package com.zoop.briefing.replay;

import com.zoop.ZoopApplication;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.StrictJson;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.util.UUID;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.boot.web.server.servlet.context.ServletWebServerApplicationContext;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import static org.junit.jupiter.api.Assertions.*;

/** Authored provider answers through the actual opt-in importer, PostgreSQL and public HTTP reader. */
@Tag("briefing-replay-postgres")
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*briefing_replay.*")
class BriefingGroupedReplayPostgresTest {
    private static final String SCHEMA = "grouped_replay_" + UUID.randomUUID().toString().replace("-", "");
    private static Path root, bundle, grants, manifest;
    private static JdbcTemplate jdbc;
    private static BriefingReplayImporter importer;
    private static ConfigurableApplicationContext server;
    private static int port;

    @BeforeAll static void prepare() throws Exception {
        root = Files.createTempDirectory("zoop-authored-grouped-replay-").toRealPath();
        ProcessBuilder command = new ProcessBuilder("python3", Path.of("scripts/briefing_grouped_fixture.py").toAbsolutePath().toString(), root.toString());
        command.environment().put("PYTHONDONTWRITEBYTECODE", "1");
        Process process = command.redirectErrorStream(true).redirectOutput(root.resolve("fixture.log").toFile()).start();
        assertEquals(0, process.waitFor(), () -> "Authored grouped fixture failed; inspect " + root.resolve("fixture.log"));
        bundle = root.resolve("output/bundle-v2.json"); grants = root.resolve("grants.json"); manifest = root.resolve("manifest.json");
        Path artifacts = Files.createDirectory(root.resolve("artifacts"));
        var datasource = new DriverManagerDataSource(url(), username(), password()); jdbc = new JdbcTemplate(datasource);
        // Both owned schemas use the same extension; keep its operators in the shared test DB public schema.
        jdbc.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public");
        jdbc.execute("CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public");
        Flyway.configure().dataSource(datasource).schemas(SCHEMA).defaultSchema(SCHEMA).load().migrate();
        jdbc.update("INSERT INTO companies(id,name) VALUES ('company-authored','합성 기업')");
        importer = new BriefingReplayImporter(jdbc, new DataSourceTransactionManager(datasource),
                new BriefingReplaySettings(root.resolve("sources.jsonl"), bundle, artifacts, grants, manifest,
                        ArtifactFileStore.sha256(Files.readAllBytes(root.resolve("sources.jsonl"))),
                        "inbox/authored-grouped-run.md", root.resolve("clocks.json")));
        importer.importBundle();
        server = new SpringApplicationBuilder(ZoopApplication.class).web(WebApplicationType.SERVLET).profiles("local")
                .run("--server.port=0", "--server.address=127.0.0.1", "--spring.datasource.url=" + url(),
                        "--spring.datasource.username=" + username(), "--spring.datasource.password=" + password(),
                        "--spring.flyway.schemas=" + SCHEMA, "--spring.flyway.default-schema=" + SCHEMA,
                        "--spring.jpa.properties.hibernate.default_schema=" + SCHEMA,
                        "--ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test", "--ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                        "--zoop.briefing.replay.read-enabled=true", "--zoop.briefing.replay.manifest=" + manifest,
                        "--zoop.document-read.grants=" + grants, "--zoop.document-read.artifact-root=" + artifacts);
        port = ((ServletWebServerApplicationContext) server).getWebServer().getPort();
    }

    @AfterAll static void cleanup() throws Exception {
        if (server != null) server.close();
        if (jdbc != null) jdbc.execute("DROP SCHEMA IF EXISTS " + SCHEMA + " CASCADE");
        if (root != null) try (var paths = Files.walk(root)) {
            for (Path path : paths.sorted(java.util.Comparator.reverseOrder()).toList()) Files.deleteIfExists(path);
        }
    }

