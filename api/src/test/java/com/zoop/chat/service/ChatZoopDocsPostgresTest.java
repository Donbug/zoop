package com.zoop.chat.service;

import static org.junit.jupiter.api.Assertions.*;

import java.time.Instant;

import com.zoop.document.evidence.service.EvidenceService.Readability;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;

/**
 * The approved policies the migrations register in {@code term_versions}, read as citable sections. It only reads, so it
 * uses the plain auth-postgres properties and shares their cached context instead of opening one more connection pool.
 */
@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
class ChatZoopDocsPostgresTest {
    @Autowired ChatZoopDocs docs;
    @Autowired JdbcTemplate jdbc;

    @Test
    void theRegisteredPoliciesAreReadSectionBySectionAtTheirSpans() {
        int sections = 0;
        for (String docId : ChatZoopDocs.POLICIES) {
            var document = docs.inEffect(docId, null).orElseThrow(() -> new AssertionError(docId + " is not in effect"));
            String body = jdbc.queryForObject("SELECT body FROM term_versions WHERE term_id = ? AND version = ?",
                    String.class, docId.substring("policy.".length()), document.version());
            assertFalse(document.quotes().isEmpty(), docId);
            for (var quote : document.quotes()) {
                assertEquals(quote.text(), body.substring(body.offsetByCodePoints(0, quote.start()),
                        body.offsetByCodePoints(0, quote.end())), quote.title());
                assertTrue(quote.text().startsWith("## "), quote.title());
                assertEquals(quote, docs.byId(quote.evidenceId()).orElseThrow());
                assertEquals(Readability.READABLE, docs.check(quote.evidenceId(), null).orElseThrow());
            }
            sections += document.quotes().size();
        }
        assertTrue(sections <= 20, "one zoopPolicy.read passes on both policies whole: " + sections);
    }

    @Test
    void beforeAVersionTakesEffectItIsNeitherReadNorCitable() {
        Instant before = Instant.parse("2026-10-01T00:00:00Z");
        var quote = docs.inEffect("policy.privacy", null).orElseThrow().quotes().getFirst();
        assertTrue(docs.inEffect("policy.privacy", before).isEmpty());
        assertEquals(Readability.DENIED, docs.check(quote.evidenceId(), before).orElseThrow());
    }
}
