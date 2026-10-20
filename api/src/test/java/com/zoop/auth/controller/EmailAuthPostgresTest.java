package com.zoop.auth.controller;

import java.nio.charset.StandardCharsets;
import java.net.InetAddress;
import java.security.MessageDigest;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

import com.zoop.common.request.RequestIdFilter;
import com.zoop.auth.dto.SignupRequest;
import com.zoop.auth.service.EmailAddress;
import com.zoop.auth.service.AuthRateLimiter;
import com.zoop.auth.service.SignupService;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.request.RequestPostProcessor;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.context.WebApplicationContext;
import tools.jackson.databind.ObjectMapper;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "ZOOP_AUTH_ALLOWED_ORIGINS=https://zoop.example"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
class EmailAuthPostgresTest {
    private static final String PASSWORD = "correct horse battery staple";
    private static final String ORIGIN = "https://zoop.example";

    @Autowired WebApplicationContext context;
    @Autowired RequestIdFilter requestIds;
    @Autowired JdbcTemplate jdbc;
    @Autowired ObjectMapper json;
    @Autowired SignupService signups;
    @Autowired AuthRateLimiter rates;

    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        mvc = MockMvcBuilders.webAppContextSetup(context).addFilters(requestIds).build();
    }

    @Test
    void signupSessionWrongPasswordReloginExpiryAndBlockedAccount() throws Exception {
        String email = "auth-" + UUID.randomUUID() + "@example.com";
        String ip = remoteIp();
        try {
            String signupJson = signupJson(email, currentAgreements());
            var created = mvc.perform(post("/api/v1/auth/signup").with(remote(ip))
                            .header("Origin", ORIGIN).header("X-Request-ID", "signup-req")
                            .contentType(MediaType.APPLICATION_JSON).content(signupJson))
                    .andExpect(status().isCreated())
                    .andExpect(header().exists("Set-Cookie"))
                    .andExpect(jsonPath("$.kind").value("member"))
                    .andExpect(jsonPath("$.user.email").value(email))
                    .andExpect(jsonPath("$.user.displayName").value("Test Member"))
                    .andExpect(jsonPath("$.setup.completed").value(false))
                    .andExpect(jsonPath("$.metadata.requestId").value("signup-req"))
                    .andExpect(jsonPath("$.csrfToken").isString())
                    .andReturn();
            String signupToken = token(created);
            assertTrue(created.getResponse().getHeader("Set-Cookie").contains("Max-Age=43200"));

            String memberId = json.readTree(created.getResponse().getContentAsString()).path("user").path("id").asText();
            String hash = jdbc.queryForObject("SELECT password_hash FROM members WHERE id = ?", String.class, memberId);
            assertTrue(hash.startsWith("{argon2id-v1}"));
            assertNotEquals(PASSWORD, hash);
            assertEquals(2, jdbc.queryForObject("SELECT count(*) FROM term_agreements WHERE member_id = ? AND accepted", Integer.class, memberId));
            assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM member_sessions WHERE token_hash = ?", Integer.class, signupToken));

            mvc.perform(post("/api/v1/auth/signup").with(remote(ip)).header("Origin", ORIGIN)
                            .contentType(MediaType.APPLICATION_JSON).content(signupJson))
                    .andExpect(status().isConflict())
                    .andExpect(jsonPath("$.error.code").value("EMAIL_TAKEN"));

            mvc.perform(get("/api/v1/auth/session").cookie(new Cookie("zoop_session", signupToken)))
                    .andExpect(status().isOk()).andExpect(jsonPath("$.kind").value("member"));

            mvc.perform(post("/api/v1/auth/login").with(remote(ip)).header("Origin", ORIGIN)
                            .contentType(MediaType.APPLICATION_JSON)
                            .content(loginJson(email, "wrong password")))
                    .andExpect(status().isUnauthorized())
                    .andExpect(jsonPath("$.error.code").value("INVALID_CREDENTIALS"));
            var relogin = mvc.perform(post("/api/v1/auth/login").with(remote(ip)).header("Origin", ORIGIN)
                            .cookie(new Cookie("zoop_session", signupToken))
                            .contentType(MediaType.APPLICATION_JSON)
                            .content(loginJson(email.toUpperCase(Locale.ROOT), PASSWORD)))
                    .andExpect(status().isOk()).andExpect(jsonPath("$.kind").value("member"))
                    .andReturn();
            String loginToken = token(relogin);
            assertNotEquals(signupToken, loginToken);
            var loginResponse = json.readTree(relogin.getResponse().getContentAsString());
            var sessionResponse = json.readTree(mvc.perform(get("/api/v1/auth/session")
                            .cookie(new Cookie("zoop_session", loginToken)))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.kind").value("member"))
                    .andReturn().getResponse().getContentAsString());
            assertEquals(loginResponse.path("user"), sessionResponse.path("user"));
            assertEquals(loginResponse.path("setup"), sessionResponse.path("setup"));
            assertFalse(sessionResponse.path("setup").path("completed").asBoolean());
            assertFalse(sessionResponse.path("setup").path("tutorialCompleted").asBoolean());
            assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM auth_rate_events WHERE scope = 'login_email_failure' AND subject_hash = ?",
                    Integer.class, subjectHash("login_email_failure", email)));
            mvc.perform(get("/api/v1/auth/session").cookie(new Cookie("zoop_session", signupToken)))
                    .andExpect(status().isOk()).andExpect(jsonPath("$.kind").value("anonymous"));

            jdbc.update("UPDATE member_sessions SET expires_at = ? WHERE token_hash = ?",
                    Timestamp.from(Instant.now().minusSeconds(1)), tokenHash(loginToken));
            mvc.perform(get("/api/v1/auth/session").cookie(new Cookie("zoop_session", loginToken)))
                    .andExpect(status().isOk()).andExpect(jsonPath("$.kind").value("anonymous"));

            jdbc.update("UPDATE members SET status = 'blocked', blocked_at = ? WHERE id = ?",
                    Timestamp.from(Instant.now()), memberId);
            mvc.perform(post("/api/v1/auth/login").with(remote(ip)).header("Origin", ORIGIN)
                            .contentType(MediaType.APPLICATION_JSON).content(loginJson(email, PASSWORD)))
                    .andExpect(status().isForbidden())
                    .andExpect(jsonPath("$.error.code").value("MEMBER_BLOCKED"));
        } finally {
            cleanup(email);
        }
    }

    @Test
    void loginAndSessionReturnLatestCompletedSetupState() throws Exception {
        String email = "setup-complete-" + UUID.randomUUID() + "@example.com";
        String ip = remoteIp();
        try {
            var signup = mvc.perform(post("/api/v1/auth/signup").with(remote(ip))
                            .header("Origin", ORIGIN)
                            .contentType(MediaType.APPLICATION_JSON)
                            .content(signupJson(email, currentAgreements())))
                    .andExpect(status().isCreated())
                    .andExpect(jsonPath("$.setup.completed").value(false))
                    .andReturn();
            String memberId = json.readTree(signup.getResponse().getContentAsString())
                    .path("user").path("id").asText();
            jdbc.update("UPDATE members SET completed = true, tutorial_completed = true WHERE id = ?", memberId);

            var login = mvc.perform(post("/api/v1/auth/login").with(remote(ip))
                            .header("Origin", ORIGIN)
                            .contentType(MediaType.APPLICATION_JSON)
                            .content(loginJson(email, PASSWORD)))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.kind").value("member"))
                    .andExpect(jsonPath("$.setup.completed").value(true))
                    .andExpect(jsonPath("$.setup.tutorialCompleted").value(true))
                    .andReturn();
            var loginResponse = json.readTree(login.getResponse().getContentAsString());
            var sessionResponse = json.readTree(mvc.perform(get("/api/v1/auth/session")
                            .cookie(new Cookie("zoop_session", token(login))))
                    .andExpect(status().isOk())
                    .andReturn().getResponse().getContentAsString());

            assertEquals(loginResponse.path("user"), sessionResponse.path("user"));
            assertEquals(loginResponse.path("setup"), sessionResponse.path("setup"));
        } finally {
            cleanup(email);
        }
    }

    @Test
    void concurrentDuplicateEmailProducesOneMember() throws Exception {
        String email = "race-" + UUID.randomUUID() + "@example.com";
        var agreementValues = currentAgreements().stream()
                .map(item -> new SignupRequest.Agreement((String) item.get("id"),
                        (String) item.get("version"), true)).toList();
        var signup = new SignupRequest(email, PASSWORD, "Race Member", agreementValues);
        var start = new CountDownLatch(1);
        try (var executor = Executors.newFixedThreadPool(2)) {
            List<Future<ErrorCode>> outcomes = List.of(
                    executor.submit(() -> attemptSignup(start, signup, email, "race-1")),
                    executor.submit(() -> attemptSignup(start, signup, email, "race-2")));
            start.countDown();
            List<ErrorCode> results = new ArrayList<>();
            results.add(outcomes.get(0).get());
            results.add(outcomes.get(1).get());
            assertEquals(1, results.stream().filter(value -> value == null).count());
            assertEquals(1, results.stream().filter(value -> value == ErrorCode.EMAIL_TAKEN).count());
            assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM members WHERE email_key = ?", Integer.class, email));
        } finally {
            cleanup(email);
        }
    }

    private ErrorCode attemptSignup(CountDownLatch start, SignupRequest body,
            String email, String requestId) throws Exception {
        start.await();
        try {
            signups.signup(body, EmailAddress.parse(email), null, requestId);
            return null;
        } catch (CustomException exception) {
            return exception.getErrorCode();
        }
    }

    @Test
    void invalidTermsAndDeniedOriginCreateNoMember() throws Exception {
        String email = "terms-" + UUID.randomUUID() + "@example.com";
        String ip = remoteIp();
        try {
            List<Map<String, Object>> valid = currentAgreements();
            assertEquals(2, valid.size());
            List<List<Map<String, Object>>> invalid = List.of(
                    valid.subList(0, 1),
                    List.of(Map.of("id", valid.get(0).get("id"), "version", "obsolete", "accepted", true), valid.get(1)),
                    List.of(Map.of("id", valid.get(0).get("id"), "version", valid.get(0).get("version"), "accepted", false), valid.get(1)));
            for (var agreements : invalid) {
                mvc.perform(post("/api/v1/auth/signup").with(remote(ip)).header("Origin", ORIGIN)
                                .contentType(MediaType.APPLICATION_JSON).content(signupJson(email, agreements)))
                        .andExpect(status().isUnprocessableEntity())
                        .andExpect(jsonPath("$.error.code").value("TERMS_REQUIRED"));
            }
            mvc.perform(post("/api/v1/auth/signup").with(remote(ip))
                            .contentType(MediaType.APPLICATION_JSON).content(signupJson(email, valid)))
                    .andExpect(status().isForbidden())
                    .andExpect(jsonPath("$.error.code").value("ACCESS_DENIED"));
            assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM members WHERE email_key = ?", Integer.class, email));
        } finally {
            cleanup(email);
        }
    }

    @Test
    void unknownAccountAndEmailFailureLimitReturnContractErrors() throws Exception {
        String email = "limited-" + UUID.randomUUID() + "@example.com";
        String unknown = "unknown-" + UUID.randomUUID() + "@example.com";
        String ip = remoteIp();
        try {
            mvc.perform(post("/api/v1/auth/login").with(remote(ip)).header("Origin", ORIGIN)
                            .contentType(MediaType.APPLICATION_JSON).content(loginJson(unknown, PASSWORD)))
                    .andExpect(status().isUnauthorized())
                    .andExpect(jsonPath("$.error.code").value("INVALID_CREDENTIALS"));

            List<SignupRequest.Agreement> accepted = currentAgreements().stream()
                    .map(item -> new SignupRequest.Agreement((String) item.get("id"),
                            (String) item.get("version"), true)).toList();
            var issued = signups.signup(new SignupRequest(email, PASSWORD, null, accepted),
                    EmailAddress.parse(email), null, "limited-signup");
            for (int i = 0; i < 20; i++) {
                rates.recordLoginFailure(email);
            }
            mvc.perform(post("/api/v1/auth/login").with(remote(ip)).header("Origin", ORIGIN)
                            .contentType(MediaType.APPLICATION_JSON).content(loginJson(email, PASSWORD)))
                    .andExpect(status().isTooManyRequests())
                    .andExpect(header().exists("Retry-After"))
                    .andExpect(jsonPath("$.error.code").value("RATE_LIMITED"));
            assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM member_sessions WHERE member_id = ?",
                    Integer.class, issued.response().user().id()));
        } finally {
            cleanup(email);
        }
    }

    @Test
    void malformedBodiesConsumeIpAttemptBudgetBeforeDeserialization() throws Exception {
        assertMalformedBodyLimit("/api/v1/auth/signup", "signup_ip", 10);
        assertMalformedBodyLimit("/api/v1/auth/login", "login_ip", 100);
    }

    private void assertMalformedBodyLimit(String path, String scope, int limit) throws Exception {
        String ip = remoteIp();
        String normalizedIp = InetAddress.getByName(ip).getHostAddress();
        try {
            for (int i = 0; i < limit; i++) {
                mvc.perform(post(path).with(remote(ip)).header("Origin", ORIGIN)
                                .contentType(MediaType.APPLICATION_JSON).content("{"))
                        .andExpect(status().isUnprocessableEntity())
                        .andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"));
            }
            mvc.perform(post(path).with(remote(ip)).header("Origin", ORIGIN)
                            .contentType(MediaType.APPLICATION_JSON).content("{"))
                    .andExpect(status().isTooManyRequests())
                    .andExpect(header().exists("Retry-After"))
                    .andExpect(jsonPath("$.error.code").value("RATE_LIMITED"));
            assertEquals(limit, jdbc.queryForObject(
                    "SELECT count(*) FROM auth_rate_events WHERE scope = ? AND subject_hash = ?",
                    Integer.class, scope, subjectHash(scope, normalizedIp)));
        } finally {
            jdbc.update("DELETE FROM auth_rate_events WHERE scope = ? AND subject_hash = ?",
                    scope, subjectHash(scope, normalizedIp));
        }
    }

    private List<Map<String, Object>> currentAgreements() {
        return jdbc.query("""
                SELECT t.id, v.version FROM terms t JOIN term_versions v ON v.term_id = t.id
                WHERE t.required AND t.retired_at IS NULL
                  AND v.approved_at <= now() AND v.effective_at <= now()
                  AND (v.retired_at IS NULL OR v.retired_at > now())
                ORDER BY t.id
                """, (rs, index) -> Map.<String, Object>of("id", rs.getString("id"),
                        "version", rs.getString("version"), "accepted", true));
    }

    private String signupJson(String email, List<Map<String, Object>> agreements) throws Exception {
        return json.writeValueAsString(Map.of("email", email, "password", PASSWORD,
                "displayName", " Test Member ", "agreements", agreements));
    }

    private String loginJson(String email, String password) throws Exception {
        return json.writeValueAsString(Map.of("email", email, "password", password));
    }

    private static String token(MvcResult result) {
        String header = result.getResponse().getHeader("Set-Cookie");
        assertNotNull(header);
        return header.substring("zoop_session=".length(), header.indexOf(';'));
    }

    private static String tokenHash(String token) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                .digest(token.getBytes(StandardCharsets.US_ASCII)));
    }

    private static String subjectHash(String scope, String subject) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                .digest((scope + "\0" + subject).getBytes(StandardCharsets.UTF_8)));
    }

    private void cleanup(String email) {
        jdbc.update("DELETE FROM term_agreements WHERE member_id IN (SELECT id FROM members WHERE email_key = ?)", email);
        jdbc.update("DELETE FROM member_sessions WHERE member_id IN (SELECT id FROM members WHERE email_key = ?)", email);
        jdbc.update("DELETE FROM members WHERE email_key = ?", email);
    }

    private static RequestPostProcessor remote(String ip) {
        return request -> {
            request.setRemoteAddr(ip);
            return request;
        };
    }

    private static String remoteIp() {
        String hex = UUID.randomUUID().toString().replace("-", "");
        return "2001:db8::" + hex.substring(0, 4) + ":" + hex.substring(4, 8)
                + ":" + hex.substring(8, 12) + ":" + hex.substring(12, 16);
    }
}
