package com.zoop.briefing.replay;

import com.zoop.ZoopApplication;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.util.LinkedHashMap;
import java.util.Map;
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
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;
import static org.junit.jupiter.api.Assertions.*;

/** Authored provider files through the actual recovery importer, local PostgreSQL and HTTP reader. */
@Tag("briefing-replay-postgres")
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*briefing_replay.*")
class BriefingGroupedRecoveryPostgresTest {
    private static final String SCHEMA = "recovery_replay_" + UUID.randomUUID().toString().replace("-", "");
    private static Path root, bundle, manifest, grants;
    private static JdbcTemplate jdbc;
    private static BriefingReplayImporter importer;
    private static ConfigurableApplicationContext server;
    private static int port;

    @BeforeAll static void prepare() throws Exception {
        root = Files.createTempDirectory("zoop-authored-item-recovery-").toRealPath();
        ProcessBuilder command = new ProcessBuilder("python3", Path.of("scripts/briefing_recovery_fixture.py").toAbsolutePath().toString(), root.toString());
        command.environment().put("PYTHONDONTWRITEBYTECODE", "1");
        Process process = command.redirectErrorStream(true).redirectOutput(root.resolve("fixture.log").toFile()).start();
        assertEquals(0, process.waitFor(), () -> "Authored recovery fixture failed: " + root.resolve("fixture.log"));
        bundle = root.resolve("output/bundle-v2.json"); manifest = root.resolve("manifest.json"); grants = root.resolve("grants.json");
        String baseUrl = System.getenv("DB_URL");
        String url = baseUrl + (baseUrl.contains("?") ? "&" : "?") + "currentSchema=" + SCHEMA + ",public";
        var datasource = new DriverManagerDataSource(url, username(), password()); jdbc = new JdbcTemplate(datasource);
        jdbc.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public");
        jdbc.execute("CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public");
        Flyway.configure().dataSource(datasource).schemas(SCHEMA).defaultSchema(SCHEMA).load().migrate();
        jdbc.update("INSERT INTO companies(id,name) VALUES ('company-authored','합성 기업')");
        Path artifacts = Files.createDirectory(root.resolve("artifacts"));
        importer = new BriefingReplayImporter(jdbc, new DataSourceTransactionManager(datasource),
                new BriefingReplaySettings(root.resolve("sources.jsonl"), bundle, artifacts, grants, manifest,
                        ArtifactFileStore.sha256(Files.readAllBytes(root.resolve("sources.jsonl"))),
                        "inbox/authored-recovery.md", root.resolve("clocks.json")));
        importer.importBundle();
        server = new SpringApplicationBuilder(ZoopApplication.class).web(WebApplicationType.SERVLET).profiles("local")
                .run("--server.port=0", "--server.address=127.0.0.1", "--spring.datasource.url=" + url,
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

    @Test void aFailedPeerDoesNotDiscardTwoSupportedItemsAndTheEffectiveRanksReachHttp() throws Exception {
        assertEquals(13, jdbc.queryForObject("SELECT count(*) FROM briefing_rounds WHERE published_at IS NOT NULL", Integer.class));
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM briefing_rounds WHERE status='failed' AND published_payload IS NULL", Integer.class));
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM evidence WHERE article_id='recovery-doc-1'", Integer.class));
        var http = HttpClient.newHttpClient(); int total = 0;
        for (int index = 0; index < 14; index++) {
            String date = LocalDate.of(2026, 10, 2).plusDays(index / 2).toString(), edition = index % 2 == 0 ? "morning" : "evening";
            var response = http.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/api/v1/briefings?date=" + date + "&edition=" + edition)).GET().build(), HttpResponse.BodyHandlers.ofString());
            assertEquals(200, response.statusCode(), response.body()); StrictJson.Obj payload = StrictJson.parseObject(response.body());
            assertEquals(index == 1 ? "failed" : "published", payload.string("status")); total += payload.array("items").size();
            if (index == 0) {
                assertEquals(2, payload.array("items").size());
                assertEquals("recovery-issue-2", payload.objects("items").get(0).string("eventId"));
                assertEquals("recovery-issue-0", payload.objects("items").get(1).string("eventId"));
                assertEquals(1, payload.objects("items").get(0).count("rank")); assertEquals(2, payload.objects("items").get(1).count("rank"));
                assertEquals(1, payload.objects("items").get(1).object("summary").string("text").lines().count());
                assertEquals(2, payload.object("references").array("eventIds").size());
                assertTrue(payload.object("metadata").objects("failures").stream().anyMatch(f -> "ITEMS_WITHHELD".equals(f.string("code"))));
            }
        }
        assertEquals(14, total);
        Map<String, String> before = fingerprints(); byte[] bundleBytes = Files.readAllBytes(bundle);
        byte[] baseBytes = Files.readAllBytes(root.resolve("output/base-bundle-v2.json"));
        byte[] originalBytes = Files.readAllBytes(root.resolve("base/bundle-v2.json"));
        assertArrayEquals(originalBytes, baseBytes);
        assertTrue(importer.importBundle().alreadyImported()); assertEquals(before, fingerprints());
        assertArrayEquals(bundleBytes, Files.readAllBytes(bundle)); assertArrayEquals(baseBytes, Files.readAllBytes(root.resolve("output/base-bundle-v2.json")));
    }

    @Test void anHonestReceiptForChecksOfOldTextCannotAuthorizeTheCurrentDraft() throws Exception {
        byte[] originalBundle = Files.readAllBytes(bundle); ObjectNode changed = (ObjectNode) StrictJson.parseObject(originalBundle).node().deepCopy();
        StrictJson.Obj layer = StrictJson.Obj.of(changed).object("briefingRecovery"), round = layer.objects("rounds").getFirst();
        StrictJson.Obj issue = round.objects("issues").getFirst(); String digest = issue.string("verificationRequestDigest");
        Path responsePath = root.resolve("output/calls/" + digest + ".response.json"); byte[] originalResponse = Files.readAllBytes(responsePath);
        Map<String, String> before = fingerprints();
        try {
            ObjectNode response = (ObjectNode) StrictJson.parseObject(originalResponse).node().deepCopy();
            ObjectNode content = (ObjectNode) response.path("output").get(0).path("content").get(0);
            ObjectNode answer = (ObjectNode) StrictJson.parseObject(content.path("text").stringValue()).node().deepCopy();
            String target = issue.string("issueId") + ":claim:0";
            ((ObjectNode) answer.path("checks").path(target)).put("checkedText", "다른 실행에서 생성한 과거 문장입니다.");
            content.put("text", Canonical.write(answer)); byte[] raw = StrictJson.write(response); Files.write(responsePath, raw);
            for (JsonNode value : layer.array("receipts")) if (digest.equals(value.path("requestDigest").stringValue()))
                ((ObjectNode) value).put("responseSha256", Canonical.sha256(raw));
            for (JsonNode value : issue.object("verification").array("checks")) if (target.equals(value.path("targetId").stringValue()))
                ((ObjectNode) value).put("checkedText", "다른 실행에서 생성한 과거 문장입니다.");
            Files.write(bundle, StrictJson.write(changed));
            RuntimeException failure = assertThrows(RuntimeException.class, importer::importBundle);
            assertTrue(failure.getMessage().contains("verification_exact_result"), failure.getMessage());
            assertEquals(before, fingerprints());
        } finally { Files.write(bundle, originalBundle); Files.write(responsePath, originalResponse); }
    }

    @Test void changingTheOriginalBundleOrItsByteEncodingIsRejectedBeforeAnyWrite() throws Exception {
        Map<String, String> before = fingerprints(); Path base = root.resolve("output/base-bundle-v2.json"); byte[] bytes = Files.readAllBytes(base);
        try {
            Files.write(base, (new String(bytes, java.nio.charset.StandardCharsets.UTF_8) + "\n").getBytes(java.nio.charset.StandardCharsets.UTF_8));
            RuntimeException failure = assertThrows(RuntimeException.class, importer::importBundle);
            assertTrue(failure.getMessage().contains("base_bytes_digest")); assertEquals(before, fingerprints());
        } finally { Files.write(base, bytes); }
        byte[] saved = Files.readAllBytes(bundle);
        try {
            ObjectNode changed = (ObjectNode) StrictJson.parseObject(saved).node().deepCopy();
            ((ObjectNode) changed.path("rounds").get(0)).put("roundId", "modified-original-round"); Files.write(bundle, StrictJson.write(changed));
            RuntimeException failure = assertThrows(RuntimeException.class, importer::importBundle);
            assertTrue(failure.getMessage().contains("base_json_unchanged")); assertEquals(before, fingerprints());
        } finally { Files.write(bundle, saved); }
    }

    @Test void anEditorialHoldCanOnlyRemoveItsRegisteredIssueAndTheOriginalFileIsPreserved() throws Exception {
        Path directory = Files.createTempDirectory(root, "editorial-").toRealPath();
        ProcessBuilder command = new ProcessBuilder("python3", Path.of("scripts/briefing_recovery_fixture.py").toAbsolutePath().toString(), directory.toString(), "--editorial");
        command.environment().put("PYTHONDONTWRITEBYTECODE", "1");
        Process process = command.redirectErrorStream(true).redirectOutput(directory.resolve("fixture.log").toFile()).start();
        assertEquals(0, process.waitFor(), () -> "Editorial fixture failed: " + directory.resolve("fixture.log"));
        String schema = "editorial_replay_" + UUID.randomUUID().toString().replace("-", "");
        String baseUrl = System.getenv("DB_URL"), url = baseUrl + (baseUrl.contains("?") ? "&" : "?") + "currentSchema=" + schema + ",public";
        var datasource = new DriverManagerDataSource(url, username(), password()); var database = new JdbcTemplate(datasource);
        try {
            Flyway.configure().dataSource(datasource).schemas(schema).defaultSchema(schema).load().migrate();
            database.update("INSERT INTO companies(id,name) VALUES ('company-authored','합성 기업')");
            Path source = directory.resolve("sources.jsonl"), file = directory.resolve("output/bundle-v2.json");
            var settings = new BriefingReplaySettings(source, file, Files.createDirectory(directory.resolve("artifacts")), directory.resolve("grants.json"),
                    directory.resolve("manifest.json"), ArtifactFileStore.sha256(Files.readAllBytes(source)), "inbox/authored-recovery.md", directory.resolve("clocks.json"));
            var subject = new BriefingReplayImporter(database, new DataSourceTransactionManager(datasource), settings); subject.importBundle();
            assertEquals(12, database.queryForObject("SELECT count(*) FROM briefing_rounds WHERE published_at IS NOT NULL", Integer.class));
            byte[] review = Files.readAllBytes(directory.resolve("output/editorial-review-holds.json"));
            assertEquals(1, database.queryForObject("SELECT count(*) FROM artifacts WHERE id LIKE '%-editorial-review' AND kind='verification_receipt' AND sha256=?",
                    Integer.class, Canonical.sha256(review)));
            String before = database.queryForObject("SELECT md5(jsonb_agg(to_jsonb(r) ORDER BY id)::text) FROM briefing_rounds r", String.class);
            assertTrue(subject.importBundle().alreadyImported());
            ObjectNode changed = (ObjectNode) StrictJson.parseObject(Files.readAllBytes(file)).node().deepCopy();
            ObjectNode mutatedReview = (ObjectNode) StrictJson.parseObject(review).node().deepCopy();
            ((ObjectNode) mutatedReview.path("holds").get(0)).put("issueId", "unregistered-issue"); byte[] mutated = StrictJson.write(mutatedReview);
            Files.write(directory.resolve("output/editorial-review-holds.json"), mutated);
            ObjectNode layerReview = (ObjectNode) changed.path("briefingRecovery").path("editorialReview");
            layerReview.put("sha256", Canonical.sha256(mutated)); layerReview.set("holds", mutatedReview.path("holds").deepCopy()); Files.write(file, StrictJson.write(changed));
            RuntimeException failure = assertThrows(RuntimeException.class, subject::importBundle);
            assertTrue(failure.getMessage().contains("editorial_hold"), failure.getMessage());
            assertEquals(before, database.queryForObject("SELECT md5(jsonb_agg(to_jsonb(r) ORDER BY id)::text) FROM briefing_rounds r", String.class));
        } finally { database.execute("DROP SCHEMA IF EXISTS " + schema + " CASCADE"); }
    }

    private static Map<String, String> fingerprints() throws Exception {
        Map<String, String> result = new LinkedHashMap<>();
        for (String table : new String[]{"articles", "article_versions", "evidence", "artifacts", "briefing_rounds"})
            result.put(table, jdbc.queryForObject("SELECT md5(COALESCE(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]'::jsonb)::text) FROM " + table + " t", String.class));
        result.put("grants", ArtifactFileStore.sha256(Files.readAllBytes(grants))); result.put("manifest", ArtifactFileStore.sha256(Files.readAllBytes(manifest))); return result;
    }
    private static String username() { return System.getenv().getOrDefault("DB_USERNAME", "company_test"); }
    private static String password() { return System.getenv().getOrDefault("DB_PASSWORD", ""); }
}
