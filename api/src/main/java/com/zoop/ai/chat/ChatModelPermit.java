package com.zoop.ai.chat;

import java.time.Duration;
import java.util.Set;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

/** Exact allocation persisted before dispatch; reuse preserves request identity even as time advances. */
public record ChatModelPermit(String stage, String mode, JsonNode resources, int fixedInputOverheadBytes) {
    public ChatModelPermit {
        if (fixedInputOverheadBytes < 0) throw invalid();
        var r = StrictJson.Obj.of(resources).exactly(Set.of("schemaVersion", "policyRevision", "policyDigest", "runtimeFingerprint", "providerTimeoutMs", "finalizing", "luna", "allocationDigest"));
        if (!ChatStageCall.STAGES.contains(stage) || !Set.of("live", "replay").contains(mode)
                || !"zoop-chat-resource-1".equals(r.string("schemaVersion")) || r.count("providerTimeoutMs") < 1
                || !r.string("policyRevision").matches("[A-Za-z0-9._-]{1,96}")) throw invalid();
        for (String name : Set.of("policyDigest", "runtimeFingerprint", "allocationDigest")) {
            if (!StrictJson.SHA256.matcher(r.string(name)).matches()) throw invalid();
        }
        ObjectNode unsigned = ((ObjectNode) resources).deepCopy();
        unsigned.remove("allocationDigest");
        ObjectNode preimage = StrictJson.newObject().put("schemaVersion", "zoop-chat-resource-allocation-1")
                .put("stage", stage).put("mode", mode);
        preimage.set("resources", unsigned);
        if (!Canonical.digest(preimage).equals(r.string("allocationDigest"))) throw invalid();
        boolean luna = stage.equals("chat-answer") || stage.equals("chat-agent");
        if (luna == r.isNull("luna") || (!luna && r.bool("finalizing")) || stage.equals("chat-answer") && !r.bool("finalizing")) throw invalid();
        if (luna) {
            var l = r.object("luna").exactly(Set.of("maxInputTokens", "maxOutputTokens", "maxVisibleOutputTokens", "maxAnswerChars", "generatedTextMaxChars", "reasoningEffort"));
            int input = l.count("maxInputTokens"), output = l.count("maxOutputTokens"), visible = l.count("maxVisibleOutputTokens"), chars = l.count("maxAnswerChars");
            if (input < 1 || input > 922000 || output < 32000 || output > 128000 || input + output > 1050000
                    || visible < 4000 || visible > 64000 || visible >= output || chars < 12000 || chars > 96000
                    || l.count("generatedTextMaxChars") != chars - 1024
                    || !com.zoop.chat.executor.ChatResourcePolicy.EFFORTS.contains(l.string("reasoningEffort"))) throw invalid();
        }
        resources = resources.deepCopy();
    }
    @Override public JsonNode resources() { return resources.deepCopy(); }
    public Duration providerTimeout() { return Duration.ofMillis(resources.path("providerTimeoutMs").longValue()); }
    public Duration applicationTimeout() { return providerTimeout().plusSeconds(20); }
    public Duration httpTimeout() { return providerTimeout().plusSeconds(13); }
    public boolean finalizing() { return resources.path("finalizing").booleanValue(); }
    public ObjectNode binding() {
        return StrictJson.newObject().put("schemaVersion", "zoop-chat-resource-binding-1")
                .put("policyDigest", resources.path("policyDigest").stringValue())
                .put("runtimeFingerprint", resources.path("runtimeFingerprint").stringValue())
                .put("allocationDigest", resources.path("allocationDigest").stringValue());
    }
    private static IllegalArgumentException invalid() { return new IllegalArgumentException("chat_resource_policy_invalid"); }
}
