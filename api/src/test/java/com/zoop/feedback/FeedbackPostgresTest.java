package com.zoop.feedback;

import static org.junit.jupiter.api.Assertions.*;

import com.zoop.admin.auth.provision.AdminProvisioningService;
import com.zoop.admin.auth.service.AdminSessionCookie;
import com.zoop.auth.service.MemberSessionService;
import com.zoop.auth.service.SessionCookie;
import java.io.IOException;
import java.net.URI;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.sql.*;
import java.util.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.context.*;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * Real HTTP, real member/admin authorization and PostgreSQL. Synthetic authored publication only;
 * no model calls.
 */
@SpringBootTest(
    webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
    properties = {
      "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
      "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
      "ZOOP_AUTH_ALLOWED_ORIGINS=https://zoop.example"
    })
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
@DirtiesContext(classMode = DirtiesContext.ClassMode.AFTER_CLASS)
class FeedbackPostgresTest {
  private static final String SCHEMA =
      "feedback_http_" + UUID.randomUUID().toString().replace("-", "");
  private static final Path GRANTS = createGrantFile(), GRAPH_ROOT = createGraphRoot();
  private static final JsonMapper JSON = JsonMapper.builder().build();
  private static final String ROUND = "brf-test-2026-10-15-morning",
      EVENT = "brf-test-event",
      ORIGIN = "https://zoop.example";
  @Autowired JdbcTemplate jdbc;
  @Autowired FeedbackVersion versions;
  @Autowired MemberSessionService sessions;
  @Autowired AdminProvisioningService admins;
  @LocalServerPort int port;
  private final HttpClient http = HttpClient.newHttpClient();

  @DynamicPropertySource
  static void properties(DynamicPropertyRegistry p) {
    p.add("spring.datasource.url", () -> databaseUrl(SCHEMA));
    p.add("spring.flyway.schemas", () -> SCHEMA);
    p.add("spring.flyway.default-schema", () -> SCHEMA);
    p.add("spring.jpa.properties.hibernate.default_schema", () -> SCHEMA);
    p.add("zoop.document-read.grants", () -> GRANTS.toString());
    p.add("zoop.document-read.artifact-root", () -> GRAPH_ROOT.toString());
    p.add(
        "zoop.document-read.ingestion-sources",
        () -> GRAPH_ROOT.resolve("sources.json").toString());
    p.add("zoop.graph.snapshot.source", () -> "artifact");
    p.add("zoop.graph.snapshot.artifact-root", () -> GRAPH_ROOT.toString());
  }

  @BeforeEach
  void fixture() throws Exception {
    jdbc.execute("TRUNCATE briefing_rounds,graph_versions,articles,companies,artifacts CASCADE");
    Files.writeString(GRANTS, resource("grants.json"));
    jdbc.execute(resource("fixture.sql"));
  }

  @AfterAll
  static void cleanup() throws Exception {
    try (var c = DriverManager.getConnection(System.getenv("DB_URL"), username(), password());
        var s = c.createStatement()) {
      s.execute("DROP SCHEMA IF EXISTS " + SCHEMA + " CASCADE");
    }
    Files.deleteIfExists(GRANTS);
    try (var paths = Files.walk(GRAPH_ROOT)) {
      for (var p : paths.sorted(Comparator.reverseOrder()).toList()) Files.deleteIfExists(p);
    }
  }

  @Test
  void saveReloadEditCancelAndIdempotencePreserveOneRow() throws Exception {
    var a = member();
    var b = member();
    assertEquals(200, vote(a, ROUND, "up", null, "synthetic-graph-v1").status());
    Timestamp first =
        jdbc.queryForObject("SELECT updated_at FROM briefing_feedback", Timestamp.class);
    assertEquals(200, vote(a, ROUND, "up", null, "synthetic-graph-v1").status());
    assertEquals(
        first, jdbc.queryForObject("SELECT updated_at FROM briefing_feedback", Timestamp.class));
    assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM briefing_feedback", Integer.class));
    assertEquals(200, vote(a, ROUND, "down", "근거를 더 보고 싶어요", "synthetic-graph-v1").status());
    var mine =
        request("GET", "/api/v1/feedback?feature=briefing_round&targetIds=" + ROUND, a, null);
    assertEquals("근거를 더 보고 싶어요", mine.json().at("/items/0/reason").asText());
    assertEquals(0, request("GET", "/api/v1/feedback", b, null).json().path("items").size());
    assertEquals(200, vote(a, ROUND, "none", null, "synthetic-graph-v1").status());
    assertEquals("none", jdbc.queryForObject("SELECT value FROM briefing_feedback", String.class));
    assertNull(jdbc.queryForObject("SELECT reason FROM briefing_feedback", String.class));
    assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM briefing_feedback", Integer.class));
  }

