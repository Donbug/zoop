package com.zoop.briefing.integration;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.sql.DriverManager;
import java.util.UUID;
import java.util.function.Consumer;

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

import static org.junit.jupiter.api.Assertions.*;

/** Isolated PostgreSQL -> actual HTTP -> fixed detail and CURRENT grant checks. No external source/model calls. */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test", "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "ZOOP_AUTH_ALLOWED_ORIGINS=https://zoop.example", "springdoc.api-docs.enabled=true"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("briefing-postgres")
@DirtiesContext(classMode = DirtiesContext.ClassMode.AFTER_CLASS)
class BriefingItemDetailHttpPostgresTest {
    private static final String SCHEMA = "briefing_detail_" + UUID.randomUUID().toString().replace("-", "");
    private static final Path GRANTS = grants();
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final String ROUND = "brf-test-2026-10-15-morning";
    private static final String DETAIL = "/api/v1/briefings/" + ROUND + "/items/brf-test-event";
    private static final String BODY = "앞😀합성" + " 원문주변문맥".repeat(180);
    private static final String BODY_HASH = hash(BODY);
    @Autowired JdbcTemplate jdbc;
    @LocalServerPort int port;
    private final HttpClient http = HttpClient.newHttpClient();

    @DynamicPropertySource static void isolate(DynamicPropertyRegistry properties) {
        properties.add("spring.datasource.url", () -> System.getenv("DB_URL") +
                (System.getenv("DB_URL").contains("?") ? "&" : "?") + "currentSchema=" + SCHEMA + ",public");
        properties.add("spring.flyway.schemas", () -> SCHEMA);
        properties.add("spring.flyway.default-schema", () -> SCHEMA);
        properties.add("spring.jpa.properties.hibernate.default_schema", () -> SCHEMA);
        properties.add("zoop.document-read.grants", () -> GRANTS.toString());
    }

    @BeforeEach void fixture() throws Exception { load(ignored -> { }); }

    private void load(Consumer<ObjectNode> change) throws Exception { load(change, true); }

    private void load(Consumer<ObjectNode> change, boolean withDetails) throws Exception { load(change, withDetails, false); }

