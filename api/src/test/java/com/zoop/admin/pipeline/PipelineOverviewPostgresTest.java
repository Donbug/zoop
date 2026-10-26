package com.zoop.admin.pipeline;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.zoop.admin.auth.provision.AdminProvisioningService;
import com.zoop.admin.auth.service.AdminSessionCookie;
import com.zoop.admin.jobs.AnalyzePlanState.ServiceBinding;
import com.zoop.admin.jobs.JdbcAnalysisJobRepository;
import com.zoop.admin.jobs.JdbcAnalyzePlanRepository;
import com.zoop.ai.plan.PlanReference;
import com.zoop.common.json.Canonical;
import com.zoop.common.request.RequestIdFilter;
import jakarta.servlet.http.Cookie;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.context.WebApplicationContext;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/** Synthetic rows over the real migration, rolled back; counts are compared before and after, since other tests share the DB. */
@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "ZOOP_AUTH_ALLOWED_ORIGINS=https://zoop.example",
        "zoop.analysis.analyze-plan.enabled=false"
})
@Import(PipelineOverviewPostgresTest.Time.class)
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
@Transactional(isolation = Isolation.REPEATABLE_READ)
class PipelineOverviewPostgresTest {
    private static final Instant NOW = Instant.parse("2097-10-26T12:00:00Z");
    private static final String ORIGIN = "https://zoop.example";
    private static final ServiceBinding BINDING = ServiceBinding.of("https://synthetic.invalid", "overview-test");

    @TestConfiguration(proxyBeanMethods = false)
    static class Time {
        @Bean @Primary Clock overviewClock() { return Clock.fixed(NOW, ZoneOffset.UTC); }
    }

    @Autowired WebApplicationContext context;
    @Autowired RequestIdFilter requestIds;
    @Autowired AdminProvisioningService provisioning;
    @Autowired JdbcTemplate jdbc;
    @Autowired JdbcAnalysisJobRepository jobs;
    @Autowired JdbcAnalyzePlanRepository plans;
    @Autowired JdbcPipelineOverviewReader reader;
    @Autowired ObjectMapper mapper;
    private MockMvc mvc;

    @BeforeEach
    void setup() {
        mvc = MockMvcBuilders.webAppContextSetup(context).addFilters(requestIds).build();
    }