  @Test
  void rejectsGuestCsrfForgedTargetAndStaleVersion() throws Exception {
    var a = member();
    String body = payload(ROUND, "up", null, "synthetic-graph-v1");
    assertEquals(401, request("PUT", "/api/v1/feedback", null, body).status());
    var g = sessions.issueGuest(null, "feedback-test");
    assertEquals(
        403,
        request(
                "PUT",
                "/api/v1/feedback",
                new Login(SessionCookie.NAME + "=" + g.token(), g.response().csrfToken()),
                body)
            .status());
    assertEquals(
        403, request("PUT", "/api/v1/feedback", new Login(a.cookie(), null), body).status());
    assertEquals(409, vote(a, ROUND, "up", null, "wrong-version").status());
    assertEquals(404, vote(a, ROUND + "/missing", "up", null, "synthetic-graph-v1").status());
    assertEquals(422, vote(a, ROUND, "up", "not for up", "synthetic-graph-v1").status());
    assertEquals(
        422,
        request(
                "PUT",
                "/api/v1/feedback",
                a,
                body.substring(0, body.length() - 1) + ",\"memberId\":\"forged\"}")
            .status());
    assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM briefing_feedback", Integer.class));
  }

  @Test
  void nullGraphUsesImmutablePublicationDigestWithoutChangingOriginal() throws Exception {
    jdbc.execute("TRUNCATE briefing_rounds,graph_versions,articles,companies,artifacts CASCADE");
    jdbc.execute(
        resource("fixture.sql")
            .replace("\"graphVersion\":\"synthetic-graph-v1\"", "\"graphVersion\":null"));
    String hash =
        jdbc.queryForObject(
            "SELECT payload_sha256 FROM briefing_rounds WHERE id=?", String.class, ROUND);
    assertEquals("publication:" + hash, versions.get(ROUND));
    // A missing graph must not bypass the public reader's production provenance gate.
    // The opt-in historical replay path is verified separately with stored publications.
    assertEquals(503, vote(member(), ROUND, "up", null, "publication:" + hash).status());
    assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM briefing_feedback", Integer.class));
    assertEquals(
        hash,
        jdbc.queryForObject(
            "SELECT payload_sha256 FROM briefing_rounds WHERE id=?", String.class, ROUND));
  }

  @Test
  void sameIssueInTwoRoundsIsTwoTargetsAndSignedPagingIsMemberBound() throws Exception {
    var a = member();
    var b = member();
    assertEquals(200, vote(a, ROUND + "/" + EVENT, "up", null, "synthetic-graph-v1").status());
    assertEquals(
        200,
        vote(a, "brf-test-2026-10-15-evening/" + EVENT, "down", "저녁 이유", "synthetic-graph-v1")
            .status());
    var page = request("GET", "/api/v1/feedback?limit=1", a, null);
    String cursor = page.json().path("nextCursor").asText();
    assertFalse(cursor.isBlank());
    var next = request("GET", "/api/v1/feedback?cursor=" + cursor, a, null);
    assertEquals(200, next.status());
    assertEquals(1, next.json().path("items").size());
    assertNotEquals(
        page.json().at("/items/0/targetId").asText(), next.json().at("/items/0/targetId").asText());
    assertEquals(422, request("GET", "/api/v1/feedback?cursor=" + cursor, b, null).status());
    assertEquals(422, request("GET", "/api/v1/feedback?cursor=" + cursor + "x", a, null).status());
    assertEquals(
        422,
        request("GET", "/api/v1/feedback?cursor=" + cursor + "&feature=briefing_round", a, null)
            .status());
  }

  @Test
  void suspensionBlocksNewVoteButAllowsWithdrawalAndExcludesAggregate() throws Exception {
    var a = member();
    var admin = admin();
    assertEquals(200, vote(a, ROUND, "down", "이유", "synthetic-graph-v1").status());
    jdbc.execute(
        "BEGIN; INSERT INTO"
            + " briefing_changes(round_id,kind,seq,suspended,reason,admin_id,admin_email_snapshot,created_at)"
            + " VALUES('"
            + ROUND
            + "','suspension',1,true,'synthetic"
            + " test','synthetic-admin','admin@example.invalid',now()); UPDATE briefing_rounds SET"
            + " status='suspended',revision=revision+1 WHERE id='"
            + ROUND
            + "'; COMMIT;");
    assertEquals(409, vote(member(), ROUND, "up", null, "synthetic-graph-v1").status());
    assertEquals(0, summary(admin).at("/features/0/total").asInt());
    assertEquals(200, vote(a, ROUND, "none", null, "synthetic-graph-v1").status());
  }

