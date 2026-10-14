package com.zoop.document.analysis;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.List;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * The flat S1 registry reader and decision rule, at parity with {@code ai/service/.../grants.py}: the same strict shape, the
 * same order of denials, and never looser (a duplicate key or a date Java cannot read fails closed).
 */
class GrantRegistryTest {
    private static final Instant NOW = Instant.parse("2026-10-14T05:00:00Z");
    private static final List<String> PURPOSES = List.of("document-summary", "semantic-verification");

    private static String grant(String id, String revision, String extra) {
        return "{\"grantId\":\"" + id + "\",\"revision\":\"" + revision + "\",\"sourceId\":\"src\",\"enabled\":true,"
                + "\"rights\":\"known\",\"allowedOperations\":[\"read\",\"store\",\"model-send\",\"quote-display\"],"
                + "\"recipients\":[\"authored-replay\",\"openai-compatible:r1\"],"
                + "\"purposes\":[\"document-summary\",\"document-sentiment\",\"semantic-verification\"],"
                + "\"evidence\":[\"authored\"],\"expiresAt\":null" + extra + "}";
    }

    private static GrantRegistry registry(String... grants) {
        return GrantRegistry.parse(("{\"schemaVersion\":\"zoop-ai-s1-1\",\"grants\":[" + String.join(",", grants) + "]}")
                .getBytes(StandardCharsets.UTF_8));
    }

    private static String registryCode(Runnable action) {
        return assertThrows(AnalysisException.class, action::run).details().get("registry");
    }

    private static String decide(FlatGrant grant, String revision, List<String> recipients) {
        return GrantRegistry.evaluate(grant, "src", revision, PURPOSES, recipients, true, NOW);
    }

    private static FlatGrant current(String json) {
        return registry(json).current("g").orElseThrow();
    }

    @Test
    void theLastListedRevisionOfAGrantIsTheCurrentOne() {
        GrantRegistry registry = registry(grant("g", "r1", ""), grant("g", "r2", ""), grant("other", "r1", ""));

        assertEquals("r2", registry.current("g").orElseThrow().revision());
        assertEquals("r1", registry.current("other").orElseThrow().revision());
        assertTrue(registry.current("missing").isEmpty());
    }

    @Test
    void theSameRevisionTwiceMustBeIdenticalAndTheShapeIsClosed() {
        assertEquals("r1", registry(grant("g", "r1", ""), grant("g", "r1", "")).current("g").orElseThrow().revision());

        assertEquals("grant_revision_conflict", registryCode(() -> registry(grant("g", "r1", ""),
                grant("g", "r1", "").replace("\"enabled\":true", "\"enabled\":false"))));
        assertEquals("grant_registry_schema_invalid", registryCode(() -> registry(grant("g", "r1", ",\"extra\":1"))));
        assertEquals("grant_registry_schema_invalid",
                registryCode(() -> registry(grant("g", "r1", "").replace("\"expiresAt\":null", "\"expiresAt\":null,\"x\":1"))));
        assertEquals("grant_registry_schema_invalid", registryCode(() -> registry(grant("", "r1", ""))));
        assertEquals("grant_registry_schema_invalid",
                registryCode(() -> registry(grant("g", "r1", "").replace("\"enabled\":true", "\"enabled\":\"yes\""))));
        assertEquals("grant_registry_schema_invalid",
                registryCode(() -> registry(grant("g", "r1", "").replace("\"known\"", "\"maybe\""))));
        assertEquals("grant_registry_schema_invalid",
                registryCode(() -> registry(grant("g", "r1", "").replace("\"read\"", "\"write\""))));
        assertEquals("grant_registry_schema_invalid",
                registryCode(() -> registry(grant("g", "r1", "").replace("\"document-summary\"", "\"chat\""))));
        assertEquals("grant_registry_schema_invalid",
                registryCode(() -> GrantRegistry.parse("{\"schemaVersion\":\"other\",\"grants\":[]}".getBytes(StandardCharsets.UTF_8))));
        assertEquals("grant_registry_schema_invalid",
                registryCode(() -> GrantRegistry.parse("{\"schemaVersion\":\"zoop-ai-s1-1\"}".getBytes(StandardCharsets.UTF_8))));
    }

