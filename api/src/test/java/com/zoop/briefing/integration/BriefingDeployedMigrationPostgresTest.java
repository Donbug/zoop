package com.zoop.briefing.integration;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.flywaydb.core.Flyway;
import org.flywaydb.core.api.FlywayException;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import static org.junit.jupiter.api.Assertions.*;

/** Upgrade from the last deployed a4308293 watermark, with the real default ordering policy. No model calls. */
@Tag("briefing-postgres")
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
class BriefingDeployedMigrationPostgresTest {
    private static final String DEPLOYED_VERSION = "20261030120000";
    private static final String ROUND = "brf-test-2026-10-15-morning";
    private static final Map<String, String> RENUMBERED = Map.of(
            "V20261102130000__create_briefing_personal_pools.sql", "V20261030110000__create_briefing_personal_pools.sql",
            "V20261102130100__create_briefing_member_feedback.sql", "V20261029160000__create_briefing_member_feedback.sql",
            "V20261102130200__create_admin_briefing_reprocessing.sql", "V20261030160000__create_admin_briefing_reprocessing.sql",
            "V20261102130300__connect_ai_result_feedback.sql", "V20261030161000__connect_ai_result_feedback.sql",
            "V20261102130400__preserve_archived_briefing_usage.sql", "V20261030162000__preserve_archived_briefing_usage.sql");

    @TempDir Path oldLayout;

    @Test
    void deployedDatabaseRejectsOldLayoutThenUpgradesWithoutLosingPublicationsSettingsOrUsage() throws Exception {
        assertDeployedMigrationManifest();
        String url = System.getenv("DB_URL");
        URI address = URI.create(url.substring("jdbc:".length()));
        assertTrue(List.of("localhost", "127.0.0.1", "[::1]").contains(address.getHost()), "Use a local disposable PostgreSQL");
        assertTrue(address.getPath().contains("test") || address.getPath().startsWith("/zoop_briefing_replay_"),
                "Use a test database, never a shared application database");
        String schema = "brf_deployed_upgrade_" + UUID.randomUUID().toString().replace("-", "");
        var ownerSource = new DriverManagerDataSource(url, username(), password());
        var owner = new JdbcTemplate(ownerSource);
        String extensions = owner.queryForObject("SELECT string_agg(DISTINCT n.nspname,',') FROM pg_extension e "
                + "JOIN pg_namespace n ON n.oid=e.extnamespace", String.class);
        String isolated = url + (url.contains("?") ? "&" : "?") + "currentSchema=" + schema
                + ",public" + (extensions == null ? "" : "," + extensions);
        var source = new DriverManagerDataSource(isolated, username(), password());
        var db = new JdbcTemplate(source);
        try {
            // Target is a real deployed watermark. Earlier newly introduced migrations must not leak into this baseline.
            Flyway.configure().dataSource(source).schemas(schema).defaultSchema(schema)
                    .outOfOrder(false).target(DEPLOYED_VERSION).load().migrate();
            assertEquals(DEPLOYED_VERSION, db.queryForObject("SELECT version FROM flyway_schema_history "
                    + "WHERE success AND version IS NOT NULL ORDER BY installed_rank DESC LIMIT 1", String.class));
            for (String table : List.of("briefing_feedback", "briefing_personal_pools", "briefing_reprocess_jobs", "ai_result_feedback")) {
                assertNull(db.queryForObject("SELECT to_regclass(?)::text", String.class, schema + "." + table));
            }
            try (var input = getClass().getResourceAsStream("/briefing/fixture.sql")) {
                assertNotNull(input);
                db.execute(new String(input.readAllBytes(), StandardCharsets.UTF_8));
            }
            db.update("""
                    INSERT INTO members(id,analytics_key,email,email_key,display_name,signup_method,status,created_at,
                        mode,completed,tutorial_completed,settings_version,updated_at)
                    VALUES('upgrade-member','upgrade-analytics','upgrade@example.invalid','upgrade@example.invalid',
                        '[합성] 업그레이드 시험','google','active',now(),'watchlist',true,true,7,now())
                    """);
            db.update("INSERT INTO member_watchlist(member_id,company_id,position) VALUES('upgrade-member','brf-test-company',0)");
            db.update("""
                    INSERT INTO briefing_attempts(id,round_id,attempt_no,request_key,purpose,trigger,owner_token,status,
                        started_at,finished_at,lease_until)
                    VALUES('upgrade-attempt',?,1,'upgrade-request','outlook','scheduler','upgrade-owner','completed',
                        '2026-10-15T00:21:00Z','2026-10-15T00:22:00Z','2026-10-15T00:23:00Z')
                    """, ROUND);
            db.update("""
                    INSERT INTO ai_executions(id,feature,execution_mode,status,briefing_attempt_id,provider,model,
                        started_at,finished_at,transmission_confirmed)
                    VALUES('upgrade-call','briefing-outlook','live','unknown','upgrade-attempt','authored-provider',
                        'authored-model','2026-10-15T00:21:00Z','2026-10-15T00:22:00Z',NULL)
                    """);
            Map<String, String> before = snapshot(db, false);

            // Negative control: exactly the old five filenames, not outOfOrder=true or ignored migrations.
            Path resources = Path.of(getClass().getResource("/db/migration").toURI());
            try (var files = Files.list(resources)) {
                for (Path file : files.filter(p -> p.getFileName().toString().endsWith(".sql")).toList()) {
                    String name = file.getFileName().toString();
                    Files.copy(file, oldLayout.resolve(RENUMBERED.getOrDefault(name, name)));
                }
            }
            var rejected = Flyway.configure().dataSource(source).schemas(schema).defaultSchema(schema)
                    .outOfOrder(false).locations("filesystem:" + oldLayout.toAbsolutePath()).load();
            var failure = assertThrows(FlywayException.class, rejected::migrate);
            assertTrue(failure.getMessage().contains("Detected resolved migration not applied to database"), failure.getMessage());
            assertTrue(failure.getMessage().contains("20261029160000"), failure.getMessage());
            assertTrue(failure.getMessage().contains("20261030110000"), failure.getMessage());
            assertEquals(before, snapshot(db, false));

            var upgrade = Flyway.configure().dataSource(source).schemas(schema).defaultSchema(schema).outOfOrder(false).load();
            assertTrue(upgrade.migrate().migrationsExecuted >= 5);
            upgrade.validate();
            assertEquals(before, snapshot(db, true));
            assertEquals("runtime", db.queryForObject("SELECT recording_origin FROM ai_executions WHERE id='upgrade-call'", String.class));
            assertEquals(1, db.queryForObject("SELECT count(*) FROM ai_executions WHERE id='upgrade-call' "
                    + "AND input_tokens IS NULL AND output_tokens IS NULL AND actual_cost IS NULL AND estimated_cost IS NULL "
                    + "AND reasoning_tokens IS NULL", Integer.class));
            for (var entry : RENUMBERED.entrySet()) {
                assertEquals(1, db.queryForObject("SELECT count(*) FROM flyway_schema_history WHERE script=? AND success", Integer.class, entry.getKey()));
                assertEquals(0, db.queryForObject("SELECT count(*) FROM flyway_schema_history WHERE script=?", Integer.class, entry.getValue()));
            }
            db.update("""
                    INSERT INTO briefing_feedback(id,member_id,feature,target_id,target_version,round_id,value,created_at,updated_at)
                    VALUES('upgrade-feedback','upgrade-member','briefing_round',?,'synthetic-graph-v1',?,'up',now(),now())
                    """, ROUND, ROUND);
            String feedback = rows(db, "briefing_feedback", false);
            assertEquals(0, upgrade.migrate().migrationsExecuted);
            assertEquals(feedback, rows(db, "briefing_feedback", false));
            assertEquals(before, snapshot(db, true));
            assertThrows(DataAccessException.class, () -> db.update("UPDATE briefing_rounds SET published_payload='{}'::jsonb WHERE id=?", ROUND));
            assertThrows(DataAccessException.class, () -> db.update("UPDATE briefing_attempts SET status='failed' WHERE id='upgrade-attempt'"));
        } finally {
            // Only a UUID-named schema owned by this test. No clean/repair against public or a deployed database.
            owner.execute("DROP SCHEMA IF EXISTS " + schema + " CASCADE");
        }
    }

