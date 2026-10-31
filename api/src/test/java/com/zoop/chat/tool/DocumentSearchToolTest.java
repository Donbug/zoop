package com.zoop.chat.tool;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.response.Metadata;
import com.zoop.graph.read.CompanyDocumentsService.Document;
import com.zoop.graph.read.CompanyDocumentsService.Quote;
import com.zoop.graph.read.CompanyDocumentsService.Response;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/** D-AI-02 Q03 company documents: the public read's documents as evidence items, never a title without a quote. Synthetic only. */
class DocumentSearchToolTest {
    private static final ChatToolScope SCOPE = new ChatToolScope("job-1", "gv-1", Instant.parse("2026-10-30T00:00:00Z"));
    private static final Instant PUBLISHED = Instant.parse("2026-10-20T01:00:00Z");

    private final List<String> asked = new ArrayList<>();

    private static Document document(String id, String title, String... evidence) {
        return new Document(id, title, "합성 언론사", "https://news.example.com/" + id, PUBLISHED, "news", List.of(),
                java.util.Arrays.stream(evidence).map(e -> new Quote(e, "인용 " + e, true)).toList(), null, "v1", null, null, null,
                null);
    }

    private static Response page(String next, Document... documents) {
        return new Response(List.of(documents), new Metadata("graph", PUBLISHED, "gv-1", "trace", false, List.of()), next);
    }

    private DocumentSearchTool tool(Map<String, Response> pages) {
        return new DocumentSearchTool((company, from, version, asOf, limit, trace) -> {
            asked.add(company + "|" + from + "|" + version + "|" + asOf + "|" + limit);
            if (!pages.containsKey(company)) throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
            return pages.get(company);
        });
    }

    @Test
    void eachQuoteIsAnEvidenceItemLabelledWithItsDocument() {
        var output = tool(Map.of("KRX:000660", page(null, document("art-1", "[합성] HBM 공급", "ev-1", "ev-2"))))
                .read(SCOPE, new ChatToolRequest("document.search", List.of("KRX:000660"), 20));

        assertEquals(List.of("KRX:000660|null|gv-1|2026-10-30T00:00:00Z|20"), asked);
        assertEquals("gv-1", output.dataVersion());
        assertEquals(List.of("ev-1", "ev-2"), output.evidenceIds());
        var first = output.items().getFirst();
        assertEquals("evidence", first.kind(), "the send gate holds a title to its quote's grant");
        assertEquals("ev-1", first.id());
        assertEquals("[합성] HBM 공급 (2026-10-20T01:00:00Z)", first.label());
        assertEquals(List.of("KRX:000660"), first.companyIds());
        assertEquals(List.of("ev-1"), first.evidenceIds());
        assertFalse(output.truncated());
    }

    @Test
    void aDocumentWithNoQuoteToPassOnIsLeftOutTitleAndAll() {
        var output = tool(Map.of("KRX:000660", page(null, document("art-1", "인용 없는 문서"))))
                .read(SCOPE, new ChatToolRequest("document.search", List.of("KRX:000660"), 20));

        assertTrue(output.items().isEmpty() && output.evidenceIds().isEmpty());
    }

    @Test
    void theQuestionsPeriodBoundsTheRead() {
        Instant since = Instant.parse("2026-10-19T15:00:00Z");
        tool(Map.of("KRX:000660", page(null))).read(SCOPE,
                new ChatToolRequest("document.search", List.of("KRX:000660"), 20, null, since));

        assertEquals(List.of("KRX:000660|2026-10-19T15:00:00Z|gv-1|2026-10-30T00:00:00Z|20"), asked);
    }

    @Test
    void whatTheLimitLeftOutIsACutNeverNone() {
        var quotes = tool(Map.of("KRX:000660", page(null, document("art-1", "t", "ev-1", "ev-2"))))
                .read(SCOPE, new ChatToolRequest("document.search", List.of("KRX:000660"), 1));
        assertEquals(List.of("ev-1"), quotes.evidenceIds());
        assertTrue(quotes.truncated());

        var pages = tool(Map.of("KRX:000660", page("next", document("art-1", "t", "ev-1"))))
                .read(SCOPE, new ChatToolRequest("document.search", List.of("KRX:000660"), 20));
        assertTrue(pages.truncated(), "more documents than one page");
    }

    @Test
    void itHonoursTheNarrowedEvidenceAndNamesAQuoteOnce() {
        var both = Map.of("KRX:000660", page(null, document("art-1", "t", "ev-1", "ev-2")),
                "NASDAQ:NVDA", page(null, document("art-1", "t", "ev-1")));

        var narrowed = tool(both).read(SCOPE, new ChatToolRequest("document.search", List.of("KRX:000660"), 20, List.of("ev-2")));
        assertEquals(List.of("ev-2"), narrowed.evidenceIds());

        var shared = tool(both).read(SCOPE, new ChatToolRequest("document.search", List.of("KRX:000660", "NASDAQ:NVDA"), 20));
        assertEquals(List.of("ev-1", "ev-2"), shared.items().stream().map(ChatToolItem::id).toList());
    }

    @Test
    void aCompanyTheCatalogDoesNotKnowIsAbsentAndAReadThatFailsIsUnavailable() {
        var output = tool(Map.of("KRX:000660", page(null, document("art-1", "t", "ev-1"))))
                .read(SCOPE, new ChatToolRequest("document.search", List.of("KRX:999999", "KRX:000660"), 20));
        assertEquals(List.of("ev-1"), output.evidenceIds());

        var down = new DocumentSearchTool((c, f, v, a, l, t) -> {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        });
        assertThrows(ChatToolUnavailable.class,
                () -> down.read(SCOPE, new ChatToolRequest("document.search", List.of("KRX:000660"), 20)));
        assertThrows(ChatToolUnavailable.class, () -> tool(Map.of()).read(new ChatToolScope("job-1", null, null),
                new ChatToolRequest("document.search", List.of("KRX:000660"), 20)));
    }
}
