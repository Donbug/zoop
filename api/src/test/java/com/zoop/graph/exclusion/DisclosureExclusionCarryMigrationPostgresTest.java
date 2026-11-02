package com.zoop.graph.exclusion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.util.UUID;

import org.flywaydb.core.Flyway;
import org.flywaydb.core.api.MigrationVersion;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

/**
 * The A-14 carry migration applied to a schema that already holds exclusion history of every earlier cause, the
 * {@code legacy-operator} and {@code publication-operator} receipt exclusions included: a forward upgrade, not an empty-database
 * check. Runs in its own schema of the disposable company test database.
 */
@Tag("graph-postgres")
class DisclosureExclusionCarryMigrationPostgresTest {
    /** The carry migration; renumbering it (merge order) changes only this constant. */
    private static final MigrationVersion CARRY = MigrationVersion.fromVersion("20261102160000");
    private static final String SHA_A = "a".repeat(64);
    private static final String SHA_B = "b".repeat(64);
    private static final String SHA_C = "c".repeat(64);
    private static final String SHA_D = "d".repeat(64);

    @Test
    void upgradeKeepsEveryExistingCauseAndOnlyAddsCarried() {
        String url = System.getenv("ZOOP_COMPANY_TEST_DB_URL");
        if (url == null || !url.matches("jdbc:postgresql://127\\.0\\.0\\.1:[0-9]+/zoop_company_test_19")) {
            throw new IllegalStateException("Set ZOOP_COMPANY_TEST_DB_URL to the dedicated localhost zoop_company_test_19 database");
        }
        String password = System.getenv().getOrDefault("ZOOP_COMPANY_TEST_DB_PASSWORD", "");
        String schema = "carry_upgrade_" + UUID.randomUUID().toString().replace("-", "");
        var owner = new JdbcTemplate(new DriverManagerDataSource(url, "company_test", password));
        String extensions = owner.queryForObject(
                "SELECT string_agg(DISTINCT n.nspname, ',') FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace",
                String.class);
        String isolated = url + "?currentSchema=" + schema + ",public" + (extensions == null ? "" : "," + extensions);
        var dataSource = new DriverManagerDataSource(isolated, "company_test", password);
        var db = new JdbcTemplate(dataSource);
        try {
            MigrationVersion before = null;
            for (var info : flyway(dataSource, schema, MigrationVersion.LATEST).info().all()) {
                if (info.getVersion() != null && info.getVersion().isNewerThan(before == null ? "0" : before.getVersion())
                        && CARRY.isNewerThan(info.getVersion().getVersion())) {
                    before = info.getVersion();
                }
            }
            flyway(dataSource, schema, before).migrate();
            for (String version : new String[] {"v-native", "v-legacy", "v-publication"}) {
                db.update("""
                        INSERT INTO artifacts (id, kind, storage_uri, sha256, bytes, media_type, created_at)
                        VALUES (?, 'graph_snapshot', ?, ?, 1, 'application/json', now())
                        """, "artifact-" + version, "artifact:" + version, "0".repeat(64));
                db.update("""
                        INSERT INTO graph_versions (id, sequence, kind, created_at, created_by, source_label, issue_count,
                            relation_count, article_count, snapshot_artifact_id, review_revision)
                        VALUES (?, (SELECT COALESCE(MAX(sequence), 0) + 1 FROM graph_versions), 'snapshot', now(), 'operator:test',
                            'carry-upgrade', 1, 1, 1, ?, 0)
                        """, version, "artifact-" + version);
            }
            change(db, 1, "exclude", "source-change", SHA_A, "v-native", "issue", "issue-1", "");
            change(db, 2, "exclude", "relation-retraction", SHA_B, "v-native", "relation", "rel-1", "");
            change(db, 3, "exclude", "legacy-operator", SHA_C, "v-legacy", "article", "article-1", SHA_A);
            change(db, 4, "exclude", "publication-operator", SHA_D, "v-publication", "evidence", "evidence-1", "");
            change(db, 5, "lift", "operator", null, "v-native", "issue", "issue-1", "");
            String changes = "SELECT jsonb_agg(to_jsonb(c) - 'base_version_id' ORDER BY revision)::text FROM disclosure_exclusion_changes c";
            String targets = "SELECT jsonb_agg(to_jsonb(t) ORDER BY revision, graph_version_id)::text FROM disclosure_exclusion_targets t";
            String changesBefore = db.queryForObject(changes, String.class);
            String targetsBefore = db.queryForObject(targets, String.class);

            Flyway upgrade = flyway(dataSource, schema, CARRY);
            assertEquals(1, upgrade.migrate().migrationsExecuted);
            assertEquals(changesBefore, db.queryForObject(changes, String.class));
            assertEquals(targetsBefore, db.queryForObject(targets, String.class));
            assertEquals(0, db.queryForObject(
                    "SELECT count(*) FROM disclosure_exclusion_changes WHERE base_version_id IS NOT NULL", Integer.class));
            assertEquals(0, upgrade.migrate().migrationsExecuted);

            // After the upgrade: carried needs its base and no report; the earlier causes refuse a base.
            change(db, 6, "exclude", "carried", null, "v-publication", "article", "article-1", SHA_A, "v-legacy");
            assertThrows(DataAccessException.class,
                    () -> change(db, 7, "exclude", "carried", null, "v-publication", "issue", "issue-2", "", null));
            assertThrows(DataAccessException.class,
                    () -> change(db, 7, "exclude", "carried", SHA_A, "v-publication", "issue", "issue-2", "", "v-legacy"));
            assertThrows(DataAccessException.class,
                    () -> change(db, 7, "exclude", "legacy-operator", SHA_C, "v-publication", "issue", "issue-2", "", "v-legacy"));
            assertThrows(DataAccessException.class,
                    () -> change(db, 7, "lift", "operator", null, "v-publication", "issue", "issue-2", "", "v-legacy"));
            change(db, 7, "exclude", "publication-operator", SHA_D, "v-publication", "issue", "issue-2", "");
            // Still append-only.
            assertThrows(DataAccessException.class,
                    () -> db.update("UPDATE disclosure_exclusion_changes SET reason = 'x' WHERE revision = 3"));
            assertEquals(7, db.queryForObject("SELECT count(*) FROM disclosure_exclusion_changes", Integer.class));
        } finally {
            owner.execute("DROP SCHEMA IF EXISTS " + schema + " CASCADE");
        }
    }

