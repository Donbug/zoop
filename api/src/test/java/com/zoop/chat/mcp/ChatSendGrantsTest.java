package com.zoop.chat.mcp;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.chat.service.ChatCompanyProfiles;
import com.zoop.chat.service.ChatZoopDocs;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/**
 * The model-send gate's reading of the operator chat grant registry: the AI runtime's rule for the {@code chat-agent} stage,
 * read again for every check, and nothing allowed by a registry that cannot be used. Synthetic registries only.
 */
class ChatSendGrantsTest {
    static final String RECIPIENT = "openai-compatible:rev-1";
    /** The source the synthetic tools' evidence belongs to. */
    static final String EVIDENCE_SOURCE = "test-news";
    private static final Clock CLOCK = Clock.fixed(ChatMcpGrantsTest.NOW, ZoneOffset.UTC);

    @TempDir
    Path dir;

    /** A grant entry that allows sending {@code source} to the agent; {@code changes} replace fields. */
    static Map<String, Object> grant(String source, Map<String, Object> changes) {
        Map<String, Object> grant = new LinkedHashMap<>();
        grant.put("grantId", "g-" + source);
        grant.put("revision", "1");
        grant.put("sourceId", source);
        grant.put("enabled", true);
        grant.put("rights", "known");
        grant.put("allowedOperations", List.of("read", "model-send", "quote-display"));
        grant.put("recipients", List.of(RECIPIENT));
        grant.put("purposes", List.of("chat-answer", "chat-agent"));
        grant.put("evidence", List.of("synthetic"));
        grant.put("expiresAt", null);
        grant.putAll(changes);
        return grant;
    }

    /** Writes a registry allowing {@code sources} (none listed: an empty registry) to {@code file}. */
    static Path write(Path file, String... sources) {
        List<Map<String, Object>> grants = new ArrayList<>();
        for (String source : sources) grants.add(grant(source, Map.of()));
        return write(file, grants);
    }

    static Path write(Path file, List<Map<String, Object>> grants) {
        String json = tools.jackson.databind.json.JsonMapper.builder().build()
                .writeValueAsString(Map.of("schemaVersion", "zoop-ai-chat-1", "grants", grants));
        try {
            return Files.writeString(file, json, StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    /** A gate over a registry in {@code dir} allowing everything the synthetic tools return; all evidence is placed. */
    static ChatMcpSendGate gate(Path dir) {
        Path file = write(dir.resolve("chat-grants.json"), ChatCompanyProfiles.SOURCE_ID, ChatZoopDocs.SOURCE_ID,
                ChatMcpSendGate.GRAPH_SOURCE_ID, EVIDENCE_SOURCE);
        return new ChatMcpSendGate(new ChatSendGrants(file.toString(), RECIPIENT, CLOCK), (run, ids) -> {
            Map<String, String> placed = new LinkedHashMap<>();
            ids.forEach(id -> placed.put(id, EVIDENCE_SOURCE));
            return placed;
        });
    }

    private ChatSendGrants grants(List<Map<String, Object>> entries) {
        return new ChatSendGrants(write(dir.resolve("chat-grants.json"), entries).toString(), RECIPIENT, CLOCK);
    }

    @Test
    void onlyAnEnabledKnownModelSendGrantForTheAgentRecipientAndPurposeAllowsASource() {
        var sendable = grants(List.of(grant("ok", Map.of()),
                grant("disabled", Map.of("enabled", false)),
                grant("unknown", Map.of("rights", "unknown")),
                grant("read-only", Map.of("allowedOperations", List.of("read", "quote-display"))),
                grant("answer-only", Map.of("purposes", List.of("chat-answer", "chat-verification"))),
                grant("other-recipient", Map.of("recipients", List.of("openai-compatible:rev-0"))),
                grant("expired", Map.of("expiresAt", "2026-10-27T09:00:00+09:00")),
                grant("later", Map.of("expiresAt", "2026-12-31T00:00:00Z")))).sendable();
        assertTrue(sendable.test("ok"));
        assertTrue(sendable.test("later"));
        for (String denied : List.of("disabled", "unknown", "read-only", "answer-only", "other-recipient", "expired",
                "absent")) {
            assertFalse(sendable.test(denied), denied);
        }
        assertFalse(sendable.test(null), "unplaced evidence has no source");
    }

    @Test
    void theRegistryIsReadAgainSoAWithdrawnGrantAppliesToTheNextCheck() {
        Path file = write(dir.resolve("chat-grants.json"), "news");
        var grants = new ChatSendGrants(file.toString(), RECIPIENT, CLOCK);
        assertTrue(grants.sendable().test("news"));
        write(file, List.of(grant("news", Map.of("enabled", false))));
        assertFalse(grants.sendable().test("news"));
    }

    @Test
    void aRegistryThatCannotBeUsedAllowsNothing() throws IOException {
        Path file = dir.resolve("chat-grants.json");
        var grants = new ChatSendGrants(file.toString(), RECIPIENT, CLOCK);
        assertThrows(ChatSendGrants.Unavailable.class, grants::sendable, "missing");
        for (String broken : List.of("", "[]", "{\"schemaVersion\":\"zoop-ai-s1-1\",\"grants\":[]}",
                "{\"schemaVersion\":\"zoop-ai-chat-1\",\"grants\":[],\"extra\":1}",
                "{\"schemaVersion\":\"zoop-ai-chat-1\",\"grants\":[],\"grants\":[]}")) {
            Files.writeString(file, broken, StandardCharsets.UTF_8);
            assertThrows(ChatSendGrants.Unavailable.class, grants::sendable, broken);
        }
        for (Map<String, Object> change : List.<Map<String, Object>>of(Map.of("unexpected", 1),
                Map.of("rights", "maybe"), Map.of("allowedOperations", List.of("store")),
                Map.of("purposes", List.of("chat-agent", "briefing")), Map.of("expiresAt", "2026-12-31T00:00:00"),
                Map.of("sourceId", ""), Map.of("enabled", "true"))) {
            write(file, List.of(grant("ok", Map.of()), grant("bad", change)));
            assertThrows(ChatSendGrants.Unavailable.class, grants::sendable, change.toString());
        }
        Files.write(file, new byte[ChatSendGrants.MAX_REGISTRY_BYTES + 1]);
        assertThrows(ChatSendGrants.Unavailable.class, grants::sendable, "too large");
    }

    @Test
    void theSettingsMustNameAnAbsolutePathAndARecipient() {
        String file = dir.resolve("chat-grants.json").toString();
        for (String[] settings : List.of(new String[] {"", RECIPIENT}, new String[] {"chat-grants.json", RECIPIENT},
                new String[] {dir.resolve("a/../chat-grants.json").toString(), RECIPIENT}, new String[] {file, ""},
                new String[] {file, " " + RECIPIENT})) {
            var refused = assertThrows(IllegalArgumentException.class,
                    () -> new ChatSendGrants(settings[0], settings[1], CLOCK));
            assertTrue(refused.getMessage().contains("ZOOP_CHAT_MCP_SEND_GRANTS"));
        }
    }
}