    @Test
    void theOverviewCountsTheAppsReviewTargetsDecisionsAndJobsAndAnswersWhatItCannotKnowAsTheContractAllows() throws Exception {
        mvc.perform(get("/api/v1/admin/pipeline/overview")).andExpect(status().isUnauthorized());
        Cookie admin = login();
        JsonNode before = overview(admin);

        String job = "s3-overview-" + UUID.randomUUID();
        target("candidate", job, "evc-a", "evc-a", "HOLD", true);
        target("candidate", job, "evc-b", "evc-b", "ALLOW", true);
        target("candidate", job, "evc-c", "evc-c", "HOLD", false);
        String decided = target("relation", job, "rel-a", "evc-a", "ALLOW", true);
        target("relation", job, "rel-b", "evc-a", "HOLD", true);
        target("relation", job, "rel-c", "evc-c", "HOLD", false);
        long global = jdbc.queryForObject("SELECT COALESCE(max(global_revision), 0) + 1 FROM review_decisions", Long.class);
        jdbc.update("""
                INSERT INTO review_decisions (target_id, decision, reason, decided_at, revision, global_revision, origin)
                VALUES (?, 'allow', 'synthetic overview read', ?, 1, ?, 'snapshot-migration')
                """, decided, Timestamp.from(NOW.minusSeconds(5)), global);

        String failed = "job-" + UUID.randomUUID();
        legacy(failed, "failed", NOW.minusSeconds(30), NOW.minusSeconds(10));
        jdbc.update("UPDATE analysis_jobs SET error='{\"code\":\"source_unavailable\",\"message\":\"원천을 읽지 못했습니다.\"}'::jsonb"
                + " WHERE id = ?", failed);
        String reported = "job-" + UUID.randomUUID();
        legacy(reported, "succeeded", NOW.minusSeconds(20), NOW.minusSeconds(15));
        jdbc.update("""
                UPDATE analysis_jobs SET report = '{"runId":"run-1","processed":4,"skipped":0,"approved":2,"held":1,"rejected":1,
                  "pending":0,"errorCount":0,"errors":[],"collectionErrorCount":0,"collectionErrors":[],"elapsedSeconds":1.5,
                  "executionMode":"replay","usage":{"calls":3,"replayCalls":3,"inputTokens":10,"outputTokens":5,
                  "elapsedSeconds":1.5,"estimatedCost":null}}'::jsonb WHERE id = ?
                """, reported);
        String plan = planJob(NOW.minusSeconds(1));
        jdbc.execute("SET CONSTRAINTS ALL IMMEDIATE");

        JsonNode after = overview(admin);

        assertEquals(NOW.toString(), after.get("asOf").stringValue());
        assertEquals(PipelineOverviewService.DATABASE, after.get("ledger").get("database").stringValue());
        assertEquals(after.get("asOf"), after.get("ledger").get("checkedAt"));
        assertFalse(after.get("policy").get("webVerification").booleanValue(), "the app never verifies on the web");
        assertTrue(after.get("policy").get("decisionPolicy").isNull());
        assertTrue(after.get("policy").get("validationModel").isNull());

        assertDelta(before, after, "candidates", Map.of("total", 3L, "active", 2L, "inactive", 1L, "hold", 1L, "allow", 1L,
                "reject", 0L));
        assertDelta(before, after, "review", Map.of("decisions", 1L, "allowed", 1L, "rejected", 0L, "holdPendingReview", 1L));
        assertEquals(global, after.get("review").get("revision").longValue());
        assertEquals(0, after.get("review").get("ruleCandidates").longValue(), "a rule never publishes a HOLD");
        assertEquals(0, after.get("review").get("ruleEvents").longValue());

        assertDelta(before, after, "jobs", Map.of("failed24h", 1L, "queued", 1L));
        JsonNode failure = after.get("jobs").get("lastFailure");
        assertEquals(failed, failure.get("jobId").stringValue());
        assertEquals("source_unavailable", failure.get("code").stringValue());
        JsonNode jobList = mapper.readTree(mvc.perform(get("/api/v1/admin/jobs").cookie(admin))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString());
        assertEquals(jobList.get("ingest"), after.get("jobs").get("ingest"), "the same baseline as the jobs tab");

        JsonNode runs = after.get("runs");
        assertTrue(runs.size() <= PipelineOverviewService.RUNS);
        assertEquals(plan, runs.get(0).get("runId").stringValue(), "newest first");
        assertTrue(runs.get(0).get("approved").isNull(), "a plan with no review target yet has no counts");
        assertEquals("admin-job", runs.get(0).get("policyGroup").stringValue());
        assertEquals("job-runner", runs.get(0).get("source").stringValue());
        assertEquals(reported, runs.get(1).get("runId").stringValue(), "always the job id, so a run links to its job");
        assertEquals(4, runs.get(1).get("processed").intValue());
        assertEquals(3, runs.get(1).get("usage").get("calls").intValue());
        assertEquals(failed, runs.get(2).get("runId").stringValue());
        assertTrue(runs.get(2).get("processed").isNull(), "no report: unknown, not zero");
        assertEquals(0, runs.get(2).get("usage").get("calls").intValue());

        // The public version part follows graph_versions whatever other tests left there.
        String active = jdbc.query("SELECT id FROM graph_versions WHERE active", (rs, row) -> rs.getString(1)).stream()
                .findFirst().orElse(null);
        String latest = jdbc.query("SELECT id FROM graph_versions WHERE kind = 'snapshot' ORDER BY sequence DESC LIMIT 1",
                (rs, row) -> rs.getString(1)).stream().findFirst().orElse(null);
        JsonNode publication = after.get("publication");
        assertEquals(active, publication.get("activeVersionId").isNull() ? null : publication.get("activeVersionId").stringValue());
        assertEquals(active != null && active.equals(latest), publication.get("ledgerMatchesActive").booleanValue());
        assertEquals(0, publication.get("issuesOnlyInLedger").size());
        assertEquals(0, publication.get("issuesOnlyInActive").size());
        JsonNode projection = after.get("projection");
        assertTrue(List.of("reflected", "pending", "unavailable").contains(projection.get("status").stringValue()));
        assertTrue(projection.get("neo4j").isNull(), "the graph database is the AI side's");
        if (active == null) assertEquals("unavailable", projection.get("status").stringValue());

        assertEquals(Map.of(), reader.relationStatusesByPlan(List.of(planId(plan))),
                "a plan whose units produced no target has no entry");
    }

