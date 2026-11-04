package com.zoop.document.analysis;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.List;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Strict S1 parsing and model admission remain at parity with {@code ai/service/.../grants.py}. Stored briefing reads use
 * display operations without granting model admission. Invalid authority still fails closed in both paths.
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
    void storedBriefingReadDoesNotRequireNewStorageModelSendOrVerification() {
        String readJson = grant("g", "r1", "").replace("\"store\",\"model-send\",", "")
                .replace("\"document-summary\",\"document-sentiment\",\"semantic-verification\"", "\"briefing-outlook\"");
        FlatGrant readOnly = current(readJson);
        List<String> recipients = List.of("authored-replay");
        assertNull(GrantRegistry.evaluateBriefingRead(readOnly, "src", "r1", recipients, NOW));
        assertEquals("source_operation_denied", GrantRegistry.evaluate(readOnly, "src", "r1",
                List.of("briefing-outlook", "semantic-verification"), recipients, true, NOW));
        FlatGrant noVerifier = current(readJson.replace("[\"read\",\"quote-display\"]",
                "[\"read\",\"store\",\"model-send\",\"quote-display\"]"));
        assertEquals("source_purpose_or_recipient_denied", GrantRegistry.evaluate(noVerifier, "src", "r1",
                List.of("briefing-outlook", "semantic-verification"), recipients, true, NOW));
    }

    @Test
    void storedBriefingStillNeedsCurrentExplicitReadAndQuoteAuthority() {
        String readJson = grant("g", "r1", "").replace("\"document-summary\"", "\"briefing-outlook\"");
        List<String> recipients = List.of("authored-replay");
        for (String operation : List.of("read", "quote-display")) {
            String reduced = readJson.replace("\"" + operation + "\",", "").replace(",\"" + operation + "\"", "");
            assertEquals("source_operation_denied", GrantRegistry.evaluateBriefingRead(current(reduced), "src", "r1", recipients, NOW));
        }
        for (String rights : List.of("unknown", "denied")) {
            assertEquals("source_rights_unknown_or_denied", GrantRegistry.evaluateBriefingRead(
                    current(readJson.replace("\"known\"", "\"" + rights + "\"")), "src", "r1", recipients, NOW));
        }
        assertEquals("source_rights_unknown_or_denied", GrantRegistry.evaluateBriefingRead(null, "src", "r1", recipients, NOW));
        assertEquals("source_rights_unknown_or_denied", GrantRegistry.evaluateBriefingRead(
                current(readJson.replace("\"enabled\":true", "\"enabled\":false")), "src", "r1", recipients, NOW));
        assertEquals("source_rights_unknown_or_denied", GrantRegistry.evaluateBriefingRead(
                current(readJson.replace("[\"authored\"]", "[]")), "src", "r1", recipients, NOW));
        assertEquals("grant_revision_or_source_changed", GrantRegistry.evaluateBriefingRead(current(readJson), "src", "other", recipients, NOW));
        assertEquals("grant_revision_or_source_changed", GrantRegistry.evaluateBriefingRead(current(readJson), "other", "r1", recipients, NOW));
        assertEquals("source_purpose_or_recipient_denied", GrantRegistry.evaluateBriefingRead(current(readJson), "src", "r1", List.of(), NOW));
        assertEquals("source_purpose_or_recipient_denied", GrantRegistry.evaluateBriefingRead(current(readJson), "src", "r1", List.of("ungranted"), NOW));
        assertEquals("source_purpose_or_recipient_denied", GrantRegistry.evaluateBriefingRead(
                current(readJson.replace("\"briefing-outlook\"", "\"document-summary\"")), "src", "r1", recipients, NOW));
        assertEquals("source_grant_expired", GrantRegistry.evaluateBriefingRead(
                current(readJson.replace("\"expiresAt\":null", "\"expiresAt\":\"2026-10-14T05:00:00Z\"")), "src", "r1", recipients, NOW));
        assertEquals("source_grant_expiry_invalid", GrantRegistry.evaluateBriefingRead(
                current(readJson.replace("\"expiresAt\":null", "\"expiresAt\":\"tomorrow\"")), "src", "r1", recipients, NOW));
        assertEquals("naver_search_ai_prohibited", GrantRegistry.evaluateBriefingRead(
                current(readJson.replace("\"sourceId\":\"src\"", "\"sourceId\":\"naver-search\"")), "naver-search", "r1", recipients, NOW));
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
    @Test
    void delegatedOwnersRemainFreshWithoutCopyingOrOverridingTheirGrants(@TempDir Path root) throws Exception {
        Path original=root.resolve("original.json"),added=root.resolve("added.json"),index=root.resolve("index.json");
        String originalValue="{\"schemaVersion\":\"zoop-ai-s1-1\",\"grants\":["+grant("g","r1","")+"]}";
        Files.writeString(original,originalValue);Files.writeString(added,originalValue.replace("\"g\"","\"other\""));
        var pointer=com.zoop.common.json.StrictJson.newObject().put("schemaVersion","zoop-grant-authority-delegates-1");pointer.putArray("delegates").add(original.toString()).add(added.toString());Files.write(index,com.zoop.common.json.Canonical.bytes(pointer));
        assertTrue(GrantRegistry.read(index).current("g").orElseThrow().enabled());
        Files.writeString(original,originalValue.replace("\"enabled\":true","\"enabled\":false"));
        assertFalse(GrantRegistry.read(index).current("g").orElseThrow().enabled());
        Files.writeString(added,originalValue);
        assertEquals("grant_authority_conflict",registryCode(()->GrantRegistry.read(index)));
    }
}
