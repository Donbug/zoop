package com.zoop.briefing.replay;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashSet;
import java.util.Set;
import java.util.UUID;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import static org.junit.jupiter.api.Assertions.*;

/** Two authored executions -> actual PostgreSQL. Failed prior calls remain paid history, never public text. */
@Tag("briefing-replay-postgres")
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*briefing_replay.*")
class BriefingOutlookHistoryPostgresTest {
    private static final String SCHEMA = "outlook_history_" + UUID.randomUUID().toString().replace("-", "");
    private static Path root, bundle, historyPath;
    private static byte[] bundleBytes, historyBytes;
    private static JdbcTemplate jdbc;
    private static BriefingReplayImporter importer;

    @BeforeAll static void prepare() throws Exception {
        root = Files.createTempDirectory("zoop-authored-outlook-history-").toRealPath();
        var command = new ProcessBuilder("python3", Path.of("scripts/briefing_outlook_history_fixture.py").toAbsolutePath().toString(), root.toString());
        command.environment().put("PYTHONDONTWRITEBYTECODE", "1");
        var process = command.redirectErrorStream(true).redirectOutput(root.resolve("fixture.log").toFile()).start();
        assertEquals(0, process.waitFor(), () -> log(root.resolve("fixture.log")));
        bundle = root.resolve("second/bundle-v2.json"); bundleBytes = Files.readAllBytes(bundle);
        String sha = StrictJson.parseObject(bundleBytes).object("presentationEnrichment").object("outlookHistory").string("bundleSha256");
        historyPath = root.resolve("second/market/outlook-history/" + sha + ".json"); historyBytes = Files.readAllBytes(historyPath);
        String baseUrl = System.getenv("DB_URL"), url = baseUrl + (baseUrl.contains("?") ? "&" : "?") + "currentSchema=" + SCHEMA + ",public";
        var ds = new DriverManagerDataSource(url, System.getenv().getOrDefault("DB_USERNAME", "company_test"), System.getenv().getOrDefault("DB_PASSWORD", ""));
        jdbc = new JdbcTemplate(ds);
        Flyway.configure().dataSource(ds).schemas(SCHEMA).defaultSchema(SCHEMA).load().migrate();
        jdbc.update("INSERT INTO companies(id,name) VALUES ('company-authored','합성 기업')");
        importer = new BriefingReplayImporter(jdbc, new DataSourceTransactionManager(ds),
                new BriefingReplaySettings(root.resolve("sources.jsonl"), bundle, Files.createDirectory(root.resolve("artifacts")),
                        root.resolve("grants.json"), root.resolve("manifest.json"),
                        ArtifactFileStore.sha256(Files.readAllBytes(root.resolve("sources.jsonl"))),
                        "inbox/authored-recovery.md", root.resolve("clocks.json")));
        importer.importBundle();
    }

    @BeforeEach void restoreInputs() throws Exception { Files.write(bundle, bundleBytes); Files.write(historyPath, historyBytes); }

    @AfterAll static void cleanup() throws Exception {
        if (jdbc != null) jdbc.execute("DROP SCHEMA IF EXISTS " + SCHEMA + " CASCADE");
        if (root != null) try (var paths = Files.walk(root)) {
            for (Path path : paths.sorted(java.util.Comparator.reverseOrder()).toList()) Files.deleteIfExists(path);
        }
    }

    @Test void allEightWithheldOldCallsAndEightNewCallsRetainSeparateUsageAndArtifacts() {
        StrictJson.Obj current = StrictJson.parseObject(bundleBytes), old = StrictJson.parseObject(historyBytes);
        assertEquals(8, current.object("presentationEnrichment").objects("receipts").size());
        assertEquals(8, old.object("presentationEnrichment").objects("receipts").size());
        Set<String> requests = new HashSet<>();
        for (StrictJson.Obj oldRound : old.object("presentationEnrichment").objects("rounds")) {
            StrictJson.Obj market = oldRound.object("marketEnrichment");
            if (!market.has("marketContext")) continue;
            assertEquals("WITHHELD", market.object("summaryResult").object("verification").string("status"));
            assertTrue(market.object("summaryResult").isNull("text"));
            assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM artifacts WHERE id LIKE '%-outlook-history-%-summary' AND sha256=?", Integer.class, market.string("summaryResultSha256")));
        }
        for (StrictJson.Obj receipt : current.object("presentationEnrichment").object("outlookHistory").objects("receipts")) {
            String digest = receipt.string("requestDigest"); assertTrue(requests.add(digest));
            assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM artifacts WHERE kind='ai_call_receipt' AND sha256=?", Integer.class, Canonical.digest(receipt.node())));
            assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM artifacts WHERE sha256=? AND kind='ai_submit'", Integer.class, digest));
        }
        assertEquals(8, requests.size());
        assertEquals(4, jdbc.queryForObject("SELECT count(*) FROM briefing_rounds WHERE round_date IN ('2026-10-07','2026-10-08') AND public_snapshot #>> '{marketSummary,analysis,schemaVersion}'='zoop-market-outlook-analysis-v1'", Integer.class));
        String before = originals(); assertTrue(importer.importBundle().alreadyImported()); assertEquals(before, originals());
    }