    private void load(Consumer<ObjectNode> change, boolean withDetails, boolean withPrevious) throws Exception {
        Files.writeString(GRANTS, resource("grants.json"));
        jdbc.execute("TRUNCATE TABLE briefing_changes, briefing_rounds RESTART IDENTITY CASCADE");
        jdbc.update("DELETE FROM evidence WHERE id LIKE 'brf-test-%'");
        jdbc.update("UPDATE articles SET current_version=NULL WHERE id LIKE 'brf-test-%'");
        jdbc.update("DELETE FROM article_versions WHERE article_id LIKE 'brf-test-%'");
        jdbc.update("DELETE FROM articles WHERE id LIKE 'brf-test-%'");
        jdbc.update("DELETE FROM artifacts WHERE id LIKE 'brf-test-%'");
        jdbc.update("DELETE FROM companies WHERE id LIKE 'brf-test-%'");
        String sql = resource("fixture.sql");
        int start = sql.indexOf("$records$") + "$records$".length(), end = sql.indexOf("$records$", start);
        JsonNode entries = JSON.readTree(sql.substring(start, end));
        for (JsonNode entry : entries) {
            JsonNode payload = entry.path("p");
            if (withPrevious && "brf-test-2026-10-14-morning".equals(payload.path("id").asString())) {
                // Recovery receipt wall clocks can be later even when historical data cutoffs are earlier.
                ((ObjectNode) entry).put("published", "2026-10-19T00:23:00Z");
                ((ObjectNode) payload.path("references")).putArray("evidenceIds").add("brf-test-evidence-previous");
                ((ObjectNode) entry.at("/snapshot/marketSummary")).putArray("evidenceIds").add("brf-test-evidence-previous");
                ((ObjectNode) entry.at("/snapshot/sourceBindings/0")).put("documentId", "brf-test-document-previous");
            }
            if (withPrevious && ROUND.equals(payload.path("id").asString())) {
                ObjectNode previous = ((ObjectNode) entry.path("snapshot")).putObject("previousComparison")
                        .put("status", "available").put("previousRoundId", "brf-test-2026-10-14-morning")
                        .put("previousPublishedAt", "2026-10-19T00:23:00Z").put("previousDataAsOf", "2026-10-14T00:20:00Z")
                        .put("comparisonBasis", "event_identity");
                previous.putObject("forecastEvaluation").put("status", "unavailable").put("reason", "전망 평가를 하지 않는 합성시험");
                ObjectNode compared = previous.putArray("items").addObject();
                JsonNode original = payload.path("items").get(0);
                for (String field : java.util.List.of("title", "eventId", "eventTime", "timePrecision", "reportedAt", "rank", "evidenceCount"))
                    compared.set(field, original.path(field).deepCopy());
                compared.putArray("companyNames").add("[합성시험] 시험기업");
                compared.put("change", "new").putNull("previousRank").putNull("previousEvidenceCount");
            }
            if (payload.path("items").isEmpty()) continue;
            JsonNode item = payload.path("items").get(0);
            ObjectNode detail = JSON.createObjectNode().put("roundId", payload.path("id").asString())
                    .put("eventId", item.path("eventId").asString()).put("title", item.path("title").asString())
                    .put("selectionReason", item.path("reason").asString());
            detail.set("summary", item.path("summary").deepCopy());
            detail.set("companies", item.path("companies").deepCopy());
            detail.set("metadata", payload.path("metadata").deepCopy());
            detail.putArray("claims").addObject().put("text", item.path("summary").path("text").asString())
                    .put("type", "fact").putArray("evidenceIds").add("brf-test-evidence");
            ObjectNode evidence = detail.putArray("evidence").addObject().put("id", "brf-test-evidence")
                    .put("quote", "😀합성").put("documentId", "brf-test-document").put("documentVersion", "synthetic-v1")
                    .put("title", "[합성시험] 직접 작성한 시험 원문").put("publisher", "[합성시험] 작성자")
                    .put("url", "https://example.invalid/synthetic-document").put("publishedAt", "2026-10-13T00:00:00Z")
                    .put("quoteVerified", true).put("sourceKind", "news").put("bodySha256", BODY_HASH);
            evidence.putObject("bodyContext").put("text", BODY).put("start", 0)
                    .put("end", BODY.codePointCount(0, BODY.length())).put("quoteStart", 1).put("quoteEnd", 4)
                    .put("offsetUnit", "unicode_code_point");
            detail.putArray("limitations").add("[합성시험] 실제 기사나 시장 판단이 아닙니다.");
            change.accept(detail);
            if (withDetails) ((ObjectNode) entry.path("snapshot")).putObject("itemDetails").set("brf-test-event", detail);
        }
        sql = sql.substring(0, start) + JSON.writeValueAsString(entries) + sql.substring(end);
        if (withPrevious) sql = sql.replace("DO $synthetic$", """
                INSERT INTO articles(id,kind,provider,access_status,created_at)
                    SELECT id||'-previous',kind,provider,access_status,created_at FROM articles WHERE id='brf-test-document';
                INSERT INTO article_versions(article_id,version,title,publisher,url,published_at,publication_precision,text_artifact_id,collected_at)
                    SELECT article_id||'-previous',version,title,publisher,url,published_at,publication_precision,text_artifact_id,collected_at
                    FROM article_versions WHERE article_id='brf-test-document';
                INSERT INTO evidence(id,article_id,article_version,text_artifact_id,quote,start_offset,end_offset,offset_unit,input_kind,raw_locator_ids,quote_verified,verification_artifact_id,verified_at,created_at)
                    SELECT id||'-previous',article_id||'-previous',article_version,text_artifact_id,quote,start_offset,end_offset,offset_unit,input_kind,raw_locator_ids,quote_verified,verification_artifact_id,verified_at,created_at
                    FROM evidence WHERE id='brf-test-evidence';
                DO $synthetic$
                """);
        sql = sql.replace("'합성시험',0,4", "'😀합성',1,4").replace("repeat('a',64),10", "'" + BODY_HASH + "'," + BODY.getBytes(StandardCharsets.UTF_8).length);
        jdbc.execute(sql);
    }

