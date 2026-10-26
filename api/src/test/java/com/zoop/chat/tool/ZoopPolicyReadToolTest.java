package com.zoop.chat.tool;

import static org.junit.jupiter.api.Assertions.*;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

import com.zoop.chat.service.ChatZoopDocs;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;

/** D-AI-02 Q01: {@code zoopPolicy.read} passes on the sections of the policies in effect, reading no graph. */
class ZoopPolicyReadToolTest {
    private static final Instant AS_OF = Instant.parse("2026-10-20T00:00:00Z");
    private final List<Instant> asked = new ArrayList<>();

    @Test
    void thePoliciesInEffectArePassedOnSectionBySectionInBodyOrder() {
        var output = tool(docs()).read(new ChatToolScope("job-1", null, AS_OF),
                new ChatToolRequest("zoopPolicy.read", ChatZoopDocs.POLICIES, 20));
        assertEquals("zoop-docs/policy.service@s1,policy.privacy@p1", output.dataVersion());
        assertEquals(List.of("policy.service", "policy.privacy"), output.items().stream().map(ChatToolItem::id).toList());
        assertEquals(List.of("zoop_doc", "zoop_doc"), output.items().stream().map(ChatToolItem::kind).toList());
        assertEquals(List.of("ev-s-0", "ev-s-1", "ev-p-0", "ev-p-1", "ev-p-2"), output.evidenceIds());
        assertFalse(output.truncated());
        assertEquals(List.of(AS_OF, AS_OF), asked, "the run's asOf, never the graph");
    }

    @Test
    void theLimitCutsAndSaysSoAndTheScopeIsKept() {
        var cut = tool(docs()).read(new ChatToolScope("job-1", "gv-1", null),
                new ChatToolRequest("zoopPolicy.read", ChatZoopDocs.POLICIES, 3));
        assertEquals(List.of("ev-s-0", "ev-s-1", "ev-p-0"), cut.evidenceIds());
        assertTrue(cut.truncated(), "sections left unread are never reported as none");

        var scoped = tool(docs()).read(new ChatToolScope("job-1", "gv-1", null),
                new ChatToolRequest("zoopPolicy.read", ChatZoopDocs.POLICIES, 20, List.of("ev-p-1")));
        assertEquals(List.of("ev-p-1"), scoped.evidenceIds());
        assertFalse(scoped.truncated());
    }

    @Test
    void aPolicyNotInEffectIsAbsentAndAnOutageIsUnavailable() {
        var none = tool(docs()).read(new ChatToolScope("job-1", null, null),
                new ChatToolRequest("zoopPolicy.read", List.of("policy.retired", "KRX:000660"), 20));
        assertTrue(none.items().isEmpty() && none.evidenceIds().isEmpty() && !none.truncated());
        assertEquals("zoop-docs/", none.dataVersion());

        var down = new ChatZoopDocs(null, null) {
            @Override
            public Optional<Document> inEffect(String docId, Instant asOf) {
                throw new DataAccessResourceFailureException("down");
            }
        };
        assertThrows(ChatToolUnavailable.class, () -> tool(down).read(new ChatToolScope("job-1", null, null),
                new ChatToolRequest("zoopPolicy.read", ChatZoopDocs.POLICIES, 20)));
    }

    private static ZoopPolicyReadTool tool(ChatZoopDocs docs) {
        var tool = new ZoopPolicyReadTool(docs);
        assertEquals(ChatCapability.ZOOP_POLICY_READ, tool.capability());
        return tool;
    }

    /** {@code policy.service} v s1 with two sections and {@code policy.privacy} v p1 with three; nothing else. */
    private ChatZoopDocs docs() {
        return new ChatZoopDocs(null, null) {
            @Override
            public Optional<Document> inEffect(String docId, Instant asOf) {
                asked.add(asOf);
                return switch (docId) {
                    case "policy.service" -> Optional.of(document(docId, "s1", "서비스 이용약관", "s", 2));
                    case "policy.privacy" -> Optional.of(document(docId, "p1", "개인정보 처리방침", "p", 3));
                    default -> Optional.empty();
                };
            }
        };
    }

    private static ChatZoopDocs.Document document(String docId, String version, String title, String prefix, int sections) {
        List<ChatZoopDocs.Quote> quotes = new ArrayList<>();
        for (int i = 0; i < sections; i++) {
            quotes.add(new ChatZoopDocs.Quote("ev-" + prefix + "-" + i, docId, version, title + " · " + i, "## " + i,
                    i * 10, i * 10 + 4));
        }
        return new ChatZoopDocs.Document(docId, version, title, quotes);
    }
}