    @Test void changedOldBundleBytesAreRejectedWithoutChangingExistingPublications() throws Exception {
        String before = originals(); Files.writeString(historyPath, "{}");
        assertThrows(IllegalArgumentException.class, importer::importBundle); assertEquals(before, originals());
    }

    @Test void rehashedHistoryBundleCannotAuthorizeAlteredFrozenContext() throws Exception {
        String before = originals(); ObjectNode old = (ObjectNode) StrictJson.parseObject(historyBytes).node().deepCopy();
        ObjectNode market = null;
        for (JsonNode row : old.path("presentationEnrichment").path("rounds")) if (row.path("marketEnrichment").has("marketContext")) { market = (ObjectNode) row.path("marketEnrichment"); break; }
        assertNotNull(market);
        ((ObjectNode) market.at("/marketContext/documents/0/sources/0")).put("quote", "fabricated history evidence");
        byte[] changed = StrictJson.write(old); String sha = Canonical.sha256(changed);
        Files.write(root.resolve("second/market/outlook-history/" + sha + ".json"), changed);
        ObjectNode value = (ObjectNode) StrictJson.parseObject(bundleBytes).node().deepCopy();
        ((ObjectNode) value.at("/presentationEnrichment/outlookHistory")).put("bundleSha256", sha);
        Files.write(bundle, StrictJson.write(value));
        assertThrows(IllegalArgumentException.class, importer::importBundle); assertEquals(before, originals());
    }

    @Test void coherentProviderRecordingsStillCannotAuthorizeHistoryQuoteAbsentFromSource() throws Exception {
        String before = originals(); Path bad = Files.createTempDirectory(root, "coherent-bad-history-");
        var command = new ProcessBuilder("python3", Path.of("scripts/briefing_outlook_history_fixture.py").toAbsolutePath().toString(), bad.toString(), "--tampered-history");
        command.environment().put("PYTHONDONTWRITEBYTECODE", "1");
        var process = command.redirectErrorStream(true).redirectOutput(bad.resolve("fixture.log").toFile()).start();
        assertEquals(0, process.waitFor(), () -> log(bad.resolve("fixture.log")));
        String baseUrl = System.getenv("DB_URL"), url = baseUrl + (baseUrl.contains("?") ? "&" : "?") + "currentSchema=" + SCHEMA + ",public";
        var ds = new DriverManagerDataSource(url, System.getenv().getOrDefault("DB_USERNAME", "company_test"), System.getenv().getOrDefault("DB_PASSWORD", ""));
        var invalid = new BriefingReplayImporter(new JdbcTemplate(ds), new DataSourceTransactionManager(ds),
                new BriefingReplaySettings(bad.resolve("sources.jsonl"), bad.resolve("second/bundle-v2.json"), Files.createDirectory(bad.resolve("artifacts")),
                        bad.resolve("grants.json"), bad.resolve("manifest.json"), ArtifactFileStore.sha256(Files.readAllBytes(bad.resolve("sources.jsonl"))),
                        "inbox/authored-recovery.md", bad.resolve("clocks.json")));
        var failure = assertThrows(IllegalArgumentException.class, invalid::importBundle);
        assertTrue(failure.getMessage().contains("market_context_exact_span"), failure.getMessage());
        assertEquals(before, originals());
        assertFalse(Files.exists(bad.resolve("manifest.json")));
    }

    @Test void removingOldCallOrDuplicatingRoundCannotDropUsageOrChangeHistoryOwnership() throws Exception {
        String before = originals(); ObjectNode value = (ObjectNode) StrictJson.parseObject(bundleBytes).node().deepCopy();
        ((ArrayNode) value.at("/presentationEnrichment/outlookHistory/receipts")).remove(0);
        Files.write(bundle, StrictJson.write(value));
        assertThrows(IllegalArgumentException.class, importer::importBundle); assertEquals(before, originals());
        ObjectNode old = (ObjectNode) StrictJson.parseObject(historyBytes).node().deepCopy();
        ((ArrayNode) old.at("/presentationEnrichment/rounds")).add(old.at("/presentationEnrichment/rounds/0").deepCopy());
        byte[] changed = StrictJson.write(old); String sha = Canonical.sha256(changed);
        Files.write(root.resolve("second/market/outlook-history/" + sha + ".json"), changed);
        value = (ObjectNode) StrictJson.parseObject(bundleBytes).node().deepCopy();
        ((ObjectNode) value.at("/presentationEnrichment/outlookHistory")).put("bundleSha256", sha);
        Files.write(bundle, StrictJson.write(value));
        assertThrows(IllegalArgumentException.class, importer::importBundle); assertEquals(before, originals());
    }

    @Test void qualityV23SurvivesActualImportWithPriorHistoryAndFourVerifiedProjections() throws Exception { qualityImport(false); }
    @Test void thirdExecutionRetainsBothHistoryGenerationsAndRejectsDeepestTamper() throws Exception { qualityImport(true); }
    @Test void roleV24RequiredSlotsSurviveActualImportAndNestedHistoryWithoutNewCalls() throws Exception { qualityImport(true, true); }
    @Test void structuredV25SlotsSurviveActualImportAndNestedHistoryWithoutNewCalls() throws Exception { qualityImport(true, true, true); }