    @AfterAll static void cleanup() throws Exception {
        try (var connection = DriverManager.getConnection(System.getenv("DB_URL"),
                System.getenv().getOrDefault("DB_USERNAME", "company_test"), System.getenv().getOrDefault("DB_PASSWORD", ""));
                var statement = connection.createStatement()) { statement.execute("DROP SCHEMA IF EXISTS " + SCHEMA + " CASCADE"); }
        Files.deleteIfExists(GRANTS);
    }

    @Test void fixedItemRestoresClaimsExactQuoteVersionAndUnicodeContextWithoutMutation() throws Exception {
        String before = jdbc.queryForObject("SELECT public_snapshot::text FROM briefing_rounds WHERE id=?", String.class, ROUND);
        var reply = get(DETAIL);
        assertEquals(200, reply.status(), reply.body());
        assertEquals(ROUND, reply.json().path("roundId").asString());
        assertEquals("fact", reply.json().at("/claims/0/type").asString());
        assertEquals("😀합성", reply.json().at("/evidence/0/quote").asString());
        assertEquals(BODY, reply.json().at("/evidence/0/bodyContext/text").asString());
        assertEquals(4, reply.json().at("/evidence/0/bodyContext/quoteEnd").intValue());
        assertEquals(BODY_HASH, reply.json().at("/evidence/0/bodySha256").asString());
        assertEquals("detail-http-request", reply.json().at("/metadata/requestId").asString());
        assertFalse(reply.body().contains("sourceBindings"));
        assertEquals(before, jdbc.queryForObject("SELECT public_snapshot::text FROM briefing_rounds WHERE id=?", String.class, ROUND));
    }

    @Test void roundMembershipAndMissingDetailNeverFallBackToAnotherRoundOrLatestDocument() throws Exception {
        for (String path : new String[] {DETAIL.replace(ROUND, "no-such-round"), DETAIL.replace("brf-test-event", "another-event"),
                DETAIL.replace(ROUND, "brf-test-2026-10-14-morning")}) assertEquals(404, get(path).status(), path);
        load(ignored -> { }, false);
        assertEquals(404, get(DETAIL).status());
        assertEquals(200, get("/api/v1/briefings?date=2026-10-15&edition=morning").status());
        // A legitimately missing source body context is explicit rather than reconstructed content.
        load(detail -> ((ObjectNode) detail.path("evidence").get(0)).putNull("bodyContext"));
        assertEquals(200, get(DETAIL).status());
        assertTrue(get(DETAIL).json().at("/evidence/0/bodyContext").isNull());
    }

    @Test void currentGrantRevocationAndPrivateDocumentBlockDetailImmediately() throws Exception {
        Files.writeString(GRANTS, resource("grants.json").replace("\"enabled\": true", "\"enabled\": false"));
        unavailable(DETAIL);
        Files.writeString(GRANTS, resource("grants.json"));
        jdbc.update("UPDATE articles SET access_status='private' WHERE id='brf-test-document'");
        unavailable(DETAIL);
        jdbc.update("UPDATE articles SET access_status='available' WHERE id='brf-test-document'");
        assertEquals(200, get(DETAIL).status());
    }

    @Test void suspendedAndUnpublishedRoundsDoNotExposeStoredDetail() throws Exception {
        unavailable(DETAIL.replace(ROUND, "brf-test-2026-10-14-evening"));
        unavailable(DETAIL.replace(ROUND, "brf-test-2026-10-16-morning"));
    }

    @Test void alteredQuoteOffsetsBodyHashAndForeignVersionFailClosed() throws Exception {
        for (Consumer<ObjectNode> change : java.util.List.<Consumer<ObjectNode>>of(
                detail -> ((ObjectNode) detail.path("evidence").get(0)).put("quote", "허위인용"),
                detail -> ((ObjectNode) detail.at("/evidence/0/bodyContext")).put("quoteStart", 2),
                detail -> ((ObjectNode) detail.at("/evidence/0/bodyContext")).put("text", BODY.replace("😀합성", "😀변조")),
                detail -> ((ObjectNode) detail.path("evidence").get(0)).put("bodySha256", "f".repeat(64)),
                detail -> ((ObjectNode) detail.path("evidence").get(0)).put("documentVersion", "synthetic-v2"),
                detail -> detail.put("roundId", "another-round"),
                detail -> ((ObjectNode) detail.path("metadata")).put("graphVersion", "latest-graph"),
                detail -> ((ObjectNode) detail.path("claims").get(0)).putArray("evidenceIds").add("another-round-evidence"))) {
            load(change); unavailable(DETAIL);
        }
    }