  @Test
  void adminSummaryDislikesMinSampleAndPrivacyUseCurrentNonCancelledVotes() throws Exception {
    var admin = admin();
    for (int i = 0; i < 5; i++)
      assertEquals(
          200,
          vote(
                  member(),
                  ROUND,
                  i < 4 ? "up" : "down",
                  i < 4 ? null : "더 구체적인 비교가 필요해요",
                  "synthetic-graph-v1")
              .status());
    var cancelled = member();
    vote(cancelled, ROUND, "down", "취소할 이유", "synthetic-graph-v1");
    vote(cancelled, ROUND, "none", null, "synthetic-graph-v1");
    var result = summary(admin);
    assertEquals(5, result.at("/features/0/total").asInt());
    assertEquals(0.8, result.at("/features/0/rate").asDouble());
    assertEquals(0, result.at("/features/1/total").asInt());
    assertTrue(result.at("/features/1/rate").isNull());
    assertEquals("chatbot_answer", result.at("/unsupported/0/feature").asText());
    var dislikes = request("GET", "/api/v1/admin/feedback/dislikes?window=all", admin, null);
    assertEquals(200, dislikes.status());
    assertEquals(1, dislikes.json().path("total").asInt());
    assertEquals("더 구체적인 비교가 필요해요", dislikes.json().at("/items/0/reason").asText());
    assertTrue(dislikes.json().at("/items/0/voter").asText().startsWith("voter-"));
    assertFalse(dislikes.body().contains("@example.com"));
    assertEquals(401, request("GET", "/api/v1/admin/feedback/summary", null, null).status());
    assertEquals(401, request("GET", "/api/v1/admin/feedback/dislikes", member(), null).status());
  }

  @Test
  void adminPagingPeriodAndSubSampleRatesAreExplicit() throws Exception {
    var a = admin();
    var b = admin();
    vote(member(), ROUND, "down", "사유1", "synthetic-graph-v1");
    vote(member(), ROUND, "down", "사유2", "synthetic-graph-v1");
    var small = summary(a);
    assertTrue(small.at("/features/0/sampleHidden").asBoolean());
    assertTrue(small.at("/features/0/rate").isNull());
    var first = request("GET", "/api/v1/admin/feedback/dislikes?limit=1", a, null);
    String cursor = first.json().path("nextCursor").asText();
    var second = request("GET", "/api/v1/admin/feedback/dislikes?cursor=" + cursor, a, null);
    assertEquals(200, second.status());
    assertNotEquals(
        first.json().at("/items/0/voter").asText(), second.json().at("/items/0/voter").asText());
    assertEquals(
        422, request("GET", "/api/v1/admin/feedback/dislikes?cursor=" + cursor, b, null).status());
    assertEquals(
        422,
        request("GET", "/api/v1/admin/feedback/summary?start=2026-10-30&end=2026-10-01", a, null)
            .status());
    assertEquals(
        422, request("GET", "/api/v1/admin/feedback/summary?window=bad", a, null).status());
    jdbc.update(
        "UPDATE briefing_feedback SET"
            + " created_at='2026-10-01T00:00:00Z',updated_at='2026-10-28T14:59:59Z'");
    jdbc.update(
        "UPDATE briefing_feedback SET updated_at='2026-10-28T15:00:00Z' WHERE id=(SELECT id FROM"
            + " briefing_feedback LIMIT 1)");
    var day =
        request("GET", "/api/v1/admin/feedback/summary?start=2026-10-29&end=2026-10-29", a, null);
    assertEquals(1, day.json().at("/features/0/total").asInt());
  }

  @Test
  void adminMasksReasonOnReadAndPreservesMemberOriginal() throws Exception {
    var member = member();
    var admin = admin();
    String original = "Synthetic Member other@example.com 010-1234-5678 2026-10-29";
    assertEquals(200, vote(member, ROUND, "down", original, "synthetic-graph-v1").status());
    assertEquals(
        original,
        request("GET", "/api/v1/feedback", member, null).json().at("/items/0/reason").asText());
    var response = request("GET", "/api/v1/admin/feedback/dislikes", admin, null);
    assertEquals(200, response.status());
    assertEquals("[이름] [이메일] [전화번호] 2026-10-29", response.json().at("/items/0/reason").asText());
    assertEquals(
        original, jdbc.queryForObject("SELECT reason FROM briefing_feedback", String.class));
  }

  private JsonNode summary(Login a) throws Exception {
    var r = request("GET", "/api/v1/admin/feedback/summary", a, null);
    assertEquals(200, r.status(), r.body());
    return r.json();
  }

  private Login member() {
    String id = "feedback-" + UUID.randomUUID();
    jdbc.update(
        """
        INSERT INTO members(id,analytics_key,email,email_key,display_name,password_hash,signup_method,status,completed,tutorial_completed,settings_version,created_at,updated_at)
        VALUES(?,?,?,?,?,'test-hash','email','active',true,true,1,now(),now())
        """,
        id,
        id,
        id + "@example.com",
        id + "@example.com",
        "Synthetic Member");
    var s = sessions.issue(id, null, "feedback-test");
    return new Login(SessionCookie.NAME + "=" + s.token(), s.response().csrfToken());
  }

