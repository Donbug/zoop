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

    private static String url() { String base = System.getenv("DB_URL"); return base + (base.contains("?") ? "&" : "?") + "currentSchema=" + SCHEMA + ",public"; }
    private static String username() { return System.getenv().getOrDefault("DB_USERNAME", "company_test"); }
    private static String password() { return System.getenv().getOrDefault("DB_PASSWORD", ""); }
}
