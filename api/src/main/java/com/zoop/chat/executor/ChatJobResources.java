package com.zoop.chat.executor;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import com.zoop.ai.chat.ChatModelPermit;
import com.zoop.ai.chat.ChatRuntimeCapabilities;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import tools.jackson.databind.node.ObjectNode;

/** Owns one frozen job policy and every invocation allocation, retaining finalization before admitting reads. */
public final class ChatJobResources {
    private final ChatRunControl control;
    private final ChatResourcePolicy policy;
    private final ChatRuntimeCapabilities runtime;
    private final Clock clock;
    private final String mode;

    public ChatJobResources(ChatRunControl control, ChatRuntimeCapabilities runtime, Clock clock, String mode) {
        this.control = control;
        this.policy = control.resourcePolicy();
        this.runtime = runtime;
        this.clock = clock;
        this.mode = mode;
    }
    public ChatResourcePolicy policy() { return policy; }
    public boolean contextFits(long priorInput, long priorOutput, long currentInputUnits, int approvedCalls) {
        if (priorInput < 0 || priorOutput < 0 || currentInputUnits < 0 || approvedCalls < 0 || approvedCalls > 4) return false;
        long projected = priorInput + priorOutput + currentInputUnits + runtime.fixedInputOverheadBytes("chat-agent")
                + (long) approvedCalls * 296448;
        return projected <= policy.maxInputTokens();
    }
    public Instant readCutoff() { return clock.instant().plus(control.remaining()).minus(policy.finalization()); }
    public Instant directReadCutoff() {
        Instant cap = clock.instant().plus(policy.directRetrievalTimeout());
        Instant cutoff = readCutoff();
        return cap.isBefore(cutoff) ? cap : cutoff;
    }
    public ChatModelPermit permit(String invocationId, String stage, Duration applicationBudget, boolean finalizing) {
        Duration ceiling = switch (stage) {
            case "chat-router" -> policy.routerProviderTimeout();
            case "chat-verification" -> policy.verificationProviderTimeout();
            case "chat-answer", "chat-agent" -> policy.generationProviderTimeout();
            default -> throw new IllegalArgumentException("unknown chat stage");
        };
        Duration available = applicationBudget.minus(ChatResourcePolicy.APPLICATION_MARGIN);
        Duration provider = ceiling.compareTo(available) <= 0 ? ceiling : available;
        if (provider.toMillis() < 1 || applicationBudget.compareTo(control.remaining()) > 0) throw new IllegalStateException("deadline_guard");
        ObjectNode resource = StrictJson.newObject().put("schemaVersion", "zoop-chat-resource-1")
                .put("policyRevision", ChatResourcePolicy.REVISION).put("policyDigest", policy.digest())
                .put("runtimeFingerprint", runtime.fingerprint()).put("providerTimeoutMs", provider.toMillis()).put("finalizing", finalizing);
        if (stage.equals("chat-answer") || stage.equals("chat-agent")) {
            resource.putObject("luna").put("maxInputTokens", policy.maxInputTokens()).put("maxOutputTokens", policy.maxOutputTokens())
                    .put("maxVisibleOutputTokens", policy.maxVisibleOutputTokens()).put("maxAnswerChars", policy.maxAnswerChars())
                    .put("generatedTextMaxChars", policy.maxAnswerChars() - ChatResourcePolicy.SERVER_TEXT_RESERVE)
                    .put("reasoningEffort", policy.reasoningEffort());
        } else resource.putNull("luna");
        ObjectNode preimage = StrictJson.newObject().put("schemaVersion", "zoop-chat-resource-allocation-1").put("stage", stage).put("mode", mode);
        preimage.set("resources", resource.deepCopy());
        resource.put("allocationDigest", Canonical.digest(preimage));
        ChatModelPermit permit = new ChatModelPermit(stage, mode, control.modelResources(invocationId, resource),
                runtime.fixedInputOverheadBytes(stage));
        var stored = permit.resources();
        if (!stored.path("policyDigest").asString().equals(policy.digest())
                || !stored.path("runtimeFingerprint").asString().equals(runtime.fingerprint())
                || !stored.path("policyRevision").equals(resource.path("policyRevision"))
                || !stored.path("luna").equals(resource.path("luna")) || permit.finalizing() != finalizing
                || permit.providerTimeout().compareTo(ceiling) > 0) throw new IllegalStateException("chat_resource_policy_invalid");
        return permit;
    }
}