  private Login admin() throws Exception {
    String email = "feedback-admin-" + UUID.randomUUID() + "@example.com";
    admins.provision(email, "Synthetic Admin", "Secure admin password 2026", "feedback-admin");
    var response =
        http.send(
            HttpRequest.newBuilder(uri("/api/v1/admin/auth/login"))
                .header("Origin", ORIGIN)
                .header("Content-Type", "application/json")
                .POST(
                    HttpRequest.BodyPublishers.ofString(
                        JSON.writeValueAsString(
                            Map.of("email", email, "password", "Secure admin password 2026"))))
                .build(),
            HttpResponse.BodyHandlers.ofString());
    assertEquals(200, response.statusCode(), response.body());
    String cookie =
        response.headers().allValues("set-cookie").stream()
            .filter(s -> s.startsWith(AdminSessionCookie.NAME + "="))
            .findFirst()
            .orElseThrow()
            .split(";", 2)[0];
    return new Login(cookie, JSON.readTree(response.body()).path("csrfToken").asText());
  }

  private Reply vote(Login a, String target, String value, String reason, String version)
      throws Exception {
    return request("PUT", "/api/v1/feedback", a, payload(target, value, reason, version));
  }

  private String payload(String target, String value, String reason, String version) {
    var n =
        JSON.createObjectNode()
            .put(
                "feature",
                target.contains("/" + EVENT) || target.endsWith("/missing")
                    ? "briefing_issue"
                    : "briefing_round")
            .put("targetId", target)
            .put("targetVersion", version)
            .put("value", value);
    if (reason != null) n.put("reason", reason);
    return n.toString();
  }

  private Reply request(String method, String path, Login a, String body) throws Exception {
    var b =
        HttpRequest.newBuilder(uri(path))
            .header("Origin", ORIGIN)
            .header("X-Request-ID", "feedback-test");
    if (a != null) {
      b.header("Cookie", a.cookie());
      if (a.csrf() != null) b.header("X-CSRF-Token", a.csrf());
    }
    if (body != null) b.header("Content-Type", "application/json");
    var r =
        http.send(
            b.method(
                    method,
                    body == null
                        ? HttpRequest.BodyPublishers.noBody()
                        : HttpRequest.BodyPublishers.ofString(body))
                .build(),
            HttpResponse.BodyHandlers.ofString());
    return new Reply(r.statusCode(), r.body(), JSON.readTree(r.body()));
  }

  private URI uri(String path) {
    return URI.create("http://127.0.0.1:" + port + path);
  }

  private record Login(String cookie, String csrf) {}

  private record Reply(int status, String body, JsonNode json) {}

  private static String username() {
    return System.getenv().getOrDefault("DB_USERNAME", "company_test");
  }

  private static String password() {
    return System.getenv().getOrDefault("DB_PASSWORD", "");
  }

  private static String databaseUrl(String schema) {
    String url = System.getenv("DB_URL");
    return url + (url.contains("?") ? "&" : "?") + "currentSchema=" + schema + ",public";
  }

  private static String resource(String name) throws IOException {
    try (var input = FeedbackPostgresTest.class.getResourceAsStream("/briefing/" + name)) {
      if (input == null) throw new IOException("Missing synthetic briefing resource");
      return new String(input.readAllBytes(), StandardCharsets.UTF_8);
    }
  }

  private static Path createGraphRoot() {
    try {
      Path root = Files.createTempDirectory("zoop-briefing-graph-").toRealPath();
      Files.createDirectory(root.resolve("graph"));
      Files.createDirectory(root.resolve("verification_receipt"));
      Files.setPosixFilePermissions(
          root.resolve("verification_receipt"),
          java.nio.file.attribute.PosixFilePermissions.fromString("rwx------"));
      Files.writeString(root.resolve("sources.json"), "{}");
      Files.setPosixFilePermissions(
          root, java.nio.file.attribute.PosixFilePermissions.fromString("rwx------"));
      Files.setPosixFilePermissions(
          root.resolve("graph"),
          java.nio.file.attribute.PosixFilePermissions.fromString("rwx------"));
      return root;
    } catch (IOException failure) {
      throw new IllegalStateException(failure);
    }
  }

  private static Path createGrantFile() {
    try {
      Path path =
          Files.createTempFile("zoop-briefing-http-synthetic-grants-", ".json").toAbsolutePath();
      Files.writeString(path, resource("grants.json"));
      return path;
    } catch (IOException failure) {
      throw new IllegalStateException("Cannot prepare synthetic grant registry", failure);
    }
  }
}