    private void qualityImport(boolean continuation) throws Exception {
        qualityImport(continuation, false);
    }

    private void qualityImport(boolean continuation, boolean role) throws Exception {
        qualityImport(continuation, role, false);
    }

    private void qualityImport(boolean continuation, boolean role, boolean structure) throws Exception {
        Path fresh = Files.createTempDirectory(root, "quality-v23-");
        var arguments = new java.util.ArrayList<>(java.util.List.of("python3", Path.of("scripts/briefing_outlook_history_fixture.py").toAbsolutePath().toString(), fresh.toString(), "--quality"));
        if (continuation) arguments.add("--continuation");
        if (role) arguments.add("--role");
        if (structure) arguments.add("--structure");
        var command = new ProcessBuilder(arguments);
        command.environment().put("PYTHONDONTWRITEBYTECODE", "1");
        var process = command.redirectErrorStream(true).redirectOutput(fresh.resolve("fixture.log").toFile()).start();
        assertEquals(0, process.waitFor(), () -> log(fresh.resolve("fixture.log")));
        String schema = "quality_" + UUID.randomUUID().toString().replace("-", "");
        String baseUrl = System.getenv("DB_URL"), url = baseUrl + (baseUrl.contains("?") ? "&" : "?") + "currentSchema=" + schema + ",public";
        var ds = new DriverManagerDataSource(url, System.getenv().getOrDefault("DB_USERNAME", "company_test"), System.getenv().getOrDefault("DB_PASSWORD", ""));
        var qualityDb = new JdbcTemplate(ds);
        try {
            Flyway.configure().dataSource(ds).schemas(schema).defaultSchema(schema).load().migrate();
            qualityDb.update("INSERT INTO companies(id,name) VALUES ('company-authored','합성 기업')");
            var qualityImporter = new BriefingReplayImporter(qualityDb, new DataSourceTransactionManager(ds),
                    new BriefingReplaySettings(fresh.resolve("sources.jsonl"), fresh.resolve((continuation ? "third" : "second") + "/bundle-v2.json"), Files.createDirectory(fresh.resolve("artifacts")),
                            fresh.resolve("grants.json"), fresh.resolve("manifest.json"), ArtifactFileStore.sha256(Files.readAllBytes(fresh.resolve("sources.jsonl"))),
                            "inbox/authored-recovery.md", fresh.resolve("clocks.json")));
            qualityImporter.importBundle();
            assertEquals(4, qualityDb.queryForObject("SELECT count(*) FROM briefing_rounds WHERE public_snapshot #>> '{marketSummary,analysis,schemaVersion}'='zoop-market-outlook-analysis-v1'", Integer.class));
            assertEquals(0, qualityDb.queryForObject("SELECT count(*) FROM briefing_rounds b CROSS JOIN LATERAL jsonb_array_elements(b.public_snapshot #> '{marketSummary,analysis,forecasts}') f WHERE jsonb_array_length(f->'conditions')<>0", Integer.class));
            assertTrue(qualityImporter.importBundle().alreadyImported());
            if (continuation) {
                var current = StrictJson.parseObject(Files.readAllBytes(fresh.resolve("third/bundle-v2.json")));
                String secondSha = current.object("presentationEnrichment").object("outlookHistory").string("bundleSha256");
                var second = StrictJson.parseObject(Files.readAllBytes(fresh.resolve("third/market/outlook-history/" + secondSha + ".json")));
                String firstSha = second.object("presentationEnrichment").object("outlookHistory").string("bundleSha256");
                assertEquals(1, qualityDb.queryForObject("SELECT count(*) FROM artifacts WHERE sha256=?", Integer.class, firstSha));
                assertEquals(1, qualityDb.queryForObject("SELECT count(*) FROM artifacts WHERE sha256=?", Integer.class, secondSha));
                String saved = qualityDb.queryForObject("SELECT json_agg(row_to_json(t) ORDER BY id)::text FROM (SELECT id,public_snapshot FROM briefing_rounds) t", String.class);
                Files.writeString(fresh.resolve("third/market/outlook-history/" + firstSha + ".json"), "{}");
                assertThrows(IllegalArgumentException.class, qualityImporter::importBundle);
                assertEquals(saved, qualityDb.queryForObject("SELECT json_agg(row_to_json(t) ORDER BY id)::text FROM (SELECT id,public_snapshot FROM briefing_rounds) t", String.class));
            }
        } finally { qualityDb.execute("DROP SCHEMA IF EXISTS " + schema + " CASCADE"); }
    }

    private static String originals() { return jdbc.queryForObject("SELECT json_agg(row_to_json(t) ORDER BY id)::text FROM (SELECT id,published_payload,public_snapshot,comparison_snapshot FROM briefing_rounds) t", String.class); }
    private static String log(Path path) { try { return Files.readString(path); } catch (Exception error) { return error.toString(); } }
}
