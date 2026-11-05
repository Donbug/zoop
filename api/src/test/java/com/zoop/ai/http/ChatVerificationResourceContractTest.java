package com.zoop.ai.http;

import static org.junit.jupiter.api.Assertions.*;

import com.zoop.ai.AiClientSettings;
import com.zoop.chat.executor.*;
import com.zoop.chat.model.ChatModelRecorder;
import com.zoop.chat.model.ChatModelStages;
import com.zoop.chat.orchestrator.*;
import com.zoop.chat.repository.ChatJobRow;
import com.zoop.chat.tool.ChatToolRegistry;
import com.zoop.chat.tool.ChatToolRunner;
import com.zoop.common.json.StrictJson;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.support.StaticListableBeanFactory;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

/** Real loopback stage responses after successful generation must not erase resource-contract failures at verification. */
class ChatVerificationResourceContractTest {
    private static final Instant NOW = Instant.parse("2026-11-05T00:00:00Z");
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final Set<String> BROKEN_REPLIES = Set.of("wrong_binding", "missing_binding", "malformed_binding", "old_schema", "unexpected_field");

    @ParameterizedTest
    @ValueSource(strings = {"chat_runtime_contract_mismatch", "chat_resource_policy_invalid", "chat_resource_binding_mismatch",
            "chat_legacy_effort_configuration", "input_budget_exceeded", "output_budget_exceeded", "chat_budget_exhausted",
            "provider_usage_invalid", "invalid_request", "request_invalid"})
    void matchingUnsentVerifierResourceRefusalIsStoredAsFailureAfterSuccessfulGeneration(String code) throws Exception {
        var observation = run(code);
        assertEquals("failed", observation.job().status());
        var failure = JSON.readTree(observation.job().failure());
        assertTrue(failure.path("retry").isNull());
        assertEquals(List.of("chat-answer", "chat-verification"), observation.stages());
        assertEquals(List.of("chat-answer:succeeded:sent", "chat-verification:failed:not_sent"), observation.recorded());
        assertNull(observation.job().result());
    }

    @ParameterizedTest
    @ValueSource(strings = {"wrong_binding", "missing_binding", "malformed_binding", "old_schema", "unexpected_field"})
    void aBrokenVerifierContractStaysUnknownAndNonRetryableAfterSuccessfulGeneration(String fault) throws Exception {
        assertUnknown(run(fault));
    }

    @Test
    void aServiceReportedBindingMismatchStaysUnknownAndNonRetryableAfterSuccessfulGeneration() throws Exception {
        assertUnknown(run("service_binding"));
    }

    @ParameterizedTest
    @ValueSource(strings = {"service_runtime", "service_request"})
    void aServiceReportedContractRefusalDoesNotBecomeACompletedAnswer(String fault) throws Exception {
        var observation = run(fault);
        assertEquals("failed", observation.job().status());
        assertTrue(JSON.readTree(observation.job().failure()).path("retry").isNull());
        assertEquals(List.of("chat-answer", "chat-verification"), observation.stages());
    }

    private static void assertUnknown(Observation observation) {
        assertEquals("failed", observation.job().status());
        var failure = JSON.readTree(observation.job().failure());
        assertEquals("response_unknown", failure.path("reason").asString());
        assertTrue(failure.path("retry").isNull());
        assertNull(observation.job().result());
        assertEquals(List.of("chat-answer", "chat-verification"), observation.stages());
        assertEquals(List.of("chat-answer:succeeded:sent", "chat-verification:unknown:unknown"), observation.recorded());
    }