    @Test
    void unreadableOrOversizedRegistriesAreRefusedWithoutTheirContent(@TempDir Path temp) throws Exception {
        assertEquals("grant_registry_unreadable", registryCode(() -> GrantRegistry.parse("{not json".getBytes(StandardCharsets.UTF_8))));
        assertEquals("grant_registry_unreadable", registryCode(() -> GrantRegistry.parse(new byte[] {(byte) 0xff, (byte) 0xfe})));
        assertEquals("grant_registry_unreadable", registryCode(() -> GrantRegistry.parse(
                "{\"schemaVersion\":\"zoop-ai-s1-1\",\"schemaVersion\":\"zoop-ai-s1-1\",\"grants\":[]}".getBytes(StandardCharsets.UTF_8))));
        assertEquals("grant_registry_too_large", registryCode(() -> GrantRegistry.parse(new byte[GrantRegistry.MAX_BYTES + 1])));
        assertEquals("grant_registry_unreadable", registryCode(() -> GrantRegistry.read(temp.resolve("missing.json"))));

        Path file = temp.resolve("grants.json");
        Files.writeString(file, "{\"schemaVersion\":\"zoop-ai-s1-1\",\"grants\":[" + grant("g", "r1", "") + "]}");
        assertEquals("r1", GrantRegistry.read(file).current("g").orElseThrow().revision());
    }

    @Test
    void deniesInTheOrderOfTheServiceAndOtherwiseAllows() {
        FlatGrant ok = current(grant("g", "r1", ""));
        List<String> replay = List.of("authored-replay");
        assertNull(decide(ok, "r1", replay));
        assertNull(decide(ok, "r1", List.of("authored-replay", "openai-compatible:r1")));

        assertEquals("source_rights_unknown_or_denied", decide(null, "r1", replay));
        assertEquals("source_rights_unknown_or_denied", decide(current(grant("g", "r1", "").replace("true", "false")), "r1", replay));
        assertEquals("source_rights_unknown_or_denied",
                decide(current(grant("g", "r1", "").replace("\"known\"", "\"denied\"")), "r1", replay));
        assertEquals("source_rights_unknown_or_denied",
                decide(current(grant("g", "r1", "").replace("[\"authored\"]", "[]")), "r1", replay));
        assertEquals("grant_revision_or_source_changed", decide(ok, "r2", replay));
        assertEquals("grant_revision_or_source_changed",
                GrantRegistry.evaluate(ok, "another", "r1", PURPOSES, replay, true, NOW));
        assertEquals("source_operation_denied",
                decide(current(grant("g", "r1", "").replace("\"model-send\",", "")), "r1", replay));
        assertEquals("source_purpose_or_recipient_denied", decide(ok, "r1", List.of()));
        assertEquals("source_purpose_or_recipient_denied", decide(ok, "r1", List.of("authored-replay", "someone-else")));
        assertEquals("source_purpose_or_recipient_denied", GrantRegistry.evaluate(ok, "src", "r1",
                List.of("document-summary", "briefing-outlook"), replay, true, NOW));
    }

    @Test
    void aLiveRecipientIsOnlyRequiredWhenTheCallerCanNameIt() {
        FlatGrant ok = current(grant("g", "r1", ""));

        assertNull(GrantRegistry.evaluate(ok, "src", "r1", PURPOSES, List.of(), false, NOW));
        assertEquals("source_purpose_or_recipient_denied", GrantRegistry.evaluate(ok, "src", "r1", PURPOSES, List.of(), true, NOW));
        assertNull(decide(ok, "r1", List.of("openai-compatible:r1")));
    }

    @Test
    void naverSearchSourcesNeverReachAnAiModel() {
        for (String source : List.of("naver-search", "NAVER_SEARCH", "naver_developers_search", "Naver-Developers-Search")) {
            FlatGrant grant = registry(grant("g", "r1", "").replace("\"sourceId\":\"src\"", "\"sourceId\":\"" + source + "\""))
                    .current("g").orElseThrow();
            assertEquals("naver_search_ai_prohibited",
                    GrantRegistry.evaluate(grant, source, "r1", PURPOSES, List.of("authored-replay"), true, NOW), source);
        }
    }

    @Test
    void expiryIsInclusiveOfTheInstantItNamesAndAnUnreadableDateDeniesInsteadOfAllowing() {
        List<String> replay = List.of("authored-replay");
        String[][] cases = {
                {"2026-10-14T05:00:00Z", "source_grant_expired"},
                {"2026-10-14T04:59:59.999999Z", "source_grant_expired"},
                {"2026-10-14T14:00:00+09:00", "source_grant_expired"},
                {"2026-10-14T05:00:01Z", null},
                {"2026-10-14T14:00:01+09:00", null},
                {"2026-10-14T05:00:00", "source_grant_expiry_invalid"},
                {"2026-10-14", "source_grant_expiry_invalid"},
                {"tomorrow", "source_grant_expiry_invalid"},
                {"", "source_grant_expiry_invalid"}};
        for (String[] testCase : cases) {
            FlatGrant grant = registry(grant("g", "r1", "").replace("\"expiresAt\":null", "\"expiresAt\":\"" + testCase[0] + "\""))
                    .current("g").orElseThrow();

            assertEquals(testCase[1], decide(grant, "r1", replay), "expiresAt " + testCase[0]);
        }
    }
}