    @Test void registryBodyHashIsImmutableAndCurrentPointerDoesNotReplacePinnedSource() throws Exception {
        jdbc.update("UPDATE articles SET current_version=NULL WHERE id='brf-test-document'");
        assertEquals(200, get(DETAIL).status());
        assertThrows(DataAccessException.class, () -> jdbc.update("UPDATE artifacts SET sha256=? WHERE id='brf-test-text'", "f".repeat(64)));
        assertEquals(BODY_HASH, get(DETAIL).json().at("/evidence/0/bodySha256").asString());
    }

    @Test void generatedSwaggerDocumentsDetailsAndEveryNestedReferenceResolves() throws Exception {
        var doc = get("/v3/api-docs"); assertEquals(200, doc.status());
        assertEquals("getBriefingItemDetail", doc.json().at("/paths/~1api~1v1~1briefings~1{roundId}~1items~1{eventId}/get/operationId").asString());
        for (String schema : java.util.List.of("BriefingItemDetail", "BriefingClaim", "BriefingItemEvidence", "BriefingBodyContext", "PreviousComparison", "PreviousComparisonItem"))
            assertTrue(doc.json().at("/components/schemas/" + schema + "/properties").isObject(), schema);
        for (JsonNode reference : doc.json().findValues("$ref")) if (reference.asString().startsWith("#/components/schemas/"))
            assertFalse(doc.json().at(reference.asString().substring(1)).isMissingNode(), reference.asString());
    }

    @Test void previousComparisonRestoresStoredMembershipAndChecksPreviousOnlySourceAuthority() throws Exception {
        load(ignored -> { }, true, true);
        String path = "/api/v1/briefings?date=2026-10-15&edition=morning";
        var round = get(path); assertEquals(200, round.status(), round.body());
        assertEquals("event_identity", round.json().at("/previousComparison/comparisonBasis").asString());
        assertEquals("new", round.json().at("/previousComparison/items/0/change").asString());
        assertEquals("unavailable", round.json().at("/previousComparison/forecastEvaluation/status").asString());
        assertTrue(round.json().path("sinceMorning").isNull());
        assertEquals(200, get(DETAIL).status());
        jdbc.update("UPDATE articles SET access_status='private' WHERE id='brf-test-document-previous'");
        unavailable(path); unavailable(DETAIL);
        jdbc.update("UPDATE articles SET access_status='available' WHERE id='brf-test-document-previous'");
        assertEquals(200, get(path).status());
    }

    private void unavailable(String path) throws Exception {
        var reply = get(path); assertEquals(503, reply.status(), reply.body());
        assertEquals("SOURCE_UNAVAILABLE", reply.json().at("/error/code").asString());
        assertFalse(reply.body().contains("😀합성"));
    }
    private Reply get(String path) throws Exception {
        var response = http.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path))
                .header("X-Request-ID", "detail-http-request").GET().build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        return new Reply(response.statusCode(), response.body(), JSON.readTree(response.body()));
    }
    private static String resource(String name) throws Exception {
        try (var input = BriefingItemDetailHttpPostgresTest.class.getResourceAsStream("/briefing/" + name)) {
            return new String(input.readAllBytes(), StandardCharsets.UTF_8);
        }
    }
    private static Path grants() {
        try { return Files.createTempFile("zoop-briefing-detail-test-grants-", ".json"); }
        catch (Exception error) { throw new IllegalStateException(error); }
    }
    private static String hash(String value) {
        try { return java.util.HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8))); }
        catch (Exception error) { throw new IllegalStateException(error); }
    }
    private record Reply(int status, String body, JsonNode json) { }
}
