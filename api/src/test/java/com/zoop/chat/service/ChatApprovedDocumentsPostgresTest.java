package com.zoop.chat.service;

import static org.junit.jupiter.api.Assertions.*;

import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.List;

import com.zoop.chat.orchestrator.EvidenceCitationSource;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatToolRequest;
import com.zoop.chat.tool.ChatToolScope;
import com.zoop.chat.tool.ChatToolUnavailable;
import com.zoop.chat.tool.HelpSearchTool;
import com.zoop.chat.tool.ScreenSpecReadTool;
import com.zoop.document.evidence.service.EvidenceService.Readability;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;

/**
 * What the Q01 document registry must hold on a real database (implementation plan 5.1), tried on synthetic rows that every
 * test rolls back: the two fixed documents, their sections and spans, the read tools with the approved-document gate on, and
 * citations reopened before and after a document is replaced or retired. The shipped guides are tried in
 * {@link ChatZoopDocsPostgresTest}.
 */
@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
@Transactional
class ChatApprovedDocumentsPostgresTest {
    private static final String HELP_BODY = """
            # 합성 도움말

            버전 줄은 인용되지 않습니다.

            ## 지도 😀 보기

            첫 절 😀 본문입니다.

            ## 답변 읽기

            둘째 절 본문입니다.
            """;
    private static final String SCREEN_BODY = "# 합성 화면 설명\n\n## 지도 화면\n\n화면 절 본문입니다.\n";

    @Autowired ChatZoopDocs docs;
    @Autowired EvidenceReadAccess access;
    @Autowired EvidenceCitationSource citations;
    @Autowired JdbcTemplate jdbc;

    /** These tests own the registry: the shipped guides leave for the test's transaction, whose rollback restores them. */
    @BeforeEach
    void emptyTheRegistry() {
        jdbc.execute("ALTER TABLE chat_document_versions DISABLE TRIGGER USER");
        jdbc.update("DELETE FROM chat_document_versions");
        jdbc.execute("ALTER TABLE chat_document_versions ENABLE TRIGGER USER");
    }

    @Test
    void sectionsKeepCodePointSpansAndTheirIdsDependOnlyOnTheVersionedSection() {
        Instant effective = daysAgo(2);
        insert(ChatZoopDocs.HELP_GUIDE, "help", "synthetic-spans-v1", HELP_BODY, effective, null);

        var document = docs.inEffect(ChatZoopDocs.HELP_GUIDE, null).orElseThrow();

        assertEquals(2, document.quotes().size());
        for (var quote : document.quotes()) {
            assertEquals(quote.text(), HELP_BODY.substring(HELP_BODY.offsetByCodePoints(0, quote.start()),
                    HELP_BODY.offsetByCodePoints(0, quote.end())), quote.title());
            assertEquals(ChatZoopDocs.id(document.docId(), document.version(), quote.start(), quote.end(), quote.text()),
                    quote.evidenceId());
            assertEquals(quote, docs.byId(quote.evidenceId()).orElseThrow());
        }
        assertEquals("합성 승인 문서 · 지도 😀 보기", document.quotes().getFirst().title());
        assertFalse(document.quotes().getFirst().text().contains("버전 줄"), "text before the first section is no quote");
    }

    @Test
    void onlyTheTwoFixedDocumentsAreReadAndEachToolReadsItsOwn() {
        insertBoth();
        insert("help.another-guide", "help", "synthetic-other-v1", SCREEN_BODY, daysAgo(2), null);
        var help = new HelpSearchTool(docs);
        var screen = new ScreenSpecReadTool(docs);
        help.afterPropertiesSet();
        screen.afterPropertiesSet();
        var scope = new ChatToolScope("job-1", null, null);

        var helpRead = help.read(scope, request(ChatCapability.HELP_SEARCH,
                List.of(ChatZoopDocs.HELP_GUIDE, ChatZoopDocs.SCREEN_GUIDE, "help.another-guide")));
        var screenRead = screen.read(scope, request(ChatCapability.SCREEN_SPEC_READ,
                List.of(ChatZoopDocs.SCREEN_GUIDE, ChatZoopDocs.HELP_GUIDE)));

        assertEquals(List.of(ChatZoopDocs.HELP_GUIDE), helpRead.items().stream().map(item -> item.id()).toList());
        assertEquals("zoop-docs/help.service-guide@synthetic-help-v1", helpRead.dataVersion());
        assertEquals(2, helpRead.evidenceIds().size());
        assertEquals(List.of(ChatZoopDocs.SCREEN_GUIDE), screenRead.items().stream().map(item -> item.id()).toList());
        assertEquals(1, screenRead.evidenceIds().size());
        assertTrue(docs.inEffect("help.another-guide", null).isEmpty(), "an unlisted document id is never read");
    }

    @Test
    void theGateStartsOnlyWhenBothRegisteredDocumentsAreInEffect() {
        var runner = new ApplicationContextRunner()
                .withUserConfiguration(HelpSearchTool.class, ScreenSpecReadTool.class)
                .withBean(ChatZoopDocs.class, () -> docs)
                .withPropertyValues("zoop.chat.approved-docs.enabled=true");

        runner.run(context -> assertNotNull(context.getStartupFailure(), "an empty registry must not start"));
        insert(ChatZoopDocs.HELP_GUIDE, "help", "synthetic-help-v1", HELP_BODY, daysAgo(2), null);
        runner.run(context -> assertNotNull(context.getStartupFailure(), "one document alone must not start"));
        insert(ChatZoopDocs.SCREEN_GUIDE, "screen_spec", "synthetic-screen-v1", SCREEN_BODY, daysAgo(2), null);
        runner.run(context -> {
            assertNull(context.getStartupFailure());
            assertNotNull(context.getBean(HelpSearchTool.class));
            assertNotNull(context.getBean(ScreenSpecReadTool.class));
        });
    }

