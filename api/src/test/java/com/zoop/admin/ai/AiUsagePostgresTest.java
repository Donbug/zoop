package com.zoop.admin.ai;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.UUID;

import com.zoop.admin.auth.provision.AdminProvisioningService;
import com.zoop.admin.auth.service.AdminSessionCookie;
import com.zoop.common.request.RequestIdFilter;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.context.WebApplicationContext;

/** Synthetic PostgreSQL integration for FS068 / A-ADM-04b Task 2. */
@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "ZOOP_AUTH_ALLOWED_ORIGINS=https://zoop.example"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
@Transactional
class AiUsagePostgresTest {
    private static final String ORIGIN = "https://zoop.example";

    @Autowired WebApplicationContext context;
    @Autowired RequestIdFilter requestIds;
    @Autowired AdminProvisioningService provisioning;
    @Autowired JdbcTemplate jdbc;
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        mvc = MockMvcBuilders.webAppContextSetup(context).addFilters(requestIds).build();
    }

    @Test
    void requiresAdminAndReturnsDocumentUsageWithoutGuessingAnUnknownProviderOutcome() throws Exception {
        mvc.perform(get("/api/v1/admin/ai-usage")).andExpect(status().isUnauthorized());
        Cookie admin = login();
        seedFailedDocumentAnalysisWithUnknownCall();

        mvc.perform(get("/api/v1/admin/ai-usage").param("window", "24h").cookie(admin))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.availability").value("partial"))
                .andExpect(jsonPath("$.window").value("24h"))
                .andExpect(jsonPath("$.features.length()").value(5))
                .andExpect(jsonPath("$.features[0].source").value("ledger-db"))
                .andExpect(jsonPath("$.features[1].feature").value("news-analysis"))
                .andExpect(jsonPath("$.features[1].requests").value(1))
                .andExpect(jsonPath("$.features[1].failed").value(1))
                .andExpect(jsonPath("$.features[1].usage.modelCalls").doesNotExist())
                .andExpect(jsonPath("$.features[1].usage.inputTokens").doesNotExist())
                .andExpect(jsonPath("$.features[1].recentErrors[0].code").value("provider_timeout"));
        mvc.perform(get("/api/v1/admin/ai-usage").param("window", "all").cookie(admin))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.features[1].requests").isNumber())
                .andExpect(jsonPath("$.features[2].source").value("ledger-db"));
        mvc.perform(get("/api/v1/admin/ai-usage").param("window", "90d").cookie(admin))
                .andExpect(status().isUnprocessableContent());
    }

    @Test
    void aggregatesBriefingGenerationAndOutlookSeparately() throws Exception {
        Cookie admin = login();
        seedBriefingUsage();
        boolean hasUnrecordedPublications = jdbc.queryForObject("""
                SELECT EXISTS (SELECT 1 FROM briefing_rounds r
                    WHERE r.published_at BETWEEN now() - interval '24 hours' AND now()
                      AND NOT EXISTS (SELECT 1 FROM briefing_attempts a
                          WHERE a.round_id=r.id AND a.purpose='generation'))
                """, Boolean.class);

        var result = mvc.perform(get("/api/v1/admin/ai-usage").param("window", "24h").cookie(admin))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.features[2].feature").value("briefing"))
                .andExpect(jsonPath("$.features[2].usage.modelCalls").value(hasUnrecordedPublications ? (Object)null : 2))
                .andExpect(jsonPath("$.features[2].usage.retries").value(hasUnrecordedPublications ? (Object)null : 1))
                .andExpect(jsonPath("$.features[2].usage.inputTokens").value(hasUnrecordedPublications ? (Object)null : 30))
                .andExpect(jsonPath("$.features[4].feature").value("briefing-outlook"))
                .andExpect(jsonPath("$.features[4].usage.modelCalls").value(1))
                .andExpect(jsonPath("$.features[4].usage.inputTokens").value(11));
        if (hasUnrecordedPublications) {
            result.andExpect(jsonPath("$.features[2].requests").doesNotExist())
                    .andExpect(jsonPath("$.features[2].unavailableMetrics").isArray())
                    .andExpect(jsonPath("$.features[4].requests").doesNotExist());
        } else {
            result.andExpect(jsonPath("$.features[2].requests").value(1))
                    .andExpect(jsonPath("$.features[2].succeeded").value(1))
                    .andExpect(jsonPath("$.features[4].requests").value(1));
        }
    }

    private Cookie login() throws Exception {
        String suffix = UUID.randomUUID().toString();
        String email = "ai-usage-" + suffix + "@example.com";
        String password = "Secure admin password 2026";
        provisioning.provision(email, "AI Usage Test", password, "ai-usage-provision-" + suffix);
        var response = mvc.perform(post("/api/v1/admin/auth/login").header("Origin", ORIGIN)
                        .contentType("application/json")
                        .content("{\"email\":\"" + email + "\",\"password\":\"" + password + "\"}"))
                .andExpect(status().isOk()).andReturn().getResponse();
        Cookie cookie = response.getCookie(AdminSessionCookie.NAME);
        if (cookie == null) throw new AssertionError("admin login did not set a session cookie");
        return cookie;
    }

    private void seedFailedDocumentAnalysisWithUnknownCall() {
        String suffix = UUID.randomUUID().toString().replace("-", "");
        String article = "article-ai-" + suffix;
        String version = "v1";
        String artifact = "artifact-ai-" + suffix;
        String analysis = "analysis-ai-" + suffix;
        String aiJob = "ai-job-" + suffix;
        Instant now = Instant.now();
        jdbc.update("INSERT INTO artifacts(id,kind,storage_uri,sha256,bytes,media_type,created_at) VALUES(?,?,?,?,?,?,?)",
                artifact, "extracted_text", "file:///synthetic/" + artifact, "a".repeat(64), 0L,
                "text/plain", Timestamp.from(now));
        jdbc.update("INSERT INTO articles(id,kind,provider,provider_key,lineage_key,current_version,access_status,created_at) "
                        + "VALUES(?, 'news', 'synthetic', ?, ?, NULL, 'available', ?)",
                article, suffix, suffix, Timestamp.from(now));
        jdbc.update("INSERT INTO article_versions(article_id,version,title,publication_precision,text_artifact_id,collected_at) "
                        + "VALUES(?, ?, 'synthetic title', 'unknown', ?, ?)", article, version, artifact, Timestamp.from(now));
        jdbc.update("UPDATE articles SET current_version=? WHERE id=?", version, article);
        jdbc.update("""
                INSERT INTO document_analyses(id,article_id,article_version,stage,request_no,status,reason,
                    grant_reference,grant_revision,grant_checked_at,ai_job_id,created_at,updated_at)
                VALUES(?,?,?,'summary',2,'failed','provider_timeout','test-grant','r1',?,?,?,?)
                """, analysis, article, version, Timestamp.from(now), aiJob, Timestamp.from(now), Timestamp.from(now));
        jdbc.update("""
                INSERT INTO ai_executions(id,feature,execution_mode,status,document_analysis_id,stage,
                    provider_send_state,started_at,finished_at,error_code)
                VALUES(?, 'news-analysis','live','unknown',?, 'document-summary','unknown',?,?, 'provider_timeout')
                """, "execution-ai-" + suffix, analysis, Timestamp.from(now), Timestamp.from(now));
    }

    private void seedBriefingUsage() {
        String suffix = UUID.randomUUID().toString().replace("-", "");
        String round = "usage-round-" + suffix;
        String attempt = "usage-attempt-" + suffix;
        Instant now = Instant.now();
        jdbc.update("""
                INSERT INTO briefing_rounds(id,round_date,edition,scheduled_at,window_to,open_start,status)
                VALUES(?,?,'morning',?,?,true,'scheduled')
                """, round, java.time.LocalDate.of(2200, 1, 1).plusDays(Math.floorMod(System.nanoTime(), 100_000)),
                Timestamp.from(now.minusSeconds(600)), Timestamp.from(now));
        String stages = "{\"purpose\":\"generation\",\"inputSha256\":\"" + "a".repeat(64)
                + "\",\"outcome\":\"available\",\"outlook\":{\"requestedAt\":\"" + now.minusSeconds(500)
                + "\",\"outcome\":\"available\"}}";
        jdbc.update("""
                INSERT INTO briefing_attempts(id,round_id,attempt_no,request_key,purpose,trigger,owner_token,status,stages,
                    started_at,finished_at,lease_until)
                VALUES(?,?,1,?,'generation','scheduler',?,'completed',CAST(? AS jsonb),?,?,?)
                """, attempt, round, "request-" + suffix, "owner-" + suffix, stages,
                Timestamp.from(now.minusSeconds(600)), Timestamp.from(now.minusSeconds(100)), Timestamp.from(now.plusSeconds(300)));
        insertBriefingExecution("execution-briefing-gen-" + suffix, "briefing", attempt, "generation", 20L, "retry-unit-" + suffix, now);
        insertBriefingExecution("execution-briefing-verify-" + suffix, "briefing", attempt, "verification", 10L, "retry-unit-" + suffix, now);
        insertBriefingExecution("execution-briefing-outlook-" + suffix, "briefing-outlook", attempt, "outlook", 11L, null, now);
    }

    private void insertBriefingExecution(String id, String feature, String attempt, String stage, long input,
            String retryUnit, Instant now) {
        jdbc.update("""
                INSERT INTO ai_executions(id,feature,execution_mode,status,briefing_attempt_id,stage,attempt_no,
                    transmission_confirmed,retry_unit_id,input_tokens,output_tokens,started_at,finished_at)
                VALUES(?,?,'live','succeeded',?,?,1,true,?,?,5,?,?)
                """, id, feature, attempt, stage, retryUnit, input,
                Timestamp.from(now.minusSeconds(90)), Timestamp.from(now.minusSeconds(80)));
    }
}