    private Observation run(String injected) throws Exception {
        var stages = new ArrayList<String>();
        var recorded = new ArrayList<String>();
        try (var server = new StubAiServer(); var client = new HttpChatStageClient(AiClientSettings.ofChat(server.baseUrl(),
                StubAiServer.TOKEN, Duration.ofSeconds(3), Duration.ofSeconds(613), 2097152, Set.of()))) {
            server.respond(seen -> {
                if (seen.method().equals("GET")) return StubAiServer.Reply.json(200, ChatResourceFixtures.contracts().path("capabilities").toString());
                ObjectNode request = (ObjectNode) StrictJson.parseObject(seen.body()).node();
                String stage = request.path("stage").asString();
                stages.add(stage);
                if (stage.equals("chat-verification") && injected.startsWith("service_")) {
                    ObjectNode error = (ObjectNode) StrictJson.parseObject(StubAiServer.error(
                            injected.equals("service_binding") ? "stage_outcome_unknown"
                                    : injected.equals("service_request") ? "invalid_request" : "service_configuration_invalid",
                            false, seen.requestId(), null, null)).node();
                    ((ObjectNode) error.path("error")).put("runtimeCode", injected.equals("service_binding")
                            ? "chat_resource_binding_mismatch" : injected.equals("service_request") ? "request_invalid" : "chat_runtime_contract_mismatch");
                    return StubAiServer.Reply.json(injected.equals("service_binding") ? 502 : injected.equals("service_request") ? 422 : 503, error.toString());
                }
                ObjectNode reply = StrictJson.newObject().put("schemaVersion", "zoop-ai-chat-6")
                        .put("invocationId", request.path("invocationId").asString()).put("stage", stage);
                var binding = reply.putObject("resourceBinding").put("schemaVersion", "zoop-chat-resource-binding-1");
                for (String field : List.of("policyDigest", "runtimeFingerprint", "allocationDigest")) binding.set(field, request.path("resources").path(field));
                if (stage.equals("chat-verification") && !BROKEN_REPLIES.contains(injected)) {
                    reply.put("status", "failed").putNull("answer");
                    reply.putObject("failure").put("code", injected).put("sent", false).put("unknown", false);
                    reply.putNull("receipt");
                } else {
                    reply.put("status", "succeeded").putNull("failure");
                    ObjectNode answer = reply.putObject("answer");
                    if (stage.equals("chat-answer")) {
                        var section = answer.putArray("sections").addObject().put("basis", "general_knowledge")
                                .put("text", "고대역폭 메모리는 대역폭을 높인 메모리입니다.");
                        section.putArray("requirementIds").add("r1"); section.putArray("evidenceIds");
                        answer.putArray("insufficientRequirementIds"); answer.putArray("graphTargetIds");
                    } else {
                        var sections = answer.putArray("sections");
                        for (JsonNode section : request.path("input").path("sections")) {
                            var verdict = sections.addObject().put("prohibitedAdvice", "no");
                            var claims = verdict.putArray("claims");
                            for (JsonNode claim : section.path("claims")) claims.addObject().put("claimId", claim.path("claimId").asString())
                                    .putNull("support").put("unsupportedCausality", "no");
                        }
                    }
                    var receipt = reply.putObject("receipt").put("provider", "authored-replay").put("providerRevision", "synthetic")
                            .put("model", stage.equals("chat-answer") ? "gpt-6-luna" : "jev-1.14.0").put("promptVersion", "synthetic")
                            .put("executionMode", "replay").put("sentAt", NOW.toString()).put("receivedAt", NOW.toString());
                    receipt.putObject("usage").put("inputTokens", 100).put("outputTokens", 100).put("cachedTokens", 0).put("reasoningTokens", 0);
                }
                if (stage.equals("chat-verification")) {
                    switch (injected) {
                        case "wrong_binding" -> binding.put("allocationDigest", "0".repeat(64));
                        case "missing_binding" -> reply.remove("resourceBinding");
                        case "malformed_binding" -> reply.put("resourceBinding", "invalid");
                        case "old_schema" -> reply.put("schemaVersion", "zoop-ai-chat-5");
                        case "unexpected_field" -> reply.put("unexpected", true);
                        default -> { }
                    }
                }
                return StubAiServer.Reply.json(200, reply.toString());
            });
            var ports = new ChatModelStages(client, "replay", null, null, (id, version, asOf, trace) -> Optional.empty(),
                    article -> Optional.empty(), new ChatModelRecorder(null, Clock.fixed(NOW, ZoneOffset.UTC)) {
                        public String start(String job, int attempt, String stage, String mode) { return stage; }
                        public void finish(String id, String status, String send, com.zoop.ai.chat.ChatStageReply.Receipt receipt, String error) {
                            recorded.add(id + ":" + status + ":" + send);
                        }
                    });
            var registry = new ChatToolRegistry(List.of());
            try (var runner = new ChatToolRunner(registry); var engine = new OrchestratedChatEngine(
                    (run, bound, permit) -> new ChatRouteDecision(List.of(new ChatRouteDecision.Requirement("r1", "메모리 개념", true,
                            Map.of(ChatQueryType.Q02, .95), Map.of(), List.of(), 0, null)), null), ports, ports, registry, runner,
                    (id, version, asOf, trace) -> Optional.empty(), Clock.fixed(NOW, ZoneOffset.UTC), ports)) {
                var store = new MemoryChatStore();
                String job = "job-verifier-resource";
                store.add(new ChatJobRow(job, "conv-resource", "member-synthetic", 1, "메모리 개념", "a".repeat(64), NOW,
                        "{\"items\":[],\"evidenceCount\":0,\"period\":null,\"asOf\":null,\"graphVersion\":null}",
                        "{\"contextIds\":[],\"evidenceIds\":[],\"evidencePool\":[]}", List.of(), null, "queued", null, null,
                        null, null, 0, null, null, 0, "[{\"n\":1,\"mode\":\"run\",\"status\":\"queued\"}]", NOW, NOW, null));
                var executor = new ChatJobExecutor(store, store, new StaticListableBeanFactory(Map.of("engine", engine)).getBeanProvider(ChatEngine.class),
                        JSON, Clock.fixed(NOW, ZoneOffset.UTC), new NoChatTransactions());
                assertTrue(executor.runOnce());
                return new Observation(store.findJob(job).orElseThrow(), List.copyOf(stages), List.copyOf(recorded));
            }
        }
    }
    private record Observation(ChatJobRow job, List<String> stages, List<String> recorded) { }
}