    private static Flyway flyway(DriverManagerDataSource dataSource, String schema, MigrationVersion target) {
        return Flyway.configure().dataSource(dataSource).schemas(schema).defaultSchema(schema).target(target).load();
    }

    private static void change(JdbcTemplate db, long revision, String action, String cause, String report, String version,
            String kind, String target, String articleVersion) {
        db.update("""
                INSERT INTO disclosure_exclusion_changes (revision, action, cause, report_sha256, reason, operator, changed_at)
                VALUES (?, ?, ?, ?, '합성 이력', 'operator-test', now())
                """, revision, action, cause, report);
        db.update("""
                INSERT INTO disclosure_exclusion_targets (revision, graph_version_id, target_kind, target_id, article_version)
                VALUES (?, ?, ?, ?, ?)
                """, revision, version, kind, target, articleVersion);
    }

    private static void change(JdbcTemplate db, long revision, String action, String cause, String report, String version,
            String kind, String target, String articleVersion, String base) {
        db.update("""
                INSERT INTO disclosure_exclusion_changes (revision, action, cause, report_sha256, reason, operator, changed_at,
                    base_version_id)
                VALUES (?, ?, ?, ?, '합성 이력', 'operator-test', now(), ?)
                """, revision, action, cause, report, base);
        db.update("""
                INSERT INTO disclosure_exclusion_targets (revision, graph_version_id, target_kind, target_id, article_version)
                VALUES (?, ?, ?, ?, ?)
                """, revision, version, kind, target, articleVersion);
    }
}
