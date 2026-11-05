package com.zoop.chat.executor;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import com.zoop.ai.AiClientSettings;
import com.zoop.ai.chat.ChatModelPermit;
import com.zoop.ai.chat.ChatRuntimeCapabilities;
import com.zoop.common.json.Canonical;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

class ChatResourcePolicyTest {
    private final Instant now = Instant.parse("2026-11-05T00:00:00Z");
    @Test
    void explicitInputEstimatorMatchesTheFrozenCodePointAndFlooringRules() {
        assertEquals(1, ChatResourcePolicy.estimatedTokens("abcd"));
        assertEquals(3, ChatResourcePolicy.estimatedTokens("가나다라"));
        assertEquals(0, ChatResourcePolicy.estimatedTokens("a가"));
        assertEquals(4, ChatResourcePolicy.estimatedTokens("abcd가나다라"));
        assertEquals(3, ChatResourcePolicy.estimatedTokens("😀😀😀😀"));
    }


    @Test
    void canonicalPolicyAndEveryAllocationMatchTheWorkerGoldenContract() {
        var fixture = ChatResourceFixtures.contracts();
        var policy = ChatResourcePolicy.defaults();
        assertEquals(Canonical.write(fixture.path("policy")), Canonical.write(policy.snapshot()));
        assertEquals("4b7bd28cb76bfd9b914a95df214a26b644daaae8f7d4f0696678a511fbbd4813", policy.digest());
        assertEquals(Duration.ofSeconds(725), policy.finalization());
        for (String stage : com.zoop.ai.chat.ChatStageCall.STAGES) {
            for (String mode : Set.of("live", "replay")) {
                var resources = owner(policy, mode);
                Duration timeout = stage.equals("chat-router") ? Duration.ofSeconds(35)
                        : stage.equals("chat-verification") ? Duration.ofSeconds(65) : Duration.ofSeconds(620);
                var permit = resources.permit("job-test.1." + stage, stage, timeout, stage.equals("chat-answer"));
                assertEquals(Canonical.write(fixture.path("allocations").path(stage + ":" + mode).path("resources")), Canonical.write(permit.resources()));
                assertEquals(fixture.path("allocations").path(stage + ":" + mode).path("binding"), permit.binding());
            }
        }
    }

    @Test
    void identicalInvocationKeepsItsOriginalTimeoutAsRemainingTimeChanges() {
        var resources = owner(ChatResourcePolicy.defaults(), "replay");
        var first = resources.permit("job-test.1.agent-1", "chat-agent", Duration.ofSeconds(200), false);
        var repeated = resources.permit("job-test.1.agent-1", "chat-agent", Duration.ofSeconds(150), false);
        assertEquals(first.resources(), repeated.resources());
        assertEquals(Duration.ofSeconds(180), repeated.providerTimeout());
        assertEquals(Duration.ofSeconds(193), repeated.httpTimeout());
    }

    @Test
    void currentContextCanAdmitNineOrTwelveThousandTokensButReservesUnknownCallbacksIndividually() {
        var resources = owner(ChatResourcePolicy.defaults(), "replay");
        assertTrue(resources.contextFits(9000, 100, 4096, 1));
        assertTrue(resources.contextFits(12001, 100, 4096, 1));
        assertFalse(resources.contextFits(12001, 100, 4096, 2));
        assertFalse(resources.contextFits(512000, 100, 4096, 0));
    }

    @Test
    void configuredOutputCanReachTheModelCardMaximumAndInvalidCoupledLimitsRefuse() {
        var policy = policy(512000, 128000, "max");
        ChatModelPermit permit = owner(policy, "replay").permit("job-test.1.answer", "chat-answer", Duration.ofSeconds(620), true);
        assertEquals(128000, permit.resources().path("luna").path("maxOutputTokens").intValue());
        assertEquals("max", permit.resources().path("luna").path("reasoningEffort").stringValue());
        assertThrows(IllegalArgumentException.class, () -> policy(512000, 128001, "high"));
        assertThrows(IllegalArgumentException.class, () -> policy(922001, 64000, "high"));
        assertEquals(922000, policy(922000, 128000, "high").maxInputTokens());
        assertThrows(IllegalArgumentException.class, () -> policy(512000, 64000, "unsupported"));
    }

