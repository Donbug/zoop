package com.zoop.chat.orchestrator;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.time.Instant;
import java.util.Optional;

import com.zoop.chat.service.ChatCompanyProfiles;
import com.zoop.chat.service.ChatZoopDocs;
import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.document.evidence.service.EvidenceService.Readability;
import org.junit.jupiter.api.Test;

/** The citations the server builds, field by field as the public {@code Citation} contract (docs/api/openapi.yaml) states. */
class EvidenceCitationSourceTest {
    private static final Instant AS_OF = Instant.parse("2026-10-25T00:00:00Z");

    @Test
    void aZoopDocumentSectionIsCitedWithItsDocumentVersionAndSpanAndNoArticleFields() {
        var quote = new ChatZoopDocs.Quote("ev-" + "a".repeat(64), "policy.privacy", "2026-10-13.1",
                "개인정보 처리방침 · 2. 보유 기간", "## 2. 보유 기간\n\n탈퇴하면 지웁니다.", 40, 62);
        var docs = mock(ChatZoopDocs.class);
        when(docs.byId(quote.evidenceId())).thenReturn(Optional.of(quote));
        when(docs.readability(quote, AS_OF)).thenReturn(Readability.READABLE);
        var profiles = mock(ChatCompanyProfiles.class);
        when(profiles.byId(any())).thenReturn(Optional.empty());
        var source = new EvidenceCitationSource(mock(EvidenceService.class), profiles, docs);

        var citation = source.cite(quote.evidenceId(), "gv-1", AS_OF, "trace-1").orElseThrow();
        // zoop_doc: docId·docVersion required; articleId·articleVersion·publisher·publishedAt·url null; articleTitle the title.
        assertEquals("zoop_doc", citation.sourceKind());
        assertEquals(quote.evidenceId(), citation.evidenceId());
        assertEquals(quote.text(), citation.quote());
        assertEquals("policy.privacy", citation.docId());
        assertEquals("2026-10-13.1", citation.docVersion());
        assertEquals(40, citation.start());
        assertEquals(62, citation.end());
        assertEquals(quote.title(), citation.articleTitle());
        assertNull(citation.articleId());
        assertNull(citation.articleVersion());
        assertNull(citation.publisher());
        assertNull(citation.publishedAt());
        assertNull(citation.url());

        when(docs.readability(quote, AS_OF)).thenReturn(Readability.DENIED);
        assertTrue(source.cite(quote.evidenceId(), "gv-1", AS_OF, "trace-1").isEmpty(), "a replaced version is not cited");
    }
}
