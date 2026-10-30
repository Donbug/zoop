package com.zoop.admin.briefings;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.zoop.admin.auth.provision.AdminProvisioningService;
import com.zoop.admin.auth.service.AdminSessionCookie;
import com.zoop.common.request.RequestIdFilter;
import jakarta.servlet.http.Cookie;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;
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
import tools.jackson.databind.ObjectMapper;

@SpringBootTest(properties = {
    "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test", "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    "ZOOP_AUTH_ALLOWED_ORIGINS=https://zoop.example"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
@Transactional
class AdminBriefingPostgresTest {
    private static final String URL = "/api/v1/admin/briefings";
    @Autowired WebApplicationContext context;
    @Autowired RequestIdFilter requestIds;
    @Autowired AdminProvisioningService provisioning;
    @Autowired JdbcTemplate jdbc;
    @Autowired ObjectMapper mapper;
    private MockMvc mvc;
    private String adminId;

    @BeforeEach void setup() { mvc = MockMvcBuilders.webAppContextSetup(context).addFilters(requestIds).build(); }

    @Test void authorizationAndEmptyOrUnknownRoundsAreNotFabricated() throws Exception {
        mvc.perform(get(URL)).andExpect(status().isUnauthorized());
        Cookie cookie = login();
        mvc.perform(get(URL).cookie(cookie).param("from", "2190-01-01").param("to", "2190-01-01"))
            .andExpect(status().isOk()).andExpect(jsonPath("$.items").isEmpty())
            .andExpect(jsonPath("$.schedule.morning").value("09:20"))
            .andExpect(jsonPath("$.schedule.evening").value("17:30"));
        mvc.perform(get(URL + "/not-stored").cookie(cookie)).andExpect(status().isNotFound());
        jdbc.update("UPDATE admins SET status='blocked' WHERE id=?", adminId);
        mvc.perform(get(URL).cookie(cookie)).andExpect(status().isUnauthorized());
    }

    @Test void dateBoundsUseKstAndSignedCursorRetainsOrderingAndScope() throws Exception {
        Cookie cookie = login();
        seed("page-a", "2191-01-01", "2191-01-01T00:20:00Z", "scheduled");
        seed("page-b", "2191-01-02", "2191-01-01T00:20:00Z", "scheduled");
        seed("next-day", "2191-01-03", "2191-01-01T15:00:00Z", "scheduled");
        String response = mvc.perform(get(URL).cookie(cookie).param("from", "2191-01-01")
            .param("to", "2191-01-01").param("limit", "1"))
            .andExpect(status().isOk()).andExpect(jsonPath("$.items[0].id").value("page-b"))
            .andReturn().getResponse().getContentAsString();
        String cursor = mapper.readTree(response).path("nextCursor").asText();
        mvc.perform(get(URL).cookie(cookie).param("from", "2191-01-01").param("to", "2191-01-01").param("cursor", cursor))
            .andExpect(status().isOk()).andExpect(jsonPath("$.items[0].id").value("page-a"))
            .andExpect(jsonPath("$.nextCursor").isEmpty());
        mvc.perform(get(URL).cookie(cookie).param("cursor", cursor)).andExpect(status().isUnprocessableContent());
        mvc.perform(get(URL).cookie(cookie).param("from", "2191-01-01").param("to", "2191-01-01")
            .param("cursor", cursor + "x")).andExpect(status().isUnprocessableContent());
        Cookie otherAdmin = login();
        mvc.perform(get(URL).cookie(otherAdmin).param("from", "2191-01-01").param("to", "2191-01-01")
            .param("cursor", cursor)).andExpect(status().isUnprocessableContent());
        mvc.perform(get(URL).cookie(cookie).param("from", "2191-01-01T09:20:00+09:00")
            .param("to", "2191-01-01T09:20:00+09:00"))
            .andExpect(status().isOk()).andExpect(jsonPath("$.items.length()").value(2));
    }

    @Test void invalidBoundsAndLimitsAreRejected() throws Exception {
        Cookie cookie = login();
        for (String limit : new String[]{"0", "101", "-1"})
            mvc.perform(get(URL).cookie(cookie).param("limit", limit)).andExpect(status().isUnprocessableContent());
        for (String[] bounds : new String[][]{{"2191-01-02", "2191-01-01"}, {"2191-02-30", "2191-03-01"},
                {"2191-01-01", "2191-01-02T00:00:00Z"}, {"", "2191-01-01"}})
            mvc.perform(get(URL).cookie(cookie).param("from", bounds[0]).param("to", bounds[1]))
                .andExpect(status().isUnprocessableContent());
    }

    @Test void unknownStagesStayUnknownAndOutlookCallsAreNotGenerationAttempts() throws Exception {
        Cookie cookie = login();
        seed("failed-round", "2192-01-01", "2192-01-01T00:20:00Z", "failed");
        attempt("failed-round", 1, "generation", "{\"failureStage\":\"verification\"}");
        attempt("failed-round", 2, "outlook", "{}");
        jdbc.update("UPDATE briefing_rounds SET failure_reason=? WHERE id='failed-round'", "https://private.invalid?token=secret");
        String body = mvc.perform(get(URL + "/failed-round").cookie(cookie))
            .andExpect(status().isOk()).andExpect(jsonPath("$.attempts").value(1))
            .andExpect(jsonPath("$.attemptsLog.length()").value(1))
            .andExpect(jsonPath("$.stages.generate.status").value("unknown"))
            .andExpect(jsonPath("$.stages.verify.status").value("failed"))
            .andExpect(jsonPath("$.stages.verify.at").isEmpty())
            .andExpect(jsonPath("$.published").isEmpty()).andExpect(jsonPath("$.reprocessable").value(false))
            .andReturn().getResponse().getContentAsString();
        assertThat(body).doesNotContain("owner_token", "request_key", "generation_token", "private.invalid", "secret");
    }

    @Test void completedAvailableGenerationLedgerProjectsDoneWithoutInventingTimestamps() throws Exception {
        Cookie cookie = login();
        seed("ledger-complete", "2194-01-01", "2194-01-01T00:20:00Z", "scheduled");
        ledgerAttempt("ledger-complete", 1, "generation", "failed", "failed", "succeeded", "failed");
        ledgerAttempt("ledger-complete", 2, "generation", "completed", "available", "reused", "succeeded");
        ledgerAttempt("ledger-complete", 3, "outlook", "failed", "failed", "failed", "failed");
        String before = jdbc.queryForObject("SELECT to_jsonb(r)::text FROM briefing_rounds r WHERE id='ledger-complete'", String.class);
        mvc.perform(get(URL + "/ledger-complete").cookie(cookie)).andExpect(status().isOk())
            .andExpect(jsonPath("$.attempts").value(2))
            .andExpect(jsonPath("$.stages.generate.status").value("done"))
            .andExpect(jsonPath("$.stages.verify.status").value("done"))
            .andExpect(jsonPath("$.stages.generate.at").isEmpty())
            .andExpect(jsonPath("$.stages.verify.at").isEmpty())
            .andExpect(jsonPath("$.generatedAt").isEmpty())
            .andExpect(jsonPath("$.stages.publish.status").value("unknown"));
        mvc.perform(get(URL).cookie(cookie).param("from", "2194-01-01").param("to", "2194-01-01"))
            .andExpect(status().isOk()).andExpect(jsonPath("$.items[0].stages.generate.status").value("done"))
            .andExpect(jsonPath("$.items[0].stages.verify.status").value("done"));
        assertThat(jdbc.queryForObject("SELECT to_jsonb(r)::text FROM briefing_rounds r WHERE id='ledger-complete'", String.class)).isEqualTo(before);
    }

    @Test void successfulVerificationTransportDoesNotOverrideWithheldSemanticOutcome() throws Exception {
        Cookie cookie = login();
        seed("ledger-withheld", "2194-01-02", "2194-01-02T00:20:00Z", "failed");
        ledgerAttempt("ledger-withheld", 1, "generation", "completed", "withheld", "succeeded", "succeeded");
        mvc.perform(get(URL + "/ledger-withheld").cookie(cookie)).andExpect(status().isOk())
            .andExpect(jsonPath("$.stages.generate.status").value("done"))
            .andExpect(jsonPath("$.stages.verify.status").value("failed"))
            .andExpect(jsonPath("$.stages.verify.at").isEmpty());
    }

    @Test void activeVerificationPreservesCompletedGenerationAndUnknownOutcomeStaysUnknown() throws Exception {
        Cookie cookie = login();
        seed("ledger-active", "2194-01-03", "2194-01-03T00:20:00Z", "scheduled");
        ledgerAttempt("ledger-active", 1, "generation", "verifying", null, "succeeded", "running");
        jdbc.update("""
            UPDATE briefing_rounds r SET status='verifying',attempt_no=1,generation_token=a.owner_token,lease_until=a.lease_until
            FROM briefing_attempts a WHERE r.id='ledger-active' AND a.round_id=r.id
            """);
        mvc.perform(get(URL + "/ledger-active").cookie(cookie)).andExpect(status().isOk())
            .andExpect(jsonPath("$.stages.generate.status").value("done"))
            .andExpect(jsonPath("$.stages.verify.status").value("running"));
        seed("ledger-unknown", "2194-01-04", "2194-01-04T00:20:00Z", "scheduled");
        ledgerAttempt("ledger-unknown", 1, "generation", "completed", null, "succeeded", "succeeded");
        mvc.perform(get(URL + "/ledger-unknown").cookie(cookie)).andExpect(status().isOk())
            .andExpect(jsonPath("$.stages.generate.status").value("done"))
            .andExpect(jsonPath("$.stages.verify.status").value("unknown"));
    }

    @Test void latestAttemptDoesNotBorrowCompletedStagesFromAnOlderAttempt() throws Exception {
        Cookie cookie = login();
        seed("ledger-latest", "2194-01-05", "2194-01-05T00:20:00Z", "failed");
        ledgerAttempt("ledger-latest", 1, "generation", "completed", "available", "succeeded", "succeeded");
        attempt("ledger-latest", 2, "generation", "{}");
        mvc.perform(get(URL + "/ledger-latest").cookie(cookie)).andExpect(status().isOk())
            .andExpect(jsonPath("$.stages.generate.status").value("unknown"))
            .andExpect(jsonPath("$.stages.verify.status").value("unknown"));
    }

    @Test void publishedOriginalCorrectionsAndSuspensionAreReadWithoutChangingStoredHistory() throws Exception {
        Cookie cookie = login();
        seed("published-round", "2193-01-01", "2193-01-01T00:20:00Z", "scheduled");
        publishEmpty("published-round");
        jdbc.update("""
            INSERT INTO briefing_changes(round_id,kind,seq,original,corrected,reason,admin_id,admin_email_snapshot,created_at)
            VALUES('published-round','correction',1,'old','new','synthetic correction',?,'snapshot@example.invalid','2193-01-02')
            """, adminId);
        jdbc.update("""
            INSERT INTO briefing_changes(round_id,kind,seq,suspended,reason,admin_id,admin_email_snapshot,created_at)
            VALUES('published-round','suspension',1,true,'synthetic suspension',?,'snapshot@example.invalid','2193-01-02')
            """, adminId);
        jdbc.update("UPDATE briefing_rounds SET status='suspended',revision=revision+1 WHERE id='published-round'");
        String before = jdbc.queryForObject("SELECT to_jsonb(r)::text FROM briefing_rounds r WHERE id='published-round'", String.class);
        mvc.perform(get(URL + "/published-round").cookie(cookie))
            .andExpect(status().isOk()).andExpect(jsonPath("$.status").value("suspended"))
            .andExpect(jsonPath("$.published.id").value("published-round"))
            .andExpect(jsonPath("$.published.emptyReason").value("no_issues_in_window"))
            .andExpect(jsonPath("$.itemCount").value(0)).andExpect(jsonPath("$.attempts").value(0))
            .andExpect(jsonPath("$.trigger").isEmpty()).andExpect(jsonPath("$.stages.verify.status").value("unknown"))
            .andExpect(jsonPath("$.stages.publish.status").value("done"))
            .andExpect(jsonPath("$.correctionCount").value(1)).andExpect(jsonPath("$.corrections[0].corrected").value("new"))
            .andExpect(jsonPath("$.corrections[0].adminEmail").value("snapshot@example.invalid"))
            .andExpect(jsonPath("$.suspension.reason").value("synthetic suspension"));
        assertThat(jdbc.queryForObject("SELECT to_jsonb(r)::text FROM briefing_rounds r WHERE id='published-round'", String.class)).isEqualTo(before);
    }

    @Test void unavailableDatabaseReturns503RatherThanEmptyListOrLeakingSql() throws Exception {
        Cookie cookie = login();
        // Transactional DDL is rolled back with the test, and simulates an unavailable relation.
        jdbc.execute("ALTER TABLE briefing_rounds RENAME TO admin_test_offline_rounds");
        String body = mvc.perform(get(URL).cookie(cookie)).andExpect(status().isServiceUnavailable())
            .andExpect(jsonPath("$.error.code").value("SOURCE_UNAVAILABLE"))
            .andReturn().getResponse().getContentAsString();
        assertThat(body).doesNotContain("SELECT", "admin_test_offline_rounds", "PSQLException");
    }

    private Cookie login() throws Exception {
        String suffix = UUID.randomUUID().toString();
        String email = "admin-briefing-" + suffix + "@example.invalid";
        String password = "Secure admin password 2026";
        provisioning.provision(email, "Briefing Read Test", password, "admin-briefing-" + suffix);
        adminId = jdbc.queryForObject("SELECT id FROM admins WHERE email=?", String.class, email);
        var response = mvc.perform(post("/api/v1/admin/auth/login")
            .with(request -> { request.setRemoteAddr("192.0.2.201"); return request; }).header("Origin", "https://zoop.example")
            .contentType("application/json").content(mapper.writeValueAsString(java.util.Map.of("email", email, "password", password))))
            .andExpect(status().isOk()).andReturn().getResponse();
        return response.getCookie(AdminSessionCookie.NAME);
    }
    private void seed(String id, String date, String scheduled, String status) {
        jdbc.update("""
            INSERT INTO briefing_rounds(id,round_date,edition,scheduled_at,window_to,open_start,status)
            VALUES(?,?,'morning',?,?,true,?)
            """, id, LocalDate.parse(date), Timestamp.from(Instant.parse(scheduled)), Timestamp.from(Instant.parse(scheduled)), status);
    }
    private void attempt(String round, int n, String purpose, String stages) {
        String key = UUID.randomUUID().toString();
        jdbc.update("""
            INSERT INTO briefing_attempts(id,round_id,attempt_no,request_key,purpose,trigger,owner_token,status,stages,
              started_at,finished_at,lease_until,failure_reason)
            VALUES(?,?,?,?,?,'scheduler',?,'failed',?::jsonb,now(),now(),now(),'verification_rejected')
            """, key, round, n, key, purpose, key, stages);
    }
    private void ledgerAttempt(String round, int n, String purpose, String status, String outcome,
            String generate, String verify) {
        String key = UUID.randomUUID().toString();
        var stages = mapper.createObjectNode().put("purpose", purpose).put("inputSha256", "a".repeat(64));
        String feature = purpose.equals("generation") ? "briefing" : "briefing-outlook";
        stages.putObject("round_simulation_morning_generation").put("status", generate).put("feature", feature);
        stages.putObject("round_simulation_morning_verification").put("status", verify).put("feature", feature);
        if (outcome != null) stages.put("outcome", outcome);
        jdbc.update("""
            INSERT INTO briefing_attempts(id,round_id,attempt_no,request_key,purpose,trigger,owner_token,status,stages,
              started_at,finished_at,lease_until)
            VALUES(?,?,?,?,?,'scheduler',?,?,?::jsonb,now(),CASE WHEN ? IN ('completed','failed','cancelled') THEN now() END,now()+interval '5 min')
            """, key, round, n, key, purpose, key, status, stages.toString(), status);
    }

    private void publishEmpty(String id) {
        jdbc.update("INSERT INTO artifacts(id,kind,storage_uri,sha256,bytes,media_type,created_at) VALUES('admin-test-artifact','extracted_text','file:///synthetic',?,0,'text/plain',now())", "a".repeat(64));
        jdbc.update("INSERT INTO articles(id,kind,provider,provider_key,lineage_key,access_status,created_at) VALUES('admin-test-article','news','synthetic','admin-test','admin-test','available',now())");
        jdbc.update("INSERT INTO article_versions(article_id,version,title,publication_precision,text_artifact_id,collected_at) VALUES('admin-test-article','v1','Synthetic fixture','unknown','admin-test-artifact',now())");
        jdbc.update("""
            WITH data AS (SELECT id,jsonb_build_object('id',id,'date',round_date,'edition',edition,
                'scheduledAt',scheduled_at,'generatedAt',scheduled_at,'dataWindow',jsonb_build_object('start',null,'end',window_to,'openStart',true),
                'graphVersion',null,'reviewRevision',1,'ruleRevision',null,'items','[]'::jsonb,
                'references',jsonb_build_object('eventIds','[]'::jsonb,'companyIds','[]'::jsonb,'evidenceIds','[]'::jsonb),
                'emptyReason','no_issues_in_window','selectedFrom',0,'marketVariables',null,'metadata','{}'::jsonb,'outlook',null) p
                FROM briefing_rounds WHERE id=?)
            UPDATE briefing_rounds r SET status='published',generated_at=scheduled_at,published_at=scheduled_at,
                review_revision=1,published_payload=data.p,public_snapshot='{"marketSummary":null,"sourceBindings":[{"documentId":"admin-test-article","documentVersion":"v1","grantId":"synthetic","grantRevision":"v1","recipients":["admin-test"]}]}',
                schema_version='admin-test-v1',payload_sha256=encode(sha256(convert_to(data.p::text,'UTF8')),'hex')
            FROM data WHERE r.id=data.id
            """, id);
    }
}