    private void assertDelta(JsonNode before, JsonNode after, String section, Map<String, Long> deltas) {
        deltas.forEach((field, delta) -> assertEquals(before.get(section).get(field).longValue() + delta,
                after.get(section).get(field).longValue(), section + "." + field));
    }

    private String target(String type, String job, String external, String candidate, String status, boolean active) {
        String id = "rt-" + UUID.randomUUID();
        jdbc.update("""
                INSERT INTO review_targets (id, target_type, source_job_id, external_id, source_version, candidate_id, status,
                                            active, source_revision, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, '1', ?)
                """, id, type, job, external, "3".repeat(64), candidate, status, active, Timestamp.from(NOW));
        return id;
    }

    private void legacy(String id, String state, Instant requested, Instant finished) {
        jdbc.update("""
                INSERT INTO analysis_jobs(id,kind,scope,label,status,reason,requested_by,requested_at,started_at,
                                          finished_at,command_key,input)
                VALUES (?, 'project', 'admin', 'historical job', ?, 'synthetic overview read', 'overview-test', ?, ?, ?, ?, '{}')
                """, id, state, Timestamp.from(requested), Timestamp.from(requested), Timestamp.from(finished),
                "overview:" + id);
    }

    private String planJob(Instant requested) {
        String id = "job-" + UUID.randomUUID();
        var reference = new PlanReference("s2plan-" + Canonical.sha256(id), "a".repeat(64));
        plans.register(reference, BINDING, "overview-test", requested);
        String input = "{\"schemaVersion\":\"zoop-app-analyze-plan-1\",\"planId\":\"" + reference.planId()
                + "\",\"planDigest\":\"" + "a".repeat(64) + "\"}";
        jobs.insertQueued(id, "analyze_plan", "계획 분석", "synthetic overview read", "overview-test", requested,
                null, "overview:" + id, input, reference.planId());
        return id;
    }

    private String planId(String job) {
        return jdbc.queryForObject("SELECT plan_id FROM analysis_jobs WHERE id = ?", String.class, job);
    }

    private JsonNode overview(Cookie admin) throws Exception {
        return mapper.readTree(mvc.perform(get("/api/v1/admin/pipeline/overview").cookie(admin))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString());
    }

    private Cookie login() throws Exception {
        String suffix = UUID.randomUUID().toString();
        String email = "overview-" + suffix + "@example.com";
        String password = "Secure admin password 2026";
        provisioning.provision(email, "Overview Test", password, "overview-provision-" + suffix);
        var response = mvc.perform(post("/api/v1/admin/auth/login").header("Origin", ORIGIN)
                        .contentType("application/json")
                        .content("{\"email\":\"" + email + "\",\"password\":\"" + password + "\"}"))
                .andExpect(status().isOk()).andReturn().getResponse();
        Cookie cookie = response.getCookie(AdminSessionCookie.NAME);
        assertNotNull(cookie);
        return cookie;
    }
}