    private static Map<String, String> snapshot(JdbcTemplate db, boolean upgraded) {
        Map<String, String> values = new LinkedHashMap<>();
        for (String table : List.of("members", "member_watchlist", "briefing_rounds", "briefing_changes", "briefing_attempts", "ai_executions")) {
            values.put(table, rows(db, table, upgraded && table.equals("ai_executions")));
        }
        return values;
    }

    private static String rows(JdbcTemplate db, String table, boolean removeNewColumn) {
        String row = removeNewColumn ? "to_jsonb(t)-'recording_origin'-'reasoning_tokens'" : "to_jsonb(t)";
        return db.queryForObject("SELECT coalesce(jsonb_agg(row ORDER BY row::text),'[]'::jsonb)::text "
                + "FROM (SELECT " + row + " AS row FROM " + table + " t) snapshot", String.class);
    }

    private void assertDeployedMigrationManifest() throws Exception {
        // Frozen file names and SHA-256 from git tree a4308293, not generated from the candidate under test.
        Map<String, String> expected = new LinkedHashMap<>();
        try (var input = getClass().getResourceAsStream("/briefing/deployed-migrations-a4308293.sha256")) {
            assertNotNull(input);
            for (String line : new String(input.readAllBytes(), StandardCharsets.UTF_8).lines().toList()) {
                if (line.isBlank() || line.startsWith("#")) continue;
                String[] fields = line.split("  ", 2);
                expected.put(fields[1], fields[0]);
            }
        }
        Map<String, String> actual = new LinkedHashMap<>();
        Path resources = Path.of(getClass().getResource("/db/migration").toURI());
        try (var files = Files.list(resources)) {
            for (Path file : files.sorted().toList()) {
                String name = file.getFileName().toString();
                if (name.matches("V[0-9]{14}__.*\\.sql") && name.substring(1, 15).compareTo(DEPLOYED_VERSION) <= 0) {
                    actual.put(name, HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(file))));
                }
            }
        }
        assertEquals(expected, actual, "Do not edit deployed SQL or introduce a migration before the deployed watermark");
    }

    private static String username() { return System.getenv().getOrDefault("DB_USERNAME", "company_test"); }
    private static String password() { return System.getenv().getOrDefault("DB_PASSWORD", ""); }
}