    @Test void acceptedGroupedIssuesReachAllFourteenHttpRoundsAndIdenticalImportIsImmutable() throws Exception {
        assertEquals(14, jdbc.queryForObject("SELECT count(*) FROM briefing_rounds WHERE published_at IS NOT NULL", Integer.class));
        assertEquals(14, jdbc.queryForObject("SELECT count(*) FROM articles", Integer.class));
        assertEquals(42, jdbc.queryForObject("SELECT count(*) FROM artifacts WHERE kind='ai_call_receipt'", Integer.class));
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM artifacts WHERE id LIKE '%-grouped-issues'", Integer.class));
        HttpClient http = HttpClient.newHttpClient();
        for (int index = 0; index < 14; index++) {
            String date = LocalDate.of(2026, 10, 2).plusDays(index / 2).toString();
            String edition = index % 2 == 0 ? "morning" : "evening";
            var response = http.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port
                    + "/api/v1/briefings?date=" + date + "&edition=" + edition)).GET().build(), HttpResponse.BodyHandlers.ofString());
            assertEquals(200, response.statusCode(), response.body());
            StrictJson.Obj payload = StrictJson.parseObject(response.body());
            assertEquals("published", payload.string("status")); assertEquals(1, payload.array("items").size());
            StrictJson.Obj item = payload.objects("items").getFirst();
            assertEquals("stable-authored-issue-" + index, item.string("eventId"));
            assertTrue(item.string("title").contains("건물 관리 기술"));
            assertEquals("company-authored", item.objects("companies").getFirst().string("id"));
        }
        String rows = jdbc.queryForObject("SELECT md5(string_agg(row_to_json(r)::text, '' ORDER BY id)) FROM briefing_rounds r", String.class);
        byte[] originalManifest = Files.readAllBytes(manifest), originalGrants = Files.readAllBytes(grants), originalBundle = Files.readAllBytes(bundle);
        int artifacts = jdbc.queryForObject("SELECT count(*) FROM artifacts", Integer.class);
        assertTrue(importer.importBundle().alreadyImported());
        assertEquals(rows, jdbc.queryForObject("SELECT md5(string_agg(row_to_json(r)::text, '' ORDER BY id)) FROM briefing_rounds r", String.class));
        assertEquals(artifacts, jdbc.queryForObject("SELECT count(*) FROM artifacts", Integer.class));
        assertArrayEquals(originalManifest, Files.readAllBytes(manifest)); assertArrayEquals(originalGrants, Files.readAllBytes(grants));
        assertArrayEquals(originalBundle, Files.readAllBytes(bundle));
    }

    @Test void unansweredGroupingReservationIsAuditedWithoutUsageOrAcceptedIssueEvidence() throws Exception {
        Path directory = Files.createTempDirectory(root, "unknown-case-").toRealPath();
        ProcessBuilder command = new ProcessBuilder("python3", Path.of("scripts/briefing_grouped_fixture.py").toAbsolutePath().toString(), directory.toString(), "--unknown");
        command.environment().put("PYTHONDONTWRITEBYTECODE", "1");
        Process process = command.redirectErrorStream(true).redirectOutput(directory.resolve("fixture.log").toFile()).start();
        int fixtureStatus = process.waitFor();
        assertEquals(0, fixtureStatus, Files.readString(directory.resolve("fixture.log")));
        String schema = "unknown_grouped_" + UUID.randomUUID().toString().replace("-", "");
        String baseUrl = System.getenv("DB_URL"), url = baseUrl + (baseUrl.contains("?") ? "&" : "?") + "currentSchema=" + schema + ",public";
        var datasource = new DriverManagerDataSource(url, username(), password()); var database = new JdbcTemplate(datasource);
        try {
            Flyway.configure().dataSource(datasource).schemas(schema).defaultSchema(schema).load().migrate();
            database.update("INSERT INTO companies(id,name) VALUES ('company-authored','합성 기업')");
            Path source = directory.resolve("sources.jsonl"), output = directory.resolve("output"), archive = output.resolve("grouped-issues.json");
            var settings = new BriefingReplaySettings(source, output.resolve("bundle-v2.json"), Files.createDirectory(directory.resolve("artifacts")),
                    directory.resolve("grants.json"), directory.resolve("manifest.json"), ArtifactFileStore.sha256(Files.readAllBytes(source)),
                    "inbox/authored-grouped-run.md", directory.resolve("clocks.json"));
            var unknownImporter = new BriefingReplayImporter(database, new DataSourceTransactionManager(datasource), settings);
            unknownImporter.importBundle();
            StrictJson.Obj savedArchive = StrictJson.parseObject(Files.readAllBytes(archive));
            StrictJson.Obj receipt = savedArchive.objects("receipts").getFirst(); String digest = receipt.string("requestDigest");
            assertFalse(receipt.bool("usageKnown")); assertTrue(receipt.isNull("inputTokens")); assertTrue(receipt.isNull("outputTokens"));
            assertEquals("unknown", receipt.string("status")); assertTrue(receipt.isNull("responseId"));
            byte[] request = Files.readAllBytes(output.resolve("calls").resolve(digest + ".request.json"));
            byte[] pending = Files.readAllBytes(output.resolve("calls").resolve(digest + ".pending.json"));
            assertEquals(digest, ArtifactFileStore.sha256(request));
            assertEquals(13, database.queryForObject("SELECT count(*) FROM briefing_rounds WHERE published_at IS NOT NULL", Integer.class));
            assertEquals(40, database.queryForObject("SELECT count(*) FROM artifacts WHERE kind='ai_call_receipt'", Integer.class));
            assertEquals(1, database.queryForObject("SELECT count(*) FROM artifacts WHERE kind='ai_submit' AND sha256=?", Integer.class, digest));
            assertEquals(1, database.queryForObject("SELECT count(*) FROM artifacts WHERE kind='briefing_input' AND sha256=?", Integer.class, ArtifactFileStore.sha256(pending)));
            assertEquals(0, database.queryForObject("SELECT count(*) FROM artifacts WHERE id LIKE ?", Integer.class, "%-response-" + digest));
            assertEquals(0, database.queryForObject("SELECT count(*) FROM evidence WHERE article_id='authored-doc-0'", Integer.class));
            String before = database.queryForObject("SELECT md5(string_agg(row_to_json(r)::text, '' ORDER BY id)) FROM briefing_rounds r", String.class);
            assertTrue(unknownImporter.importBundle().alreadyImported());
            assertArrayEquals(request, Files.readAllBytes(output.resolve("calls").resolve(digest + ".request.json")));
            assertArrayEquals(pending, Files.readAllBytes(output.resolve("calls").resolve(digest + ".pending.json")));
            // Changing a reservation's phase must fail even though the original paid request bytes are untouched.
            var mutated = (tools.jackson.databind.node.ObjectNode) StrictJson.parseObject(pending).node().deepCopy();
            mutated.put("stage", "issue_grounding"); Files.write(output.resolve("calls").resolve(digest + ".pending.json"), StrictJson.write(mutated));
            assertThrows(RuntimeException.class, unknownImporter::importBundle);
            assertEquals(before, database.queryForObject("SELECT md5(string_agg(row_to_json(r)::text, '' ORDER BY id)) FROM briefing_rounds r", String.class));
        } finally { database.execute("DROP SCHEMA IF EXISTS " + schema + " CASCADE"); }
    }

    @Test void invalidCompletedSelectionCanStayHeldAndOneBoundCorrectionCanPublish() throws Exception {
        for (String mode : new String[]{"held", "corrected"}) {
            Path directory = Files.createTempDirectory(root, "selection-" + mode + "-").toRealPath();
            ProcessBuilder command = new ProcessBuilder("python3", Path.of("scripts/briefing_grouped_fixture.py").toAbsolutePath().toString(),
                    directory.toString(), "--" + mode + "-selection");
            command.environment().put("PYTHONDONTWRITEBYTECODE", "1");
            Process process = command.redirectErrorStream(true).redirectOutput(directory.resolve("fixture.log").toFile()).start();
            int code = process.waitFor(); assertEquals(0, code, Files.readString(directory.resolve("fixture.log")));
            String schema = "selection_case_" + UUID.randomUUID().toString().replace("-", "");
            String baseUrl = System.getenv("DB_URL"), url = baseUrl + (baseUrl.contains("?") ? "&" : "?") + "currentSchema=" + schema + ",public";
            var datasource = new DriverManagerDataSource(url, username(), password()); var database = new JdbcTemplate(datasource);
            try {
                Flyway.configure().dataSource(datasource).schemas(schema).defaultSchema(schema).load().migrate();
                database.update("INSERT INTO companies(id,name) VALUES ('company-authored','합성 기업')");
                Path source = directory.resolve("sources.jsonl"), output = directory.resolve("output"), bundleFile = output.resolve("bundle-v2.json");
                var settings = new BriefingReplaySettings(source, bundleFile, Files.createDirectory(directory.resolve("artifacts")),
                        directory.resolve("grants.json"), directory.resolve("manifest.json"), ArtifactFileStore.sha256(Files.readAllBytes(source)),
                        "inbox/authored-grouped-run.md", directory.resolve("clocks.json"));
                var caseImporter = new BriefingReplayImporter(database, new DataSourceTransactionManager(datasource), settings);
                caseImporter.importBundle();
                assertEquals("held".equals(mode) ? 13 : 14,
                        database.queryForObject("SELECT count(*) FROM briefing_rounds WHERE published_at IS NOT NULL", Integer.class));
                assertEquals("held".equals(mode) ? 41 : 43,
                        database.queryForObject("SELECT count(*) FROM artifacts WHERE kind='ai_call_receipt'", Integer.class));
                if ("held".equals(mode)) assertEquals(1, database.queryForObject("SELECT count(*) FROM briefing_rounds WHERE status='failed' AND published_payload IS NULL", Integer.class));
                StrictJson.Obj saved = StrictJson.parseObject(Files.readAllBytes(bundleFile)), first = saved.objects("rounds").getFirst();
                String finalDigest = first.string("groupedSelectionRequestDigest");
                StrictJson.Obj request = StrictJson.parseObject(Files.readAllBytes(output.resolve("calls").resolve(finalDigest + ".request.json")));
                StrictJson.Obj input = StrictJson.parseObject(request.string("input"));
                assertTrue(input.has("selectionCorrection")); assertEquals(1, input.object("selectionCorrection").count("attempt"));
                assertTrue(caseImporter.importBundle().alreadyImported());
                String before = database.queryForObject("SELECT md5(string_agg(row_to_json(r)::text, '' ORDER BY id)) FROM briefing_rounds r", String.class);
                // Rebind the changed request's byte digest and receipt honestly: the extra context is still forbidden.
                var changedInput = (tools.jackson.databind.node.ObjectNode) input.node().deepCopy(); changedInput.put("extraUnfrozenContext", "changed");
                var changedRequest = (tools.jackson.databind.node.ObjectNode) request.node().deepCopy(); changedRequest.put("input", com.zoop.common.json.Canonical.write(changedInput));
                byte[] changedBytes = StrictJson.write(changedRequest); String changedDigest = ArtifactFileStore.sha256(changedBytes);
                Files.write(output.resolve("calls").resolve(changedDigest + ".request.json"), changedBytes);
                Files.copy(output.resolve("calls").resolve(finalDigest + ".response.json"), output.resolve("calls").resolve(changedDigest + ".response.json"));
                var changedBundle = (tools.jackson.databind.node.ObjectNode) saved.node().deepCopy();
                var changedRound = (tools.jackson.databind.node.ObjectNode) changedBundle.path("rounds").get(0);
                changedRound.put("groupedSelectionRequestDigest", changedDigest);
                for (tools.jackson.databind.JsonNode value : changedRound.path("receipts")) if (finalDigest.equals(value.path("requestDigest").asText()))
                    ((tools.jackson.databind.node.ObjectNode) value).put("requestDigest", changedDigest);
                for (tools.jackson.databind.JsonNode value : changedBundle.path("receipts")) if (finalDigest.equals(value.path("requestDigest").asText()))
                    ((tools.jackson.databind.node.ObjectNode) value).put("requestDigest", changedDigest);
                Files.write(bundleFile, StrictJson.write(changedBundle));
                RuntimeException rejected = assertThrows(RuntimeException.class, caseImporter::importBundle);
                assertTrue(rejected.getMessage().contains("selection_correction_frozen_inputs"), rejected.getMessage());
                assertEquals(before, database.queryForObject("SELECT md5(string_agg(row_to_json(r)::text, '' ORDER BY id)) FROM briefing_rounds r", String.class));
            } finally { database.execute("DROP SCHEMA IF EXISTS " + schema + " CASCADE"); }
        }
    }

    @Test void aFutureQuarantinedMemberCannotRemoveAnEarlierPublishedIssueAndMalformedProjectionIsRejected() throws Exception {
        Path directory = Files.createTempDirectory(root, "projection-asof-").toRealPath();
        String authored = """
                import importlib.util, sys
                from pathlib import Path
                path = Path('..').resolve() / 'scripts/tests/test_briefing_grouped_run.py'
                spec = importlib.util.spec_from_file_location('projection_fixture_case', path)
                m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
                f = m.GroupedRunTest(); f.setUp()
                try:
                    directory = Path(sys.argv[1]).resolve(); m.base.private_dir(directory)
                    f.root = directory; f.archive_path = directory / 'archive.json'; f.output = directory / 'output'
                    f.clock.root = directory; f.clock.sources = directory / 'sources.jsonl'
                    f.clock.clocks = directory / 'clocks.json'; f.clock.html = directory / 'html'; f.clock.html.mkdir()
                    archive = f.prepare()
                    archive['identity'] = {'companyProjectionVersion':'canonical-evidence-v1'}
                    for issue in archive['issues']:
                        for mention in issue['mentions']:
                            audit = []
                            for company in mention['companies']:
                                raw = {'company_id':company['companyId'], 'name':company['name'], 'role':company['role']}
                                audit.append({'suppliedCompanyId':raw['company_id'], 'suppliedName':raw['name'],
                                    'suppliedRole':raw['role'], 'canonicalName':raw['name'], 'rawParticipant':raw,
                                    'matchedEvidenceIds':[e['evidenceId'] for e in company['evidence']], 'status':'linked_name_match'})
                            mention['companyProjection'] = {'policy':'canonical-evidence-v1', 'version':'canonical-evidence-v1',
                                'briefingEligible':True, 'status':'eligible', 'audit':audit}
                    future = archive['issues'].pop(1)['mentions'][0]
                    future['companies'] = []
                    raw = {'company_id':'UNKNOWN:BAD', 'name':'합성 기업', 'role':'contract party'}
                    future['companyProjection'] = {'policy':'canonical-evidence-v1', 'version':'canonical-evidence-v1',
                        'briefingEligible':False, 'status':'quarantined', 'audit':[{'suppliedCompanyId':raw['company_id'],
                        'suppliedName':raw['name'], 'suppliedRole':raw['role'], 'canonicalName':None,
                        'rawParticipant':raw, 'matchedEvidenceIds':[], 'status':'excluded_unknown_company_id'}]}
                    archive['issues'][0]['mentions'].append(future)
                    f.archive_path.write_bytes(m.base.canonical(archive))
                    result = f.execute(m.fixtures.AuthoredTransport())
                    assert result['selectedRounds'] == 13, result
                finally:
                    f.tearDown()
                """;
        ProcessBuilder command = new ProcessBuilder("python3", "-c", authored, directory.toString());
        command.environment().put("PYTHONDONTWRITEBYTECODE", "1");
        Process process = command.redirectErrorStream(true).redirectOutput(directory.resolve("fixture.log").toFile()).start();
        int code = process.waitFor(); assertEquals(0, code, Files.readString(directory.resolve("fixture.log")));
        String schema = "projection_case_" + UUID.randomUUID().toString().replace("-", "");
        String baseUrl = System.getenv("DB_URL"), url = baseUrl + (baseUrl.contains("?") ? "&" : "?") + "currentSchema=" + schema + ",public";
        var datasource = new DriverManagerDataSource(url, username(), password()); var database = new JdbcTemplate(datasource);
        try {
            Flyway.configure().dataSource(datasource).schemas(schema).defaultSchema(schema).load().migrate();
            database.update("INSERT INTO companies(id,name) VALUES ('company-authored','합성 기업')");
            Path source = directory.resolve("sources.jsonl"), output = directory.resolve("output"), bundleFile = output.resolve("bundle-v2.json"), archiveFile = output.resolve("grouped-issues.json");
            var settings = new BriefingReplaySettings(source, bundleFile, Files.createDirectory(directory.resolve("artifacts")),
                    directory.resolve("grants.json"), directory.resolve("manifest.json"), ArtifactFileStore.sha256(Files.readAllBytes(source)),
                    "inbox/authored-grouped-run.md", directory.resolve("clocks.json"));
            var projectedImporter = new BriefingReplayImporter(database, new DataSourceTransactionManager(datasource), settings);
            projectedImporter.importBundle();
            assertEquals(13, database.queryForObject("SELECT count(*) FROM briefing_rounds WHERE published_at IS NOT NULL", Integer.class));
            assertEquals(1, database.queryForObject("SELECT count(*) FROM briefing_rounds WHERE round_date='2026-10-02' AND edition='morning' AND published_payload->'items'->0->>'eventId'='stable-authored-issue-0'", Integer.class));
            assertEquals(1, database.queryForObject("SELECT count(*) FROM briefing_rounds WHERE round_date='2026-10-02' AND edition='evening' AND published_payload IS NULL", Integer.class));
            assertEquals(39, database.queryForObject("SELECT count(*) FROM artifacts WHERE kind='ai_call_receipt'", Integer.class));
            assertTrue(projectedImporter.importBundle().alreadyImported());
            byte[] originalArchive = Files.readAllBytes(archiveFile), originalBundle = Files.readAllBytes(bundleFile);
            String before = database.queryForObject("SELECT md5(string_agg(row_to_json(r)::text, '' ORDER BY id)) FROM briefing_rounds r", String.class);
            for (String mutation : new String[]{"missing_policy", "false_claimed_eligible"}) {
                var changedArchive = (tools.jackson.databind.node.ObjectNode) StrictJson.parseObject(originalArchive).node().deepCopy();
                var projection = (tools.jackson.databind.node.ObjectNode) changedArchive.path("issues").get(0).path("mentions").get(1).path("companyProjection");
                if ("missing_policy".equals(mutation)) projection.remove("policy"); else projection.put("briefingEligible", true);
                byte[] changedBytes = StrictJson.write(changedArchive); Files.write(archiveFile, changedBytes);
                var changedBundle = (tools.jackson.databind.node.ObjectNode) StrictJson.parseObject(originalBundle).node().deepCopy();
                changedBundle.put("groupArchiveSha256", ArtifactFileStore.sha256(changedBytes)); Files.write(bundleFile, StrictJson.write(changedBundle));
                assertThrows(RuntimeException.class, projectedImporter::importBundle);
                assertEquals(before, database.queryForObject("SELECT md5(string_agg(row_to_json(r)::text, '' ORDER BY id)) FROM briefing_rounds r", String.class));
            }
        } finally { database.execute("DROP SCHEMA IF EXISTS " + schema + " CASCADE"); }
    }

    private static String url() { String base = System.getenv("DB_URL"); return base + (base.contains("?") ? "&" : "?") + "currentSchema=" + SCHEMA + ",public"; }
    private static String username() { return System.getenv().getOrDefault("DB_USERNAME", "company_test"); }
    private static String password() { return System.getenv().getOrDefault("DB_PASSWORD", ""); }
}
