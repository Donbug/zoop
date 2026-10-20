package com.zoop.briefing.replay;

import com.zoop.ZoopApplication;
import com.zoop.artifact.storage.ArtifactFileStore;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.UUID;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
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
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

import static org.junit.jupiter.api.Assertions.*;

/** Actual DB/importer/HTTP; all upstream source, calendar and model responses are explicitly authored. */
@Tag("briefing-replay-postgres")
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*briefing_replay.*")
class BriefingMarketContextPostgresTest {
    private static final String SCHEMA = "market_context_" + UUID.randomUUID().toString().replace("-", "");
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static Path root, bundle, artifacts, grants, manifest;
    private static byte[] original;
    private static JdbcTemplate jdbc;
    private static BriefingReplayImporter importer;
    private static ConfigurableApplicationContext server;
    private static int port;

    @BeforeAll static void prepare() throws Exception {
        root = Files.createTempDirectory("zoop-authored-market-context-").toRealPath();
        var script = Path.of("scripts/briefing_market_context_fixture.py").toAbsolutePath();
        var process = new ProcessBuilder("python3", script.toString(), root.toString())
                .redirectErrorStream(true).redirectOutput(root.resolve("fixture.log").toFile()).start();
        assertEquals(0, process.waitFor(), () -> "Authored fixture failed; inspect " + root.resolve("fixture.log"));
        bundle = root.resolve("enriched/bundle-v2.json"); original = Files.readAllBytes(bundle);
        artifacts = Files.createDirectory(root.resolve("artifacts")); grants = root.resolve("grants.json"); manifest = root.resolve("manifest.json");
        var dataSource = new DriverManagerDataSource(url(), username(), password());
        jdbc = new JdbcTemplate(dataSource);
        Flyway.configure().dataSource(dataSource).schemas(SCHEMA).defaultSchema(SCHEMA).load().migrate();
        jdbc.update("INSERT INTO companies(id,name) VALUES ('authored-context-company','시험 기업')");
        importer = new BriefingReplayImporter(jdbc, new DataSourceTransactionManager(dataSource),
                new BriefingReplaySettings(root.resolve("sources.jsonl"), bundle, artifacts, grants, manifest,
                        ArtifactFileStore.sha256(Files.readAllBytes(root.resolve("sources.jsonl"))),
                        "inbox/authored-market-context.md", root.resolve("clocks.json")));
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

    @BeforeEach void restoreOwnedInputs() throws Exception {
        Files.write(bundle, original);
        jdbc.update("UPDATE articles SET access_status='available' WHERE id='z-unselected-industry'");
    }

    @AfterAll static void cleanup() throws Exception {
        if (server != null) server.close();
        if (jdbc != null) jdbc.execute("DROP SCHEMA IF EXISTS " + SCHEMA + " CASCADE");
        if (root != null) try (var files = Files.walk(root)) {
            for (Path p : files.sorted(java.util.Comparator.reverseOrder()).toList()) Files.deleteIfExists(p);
        }
    }

    @Test void broadUnselectedEvidenceAndPriorSummarySurviveActualDbHttpRestoration() throws Exception {
        var response = get("2026-10-02", "evening");
        assertEquals(200, response.statusCode(), response.body());
        JsonNode payload = JSON.readTree(response.body());
        assertEquals("published", payload.path("status").asText());
        assertTrue(payload.at("/marketSummary/text").asText().contains("시험 기업"));
        assertTrue(payload.at("/marketSummary/evidenceIds/0").asText().startsWith("market-evidence-"));
        assertEquals(15, jdbc.queryForObject("SELECT count(*) FROM articles", Integer.class));
        assertTrue(jdbc.queryForObject("SELECT count(*) FROM evidence WHERE id LIKE 'market-evidence-%'", Integer.class) >= 4);
        JsonNode saved = snapshot("2026-10-03", "morning");
        assertEquals("available", saved.at("/marketEnrichment/marketContext/previousPublication/status").asText());
        assertEquals("2026-10-02", saved.at("/marketEnrichment/marketContext/previousPublication/date").asText());
        assertEquals("evening", saved.at("/marketEnrichment/marketContext/previousPublication/edition").asText());
        assertFalse(saved.at("/marketEnrichment/forecasts").isEmpty());
        assertEquals("unavailable", saved.at("/marketEnrichment/forecastEvaluations/0/status").asText());
        assertEquals("condition_outcomes_not_observed", saved.at("/marketEnrichment/forecastEvaluations/0/reason").asText());
    }

    @Test void identicalReimportPreservesPublishedSnapshotsAndManifest() throws Exception {
        String before = originals(); byte[] savedManifest = Files.readAllBytes(manifest);
        int count = jdbc.queryForObject("SELECT count(*) FROM artifacts", Integer.class);
        importer.importBundle();
        assertEquals(before, originals());
        assertArrayEquals(savedManifest, Files.readAllBytes(manifest));
        assertEquals(count, jdbc.queryForObject("SELECT count(*) FROM artifacts", Integer.class));
    }

    @Test void contextQuoteTamperIsRejectedAndCannotOverwritePublication() throws Exception {
        String before = originals();
        var changed = (ObjectNode) JSON.readTree(original);
        ((ObjectNode) changed.at("/marketEnrichment/rounds/0/marketContext/documents/0/sources/0")).put("quote", "fabricated source");
        Files.writeString(bundle, JSON.writeValueAsString(changed));
        assertThrows(RuntimeException.class, () -> importer.importBundle());
        assertEquals(before, originals());
    }

    @Test void revokingUnselectedContextDocumentBlocksReadWithoutChangingOriginal() throws Exception {
        String before = originals();
        jdbc.update("UPDATE articles SET access_status='private' WHERE id='z-unselected-industry'");
        assertEquals(503, get("2026-10-02", "evening").statusCode());
        assertEquals(before, originals());
        jdbc.update("UPDATE articles SET access_status='available' WHERE id='z-unselected-industry'");
        assertEquals(200, get("2026-10-02", "evening").statusCode());
    }

    private static JsonNode snapshot(String date, String edition) throws Exception {
        return JSON.readTree(jdbc.queryForObject("SELECT public_snapshot::text FROM briefing_rounds WHERE round_date=?::date AND edition=?",
                String.class, date, edition));
    }
    private static String originals() {
        return jdbc.queryForObject("SELECT json_agg(row_to_json(t) ORDER BY id)::text FROM (SELECT id,published_payload,public_snapshot,comparison_snapshot FROM briefing_rounds) t", String.class);
    }
    private static HttpResponse<String> get(String date, String edition) throws Exception {
        return HttpClient.newHttpClient().send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port
                + "/api/v1/briefings?date=" + date + "&edition=" + edition)).GET().build(), HttpResponse.BodyHandlers.ofString());
    }
    private static String url() {
        String value = System.getenv("DB_URL"); return value + (value.contains("?") ? "&" : "?") + "currentSchema=" + SCHEMA + ",public";
    }
    private static String username() { return System.getenv().getOrDefault("DB_USERNAME", "company_test"); }
    private static String password() { return System.getenv().getOrDefault("DB_PASSWORD", ""); }
}
