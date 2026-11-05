package com.zoop.chat.executor;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Function;
import com.zoop.ai.chat.*;
import com.zoop.chat.orchestrator.ChatModels;
import com.zoop.common.json.StrictJson;
import tools.jackson.databind.JsonNode;

/** Shared Python-authored golden contract; tests replace the provider ports, not the resource wire. */
public final class ChatResourceFixtures {
    private ChatResourceFixtures() { }
    public static JsonNode contracts() {
        try {
            return StrictJson.parseObject(java.nio.file.Files.readAllBytes(java.nio.file.Path.of("..", "docs", "api", "fixtures", "chat-internal-contracts.json")))
                    .node().path("resourceContracts");
        } catch (java.io.IOException failed) { throw new java.io.UncheckedIOException(failed); }
    }
    public static ChatRuntimeCapabilities capabilities() { return new ChatRuntimeCapabilities(contracts().path("capabilities")); }
    public static ChatModels.Runtime runtime() { return (policy, agent) -> new ChatModels.RuntimeContext("replay", capabilities()); }
    public static ChatStageClient client(Function<ChatStageCall, ChatStageReply> answer) {
        return new ChatStageClient() {
            public ChatStageReply invoke(ChatStageCall call) { return answer.apply(call); }
            public ChatRuntimeCapabilities capabilities() { return ChatResourceFixtures.capabilities(); }
            public void requireTimeout(Duration required) {
                if (required.compareTo(Duration.ofSeconds(613)) > 0) throw new IllegalArgumentException("test transport ceiling");
            }
        };
    }
    public static ChatModelPermit permit(String stage) { return permit(stage, "replay"); }
    public static ChatModelPermit permit(String stage, String mode) {
        return new ChatModelPermit(stage, mode, contracts().path("allocations").path(stage + ":" + mode).path("resources"),
                capabilities().fixedInputOverheadBytes(stage));
    }

    public static String freshAttempts(String json) {
        var array = StrictJson.parseObject("{\"attempts\":" + json + "}").array("attempts").deepCopy();
        ((tools.jackson.databind.node.ObjectNode) array.get(0)).set("resourcePolicy", ChatResourcePolicy.defaults().snapshot());
        return array.toString();
    }
    public abstract static class Control implements ChatRunControl {
        private final Map<String, JsonNode> allocations = new ConcurrentHashMap<>();
        private Instant cutoff;
        protected abstract Clock resourceClock();
        public ChatResourcePolicy resourcePolicy() { return ChatResourcePolicy.defaults(); }
        public JsonNode modelResources(String invocation, JsonNode proposed) {
            return allocations.computeIfAbsent(invocation, key -> proposed.deepCopy()).deepCopy();
        }
        public void readCutoff(Instant end) { if (cutoff == null || end.isBefore(cutoff)) cutoff = end; }
        public Duration readRemaining() { return cutoff == null ? remaining() : Duration.between(resourceClock().instant(), cutoff); }
    }
}
