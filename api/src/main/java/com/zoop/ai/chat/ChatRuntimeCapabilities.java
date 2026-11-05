package com.zoop.ai.chat;

import java.util.List;
import java.util.Set;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import tools.jackson.databind.JsonNode;

/** Authenticated installed-worker capabilities. The fingerprint binds only the closed worker runtime manifest. */
public final class ChatRuntimeCapabilities {
    private static final Set<String> STAGES = ChatStageCall.STAGES;
    private static final Set<String> CREDENTIAL_ERRORS = Set.of("provider_key_required", "provider_key_invalid");
    private final JsonNode document;
    private final String fingerprint;

    public ChatRuntimeCapabilities(JsonNode document) {
        var root = StrictJson.Obj.of(document).exactly(Set.of("schemaVersion", "capabilitiesSchemaVersion", "runtimeFingerprint", "runtime", "configurationErrors"));
        equal(root.string("schemaVersion"), "zoop-ai-chat-6");
        equal(root.string("capabilitiesSchemaVersion"), "zoop-chat-capabilities-1");
        fingerprint = root.string("runtimeFingerprint");
        hash(fingerprint);
        equal(fingerprint, Canonical.digest(root.raw("runtime")));
        var runtime = root.object("runtime").exactly(Set.of("workerContractRevision", "stageSchemaVersion", "resourceSchemaVersion",
                "modelLimits", "structuralLimits", "supportedReasoningEfforts", "defaultReasoningEffort", "stages", "timeModel"));
        equal(runtime.string("workerContractRevision"), "zoop-chat-worker-resource-1");
        equal(runtime.string("stageSchemaVersion"), "zoop-ai-chat-6");
        equal(runtime.string("resourceSchemaVersion"), "zoop-chat-resource-1");
        constants(runtime.object("modelLimits"), new String[]{"contextWindowTokens", "maxInputTokens", "maxOutputTokens"}, new int[]{1050000, 922000, 128000});
        constants(runtime.object("structuralLimits"), new String[]{"maxSections", "maxClaimsPerSection", "maxCitations", "maxAnswerChars", "serverAddedTextReserveChars"}, new int[]{12,20,20,96000,1024});
        if (!runtime.strings("supportedReasoningEfforts").equals(List.of("none", "low", "medium", "high", "xhigh", "max"))) throw mismatch();
        equal(runtime.string("defaultReasoningEffort"), "medium");
        constants(runtime.object("timeModel"), new String[]{"workerProcessMarginMs", "workerTerminationGraceMs", "serviceSlotWaitMs", "httpTransportDecodeMs", "applicationModelRecordingMs", "applicationGuardMs"}, new int[]{5000,5000,1000,2000,6000,1000});
        var stages = runtime.object("stages").exactly(STAGES);
        var errors = root.object("configurationErrors").exactly(STAGES);
        for (String stage : STAGES) {
            var s = stages.object(stage).exactly(Set.of("provider", "model", "api", "adapterRevision", "adapterDigest", "providerRevision", "mcpServerRevision", "fixedInputOverheadBytes"));
            boolean luna = stage.equals("chat-answer") || stage.equals("chat-agent");
            equal(s.string("provider"), luna ? "openai-compatible" : "typesafe-native");
            equal(s.string("model"), luna ? "gpt-6-luna" : "jev-1.14.0");
            equal(s.string("api"), luna ? "responses" : "systemone");
            equal(s.string("adapterRevision"), luna ? (stage.equals("chat-answer") ? "zoop-chat-answer-resource-1" : "zoop-chat-agent-resource-1") : "zoop-jev-chat-10");
            hash(s.string("adapterDigest"));
            if (!s.isNull("providerRevision")) hash(s.string("providerRevision"));
            if (!s.isNull("mcpServerRevision")) {
                if (!stage.equals("chat-agent")) throw mismatch();
                hash(s.string("mcpServerRevision"));
            }
            int overhead = s.count("fixedInputOverheadBytes");
            if (luna ? overhead < 1 : overhead != 0) throw mismatch();
            String error = errors.stringOrNull(stage);
            if (error != null && !error.matches("[a-z0-9_]{1,64}")) throw mismatch();
        }
        this.document = document.deepCopy();
    }

    public String fingerprint() { return fingerprint; }
    public int fixedInputOverheadBytes(String stage) {
        return document.path("runtime").path("stages").path(stage).path("fixedInputOverheadBytes").intValue();
    }
    public void requireReady(String mode, boolean agent) {
        for (String stage : STAGES) {
            if (stage.equals("chat-agent") && !agent) continue;
            JsonNode error = document.path("configurationErrors").path(stage);
            if (!error.isNull() && !(mode.equals("replay") && CREDENTIAL_ERRORS.contains(error.stringValue()))) {
                throw new IllegalStateException(error.stringValue());
            }
        }
    }
    private static void constants(StrictJson.Obj object, String[] keys, int[] values) {
        object.exactly(Set.of(keys));
        for (int i = 0; i < keys.length; i++) if (object.count(keys[i]) != values[i]) throw mismatch();
    }
    private static void equal(String actual, String expected) { if (!expected.equals(actual)) throw mismatch(); }
    private static void hash(String value) { if (!StrictJson.SHA256.matcher(value).matches()) throw mismatch(); }
    private static IllegalArgumentException mismatch() { return new IllegalArgumentException("chat_runtime_contract_mismatch"); }
}
