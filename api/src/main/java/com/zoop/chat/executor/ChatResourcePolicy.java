package com.zoop.chat.executor;

import java.time.Duration;
import java.util.Set;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

/** Job-owned policy, frozen before the first attempt can dispatch a model request. Durations are serialized in milliseconds. */
@ConfigurationProperties("zoop.chat.resources")
public record ChatResourcePolicy(
        @DefaultValue("512000") int maxInputTokens,
        @DefaultValue("64000") int maxOutputTokens,
        @DefaultValue("16000") int maxVisibleOutputTokens,
        @DefaultValue("48000") int maxAnswerChars,
        @DefaultValue("high") String reasoningEffort,
        @DefaultValue("1200s") Duration jobTimeout,
        @DefaultValue("15s") Duration routerProviderTimeout,
        @DefaultValue("600s") Duration generationProviderTimeout,
        @DefaultValue("45s") Duration verificationProviderTimeout,
        @DefaultValue("120s") Duration directRetrievalTimeout,
        @DefaultValue("240s") Duration webSupplementTimeout) {
    public static final String REVISION = "expanded-local-2026-11-05.1";
    public static final int SERVER_TEXT_RESERVE = 1024;
    public static final Set<String> EFFORTS = Set.of("none", "low", "medium", "high", "xhigh", "max");
    public static final Duration APPLICATION_MARGIN = Duration.ofSeconds(20);
    public static final Duration HTTP_MARGIN = Duration.ofSeconds(13);
    public static final Duration CITATIONS = Duration.ofSeconds(30);
    public static final Duration COMMIT = Duration.ofSeconds(10);
    public static final Duration INITIAL_AGENT = Duration.ofSeconds(90);
    public static final Duration APPROVED_CONTINUATION = Duration.ofSeconds(120);
    public static final Duration WEB_FINAL = Duration.ofSeconds(90);

    public ChatResourcePolicy {
        if (maxInputTokens < 1 || maxInputTokens > 922000 || maxOutputTokens < 32000 || maxOutputTokens > 128000
                || (long) maxInputTokens + maxOutputTokens > 1050000 || maxVisibleOutputTokens < 4000
                || maxVisibleOutputTokens > 64000 || maxVisibleOutputTokens >= maxOutputTokens
                || maxAnswerChars < 12000 || maxAnswerChars > 96000 || !EFFORTS.contains(reasoningEffort)) throw invalid();
        for (Duration value : new Duration[]{jobTimeout, routerProviderTimeout, generationProviderTimeout,
                verificationProviderTimeout, directRetrievalTimeout, webSupplementTimeout}) {
            if (value == null || value.toMillis() < 1 || value.toMillis() > Integer.MAX_VALUE
                    || !value.equals(Duration.ofMillis(value.toMillis()))) throw invalid();
        }
        Duration finalization = generationProviderTimeout.plus(APPLICATION_MARGIN).plus(CITATIONS)
                .plus(verificationProviderTimeout).plus(APPLICATION_MARGIN).plus(COMMIT);
        Duration router = routerProviderTimeout.plus(APPLICATION_MARGIN);
        if (jobTimeout.compareTo(router.plus(directRetrievalTimeout).plus(finalization)) < 0
                || jobTimeout.compareTo(router.plus(INITIAL_AGENT).plus(APPROVED_CONTINUATION).plus(finalization)) < 0) throw invalid();
    }

    public static ChatResourcePolicy defaults() {
        return new ChatResourcePolicy(512000, 64000, 16000, 48000, "high", Duration.ofSeconds(1200),
                Duration.ofSeconds(15), Duration.ofSeconds(600), Duration.ofSeconds(45), Duration.ofSeconds(120), Duration.ofSeconds(240));
    }

    public Duration finalization() {
        return generationProviderTimeout.plus(APPLICATION_MARGIN).plus(CITATIONS)
                .plus(verificationProviderTimeout).plus(APPLICATION_MARGIN).plus(COMMIT);
    }

    /** The frozen worker estimator; each term floors separately and supplementary characters count once. */
    public static long estimatedTokens(String text) {
        long ascii = 0, other = 0;
        for (int index = 0; index < text.length();) {
            int point = text.codePointAt(index);
            if (point < 128) ascii++;
            else other++;
            index += Character.charCount(point);
        }
        return ascii / 4 + other * 3 / 4;
    }

    public static long estimatedInputTokens(String stage, JsonNode input) {
        JsonNode identified = input;
        if ("chat-agent".equals(stage)) {
            ObjectNode redacted = ((ObjectNode) input).deepCopy();
            ((ObjectNode) redacted.path("mcp")).put("authorization", "[redacted]");
            identified = redacted;
        }
        return estimatedTokens(Canonical.write(identified));
    }

    public ObjectNode snapshot() {
        return StrictJson.newObject().put("schemaVersion", "zoop-chat-resource-policy-1").put("policyRevision", REVISION)
                .put("maxInputTokens", maxInputTokens).put("maxOutputTokens", maxOutputTokens)
                .put("maxVisibleOutputTokens", maxVisibleOutputTokens).put("maxAnswerChars", maxAnswerChars)
                .put("reasoningEffort", reasoningEffort).put("jobTimeoutMs", jobTimeout.toMillis())
                .put("routerProviderTimeoutMs", routerProviderTimeout.toMillis())
                .put("generationProviderTimeoutMs", generationProviderTimeout.toMillis())
                .put("verificationProviderTimeoutMs", verificationProviderTimeout.toMillis())
                .put("directRetrievalTimeoutMs", directRetrievalTimeout.toMillis())
                .put("webSupplementTimeoutMs", webSupplementTimeout.toMillis());
    }

    public String digest() { return Canonical.digest(snapshot()); }

    public static ChatResourcePolicy fromSnapshot(JsonNode node) {
        var p = StrictJson.Obj.of(node).exactly(Set.of("schemaVersion", "policyRevision", "maxInputTokens", "maxOutputTokens",
                "maxVisibleOutputTokens", "maxAnswerChars", "reasoningEffort", "jobTimeoutMs", "routerProviderTimeoutMs",
                "generationProviderTimeoutMs", "verificationProviderTimeoutMs", "directRetrievalTimeoutMs", "webSupplementTimeoutMs"));
        if (!"zoop-chat-resource-policy-1".equals(p.string("schemaVersion")) || !REVISION.equals(p.string("policyRevision"))) throw invalid();
        return new ChatResourcePolicy(p.count("maxInputTokens"), p.count("maxOutputTokens"), p.count("maxVisibleOutputTokens"),
                p.count("maxAnswerChars"), p.string("reasoningEffort"), Duration.ofMillis(p.count("jobTimeoutMs")),
                Duration.ofMillis(p.count("routerProviderTimeoutMs")), Duration.ofMillis(p.count("generationProviderTimeoutMs")),
                Duration.ofMillis(p.count("verificationProviderTimeoutMs")), Duration.ofMillis(p.count("directRetrievalTimeoutMs")),
                Duration.ofMillis(p.count("webSupplementTimeoutMs")));
    }

    private static IllegalArgumentException invalid() { return new IllegalArgumentException("chat_resource_policy_invalid"); }
}