    @Test
    void aSectionOverTheQuoteLimitStopsTheGateAndTheRead() {
        String oversized = "# 합성\n\n## 긴 절\n\n" + "가".repeat(2_001);
        insert(ChatZoopDocs.HELP_GUIDE, "help", "synthetic-long-v1", oversized, daysAgo(2), null);
        var help = new HelpSearchTool(docs);

        assertThrows(IllegalStateException.class, help::afterPropertiesSet);
        assertThrows(ChatToolUnavailable.class, () -> help.read(new ChatToolScope("job-1", null, null),
                request(ChatCapability.HELP_SEARCH, ChatZoopDocs.HELP_DOCUMENTS)));
    }

    @Test
    void aCitationReopensWithItsVersionAndSpanUntilThatVersionIsRetired() {
        Instant asked = daysAgo(1);
        insert(ChatZoopDocs.HELP_GUIDE, "help", "synthetic-retire-v1", HELP_BODY, daysAgo(2), null);
        var quote = docs.inEffect(ChatZoopDocs.HELP_GUIDE, null).orElseThrow().quotes().getFirst();

        var citation = citations.cite(quote.evidenceId(), null, asked, "trace-1").orElseThrow();
        assertEquals("zoop_doc", citation.sourceKind());
        assertEquals(quote.docId(), citation.docId());
        assertEquals(quote.docVersion(), citation.docVersion());
        assertEquals(quote.text(), citation.quote());
        assertEquals(quote.start(), citation.start());
        assertEquals(quote.end(), citation.end());
        assertEquals(Readability.READABLE, access.readability(quote.evidenceId(), null, asked, "trace-1"));

        jdbc.update("UPDATE chat_document_versions SET retired_at = ? WHERE doc_id = ? AND version = ?",
                Timestamp.from(Instant.now().minusSeconds(60)), ChatZoopDocs.HELP_GUIDE, "synthetic-retire-v1");

        assertTrue(citations.cite(quote.evidenceId(), null, asked, "trace-1").isEmpty());
        assertEquals(Readability.DENIED, access.readability(quote.evidenceId(), null, asked, "trace-1"));
        assertTrue(docs.inEffect(ChatZoopDocs.HELP_GUIDE, null).isEmpty());
    }

    @Test
    void aReplacedVersionIsNeitherReadNorCitedEvenForAQuestionAskedWhileItWasInEffect() {
        Instant replaced = daysAgo(1);
        Instant asked = replaced.minus(Duration.ofHours(6));
        insert(ChatZoopDocs.HELP_GUIDE, "help", "synthetic-old-v1", HELP_BODY, daysAgo(3), replaced);
        String oldQuote = ChatZoopDocs.split(ChatZoopDocs.HELP_GUIDE, "synthetic-old-v1", "합성 승인 문서", HELP_BODY)
                .getFirst().evidenceId();
        insert(ChatZoopDocs.HELP_GUIDE, "help", "synthetic-new-v1", HELP_BODY, replaced, null);

        assertEquals("synthetic-new-v1", docs.inEffect(ChatZoopDocs.HELP_GUIDE, null).orElseThrow().version());
        assertTrue(docs.inEffect(ChatZoopDocs.HELP_GUIDE, asked).isEmpty());
        assertEquals("synthetic-old-v1", docs.byId(oldQuote).orElseThrow().docVersion());
        assertTrue(citations.cite(oldQuote, null, asked, "trace-1").isEmpty());
        assertEquals(Readability.DENIED, docs.check(oldQuote, null).orElseThrow());
    }

    @Test
    void theRegistryRefusesOverlappingPeriods() {
        insert(ChatZoopDocs.HELP_GUIDE, "help", "synthetic-first-v1", HELP_BODY, daysAgo(3), null);

        assertThrows(DataAccessException.class, () -> insert(ChatZoopDocs.HELP_GUIDE, "help", "synthetic-second-v1",
                HELP_BODY, daysAgo(1), null));
    }

    @Test
    void theRegistryRefusesADocumentOfTheWrongKind() {
        assertThrows(DataAccessException.class, () -> insert(ChatZoopDocs.SCREEN_GUIDE, "help", "synthetic-kind-v1",
                SCREEN_BODY, daysAgo(1), null));
    }

    private void insertBoth() {
        insert(ChatZoopDocs.HELP_GUIDE, "help", "synthetic-help-v1", HELP_BODY, daysAgo(2), null);
        insert(ChatZoopDocs.SCREEN_GUIDE, "screen_spec", "synthetic-screen-v1", SCREEN_BODY, daysAgo(2), null);
    }

    private void insert(String docId, String kind, String version, String body, Instant effective, Instant retired) {
        jdbc.update("""
                INSERT INTO chat_document_versions
                    (doc_id, kind, version, title, body, approval_ref, approved_at, effective_at, retired_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, docId, kind, version, "합성 승인 문서", body, "synthetic:test-only", Timestamp.from(effective),
                Timestamp.from(effective), retired == null ? null : Timestamp.from(retired));
    }

    private static ChatToolRequest request(ChatCapability capability, List<String> targets) {
        return new ChatToolRequest(capability.id(), targets, ChatToolRequest.MAX_LIMIT);
    }

    private static Instant daysAgo(int days) {
        return Instant.now().minus(Duration.ofDays(days));
    }
}
