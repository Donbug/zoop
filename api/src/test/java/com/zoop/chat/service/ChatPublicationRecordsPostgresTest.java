package com.zoop.chat.service;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

import com.zoop.chat.tool.ChatSelectionRecord;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.junit.jupiter.api.Assertions.*;

/**
 * D-AI-02 Q08 against PostgreSQL: an issue's recorded publication at a graph version is the last review decision up to the
 * version's pinned review revision and the exact rules the version was filtered with; the decider and their note never
 * leave. Synthetic rows only.
 */
@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "zoop.chat.executor.enabled=false"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
class ChatPublicationRecordsPostgresTest {
    private static final Instant AT = Instant.parse("2026-10-20T05:00:00Z");

    @Autowired JdbcTemplate jdbc;
    @Autowired ChatPublicationRecords records;

    @Test
    void theLastDecisionUpToThePinnedRevisionAndTheVersionsOwnRulesAreTheRecord() {
        String suffix = UUID.randomUUID().toString().substring(0, 8);
        String issue = "iss-q08-" + suffix;
        long base = jdbc.queryForObject("SELECT COALESCE(MAX(global_revision), 0) FROM review_decisions", Long.class);
        String target = target(issue, suffix);
        decide(target, "reject", 1, base + 1, AT.minusSeconds(60));
        decide(target, "allow", 2, base + 2, AT);
        // A later decision than the version pinned is not part of its record.
        decide(target, "reject", 3, base + 3, AT.plusSeconds(60));
        String version = version("gv-q08-" + suffix, base + 2, 7L);
        jdbc.update("INSERT INTO graph_version_rules (graph_version_id, rule_id) VALUES (?, 'speculative-issue@1')", version);

        var record = records.publication(version, issue, "HBM 공급 계약").orElseThrow();

        assertEquals("allow", record.decision());
        assertEquals("snapshot_migration", record.decisionPath());
        assertEquals(AT, record.decidedAt());
        assertEquals(base + 2, record.reviewRevision());
        assertEquals(7L, record.ruleRevision());
        assertEquals(List.of("speculative-issue@1"), record.rules().stream().map(ChatSelectionRecord.Rule::ruleId).toList());
        assertEquals("취소·전망 이슈 숨기기", record.rules().getFirst().title());
        assertFalse(record.toString().contains("synthetic decision note"), "the decider's note never leaves");

        // Before any decision, and for an issue no review target names: no decision is recorded, nothing is made up.
        var earlier = records.publication(version("gv-q08-early-" + suffix, base, null), issue, "HBM").orElseThrow();
        assertEquals("none", earlier.decisionPath());
        assertNull(earlier.decision());
        assertNull(earlier.ruleRevision());
        assertTrue(earlier.rules().isEmpty());
        assertEquals("none", records.publication(version, "iss-unreviewed-" + suffix, "다른 사건").orElseThrow()
                .decisionPath());
        assertTrue(records.publication("gv-missing-" + suffix, issue, "HBM").isEmpty());
    }

    private String target(String issue, String suffix) {
        String id = "rt-q08-" + suffix;
        jdbc.update("""
                INSERT INTO review_targets (id, target_type, source_job_id, external_id, source_version, candidate_id, status,
                                            active, source_revision, updated_at, issue_id)
                VALUES (?, 'candidate', ?, ?, ?, ?, 'ALLOW', true, '1', ?, ?)
                """, id, "job-q08-" + suffix, "cand-" + suffix, "3".repeat(64), "cand-" + suffix, Timestamp.from(AT), issue);
        return id;
    }

    private void decide(String target, String decision, long revision, long global, Instant at) {
        jdbc.update("""
                INSERT INTO review_decisions (target_id, decision, reason, decided_at, revision, global_revision, origin)
                VALUES (?, ?, 'synthetic decision note', ?, ?, ?, 'snapshot-migration')
                """, target, decision, Timestamp.from(at), revision, global);
    }

    private String version(String id, long reviewRevision, Long ruleRevision) {
        jdbc.update("""
                INSERT INTO artifacts (id, kind, storage_uri, sha256, bytes, media_type, created_at)
                VALUES (?, 'graph_snapshot', ?, ?, 1, 'application/json', now())
                """, "artifact-" + id, "artifact:" + id, "0".repeat(64));
        jdbc.update("""
                INSERT INTO graph_versions (id, sequence, kind, created_at, created_by, source_label, issue_count,
                    relation_count, article_count, snapshot_artifact_id, review_revision, rule_revision)
                VALUES (?, (SELECT COALESCE(MAX(sequence), 0) + 1 FROM graph_versions), 'snapshot', now(), 'operator:test',
                    'q08-test', 1, 1, 1, ?, ?, ?)
                """, id, "artifact-" + id, reviewRevision, ruleRevision);
        return id;
    }
}