    @Test
    void authenticatedDirectOnlyCapabilitiesIgnoreUnavailableAgentButRejectDriftedManifests() {
        ObjectNode value = (ObjectNode) ChatResourceFixtures.contracts().path("capabilities").deepCopy();
        ((ObjectNode) value.path("configurationErrors")).put("chat-agent", "mcp_server_url_required");
        ((ObjectNode) value.path("runtime").path("stages").path("chat-agent")).putNull("mcpServerRevision");
        value.put("runtimeFingerprint", Canonical.digest(value.path("runtime")));
        var runtime = new ChatRuntimeCapabilities(value);
        assertDoesNotThrow(() -> runtime.requireReady("replay", false));
        assertThrows(IllegalStateException.class, () -> runtime.requireReady("replay", true));
        ((ObjectNode) value.path("runtime").path("timeModel")).put("workerProcessMarginMs", 4999);
        value.put("runtimeFingerprint", Canonical.digest(value.path("runtime")));
        assertThrows(IllegalArgumentException.class, () -> new ChatRuntimeCapabilities(value));
    }

    @Test
    void replayIgnoresExactlyCredentialOnlyReadinessErrorsWhileLiveRejectsThem() {
        for (String code : java.util.List.of("provider_key_required", "provider_key_invalid", "provider_model_required",
                "chat_legacy_effort_configuration", "chat_resource_policy_invalid")) {
            var value = (ObjectNode) ChatResourceFixtures.contracts().path("capabilities").deepCopy();
            var errors = (ObjectNode) value.path("configurationErrors");
            for (String stage : com.zoop.ai.chat.ChatStageCall.STAGES) errors.putNull(stage);
            errors.put("chat-answer", code);
            var runtime = new ChatRuntimeCapabilities(value);
            if (code.equals("provider_key_required") || code.equals("provider_key_invalid")) {
                assertDoesNotThrow(() -> runtime.requireReady("replay", false), code);
            } else {
                assertEquals(code, assertThrows(IllegalStateException.class, () -> runtime.requireReady("replay", false), code).getMessage());
            }
            assertEquals(code, assertThrows(IllegalStateException.class, () -> runtime.requireReady("live", false), code).getMessage());
        }
    }

    @Test
    void standardClientsRetainTheirCeilingWhileChatAcceptsNegotiatedTimeouts() {
        String token = "synthetic-chat-service-token-00000001";
        assertThrows(com.zoop.ai.AiClientConfigurationException.class, () -> AiClientSettings.of("http://127.0.0.1:1", token,
                Duration.ofSeconds(3), Duration.ofSeconds(121), 65536));
        assertEquals(Duration.ofSeconds(613), AiClientSettings.ofChat("http://127.0.0.1:1", token,
                Duration.ofSeconds(3), Duration.ofSeconds(613), 65536, Set.of()).requestTimeout());
    }

    private ChatJobResources owner(ChatResourcePolicy policy, String mode) {
        ChatRunControl control = mock(ChatRunControl.class);
        when(control.resourcePolicy()).thenReturn(policy);
        when(control.remaining()).thenReturn(Duration.ofSeconds(1200));
        var persisted = new ConcurrentHashMap<String, JsonNode>();
        when(control.modelResources(anyString(), any())).thenAnswer(call -> persisted.computeIfAbsent(call.getArgument(0),
                key -> ((JsonNode) call.getArgument(1)).deepCopy()).deepCopy());
        return new ChatJobResources(control, ChatResourceFixtures.capabilities(), Clock.fixed(now, java.time.ZoneOffset.UTC), mode);
    }

    private static ChatResourcePolicy policy(int input, int output, String effort) {
        var p = ChatResourcePolicy.defaults();
        return new ChatResourcePolicy(input, output, p.maxVisibleOutputTokens(), p.maxAnswerChars(), effort,
                p.jobTimeout(), p.routerProviderTimeout(), p.generationProviderTimeout(), p.verificationProviderTimeout(),
                p.directRetrievalTimeout(), p.webSupplementTimeout());
    }
}
