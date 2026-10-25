package com.zoop.admin.dashboard;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.zoop.admin.auth.provision.AdminProvisioningService;
import com.zoop.admin.auth.service.AdminSessionCookie;
import com.zoop.admin.jobs.AnalysisJobService;
import com.zoop.admin.jobs.AnalyzePlanState.ServiceBinding;
import com.zoop.admin.jobs.JdbcAnalysisJobRepository;
import com.zoop.admin.jobs.JdbcAnalyzePlanRepository;
import com.zoop.ai.ExecutionMode;
import com.zoop.ai.PipelineJob;
import com.zoop.ai.extraction.ExtractionSubmission;
import com.zoop.ai.plan.PlanAdmission;
import com.zoop.ai.plan.PlanIdentity;
import com.zoop.ai.plan.PlanManifest;
import com.zoop.ai.plan.PlanReference;
import com.zoop.ai.relation.RelationSubmission;
import com.zoop.ai.relation.RelationUpstream;
import com.zoop.common.json.Canonical;
import com.zoop.common.request.RequestIdFilter;
import jakarta.servlet.http.Cookie;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
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

/** Synthetic DB fixtures only: the dashboard and jobs API share public rows, not AI attempts or publication authority. */
@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "ZOOP_AUTH_ALLOWED_ORIGINS=https://zoop.example",
        "zoop.analysis.analyze-plan.enabled=false"
})
@Import(AdminDashboardPostgresTest.Time.class)
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
@Transactional(isolation = Isolation.REPEATABLE_READ)
class AdminDashboardPostgresTest {
    private static final Instant NOW = Instant.parse("2096-10-24T12:00:00Z");
    private static final String DIGEST = "a".repeat(64);
    private static final String ORIGIN = "https://zoop.example";
    private static final ServiceBinding BINDING = ServiceBinding.of("https://synthetic.invalid", "dashboard-test");

    @TestConfiguration(proxyBeanMethods = false)
    static class Time {
        @Bean @Primary Clock dashboardClock() { return Clock.fixed(NOW, ZoneOffset.UTC); }
    }

    @Autowired WebApplicationContext context;
    @Autowired RequestIdFilter requestIds;
    @Autowired AdminProvisioningService provisioning;
    @Autowired JdbcTemplate jdbc;
    @Autowired JdbcAnalysisJobRepository jobs;
    @Autowired JdbcAnalyzePlanRepository plans;
    @Autowired AnalysisJobService service;
    @Autowired ObjectMapper mapper;
    private MockMvc mvc;

    @BeforeEach
    void setup() {
        mvc = MockMvcBuilders.webAppContextSetup(context).addFilters(requestIds).build();
    }

    @Test
    void dashboardReadsAdminAppCountsBoundedRecentAndExactPublicJobMapping() throws Exception {
        mvc.perform(get("/api/v1/admin/dashboard")).andExpect(status().isUnauthorized());
        Cookie admin = login();
        var before = service.dashboardAt(NOW);
        assertNull(before.active(), "the shared administrator slot must be free for this fixture");

        // An old running app job stays active even though it is outside the five recent requests.
        String running = planJob(Instant.parse("1900-01-01T00:00:00Z"));
        var claim = plans.claimNext().orElseThrow();
        assertEquals(running, claim.appJobId());
        var runningRow = jobs.adminJob(running).orElseThrow();
        assertTrue(plans.bindAdmission(claim, admission(new PlanReference(runningRow.planId(), DIGEST))));
        String queued = planJob(NOW);

        List<String> tied = new ArrayList<>();
        String prefix = "job-dashboard-" + UUID.randomUUID().toString().replace("-", "");
        for (int i = 0; i < 7; i++) {
            String id = prefix + "-" + i;
            legacy(id, "admin", "succeeded", NOW.minusSeconds(100), NOW.minusSeconds(90));
            tied.add(id);
        }
        // Several worker attempts are still one application job, with historical null outputs untouched.
        jdbc.update("UPDATE analysis_jobs SET attempts='[{},{},{}]'::jsonb WHERE id=?", tied.get(6));

        Instant start = NOW.minusSeconds(86_400);
        legacy(id(), "admin", "failed", start.minusSeconds(60), start.minusNanos(1_000));
        legacy(id(), "admin", "failed", start.minusSeconds(60), start);
        legacy(id(), "admin", "failed", start.minusSeconds(60), NOW.minusNanos(1_000));
        legacy(id(), "admin", "failed", start.minusSeconds(60), NOW);
        legacy(id(), "admin", "failed", start.minusSeconds(60), NOW.plusNanos(1_000));
        String future = id();
        legacy(future, "admin", "queued", NOW.plusNanos(1_000), null);
        for (String state : List.of("queued", "running", "failed")) {
            legacy(id(), "internal_projection", state, NOW.minusSeconds(1),
                    "failed".equals(state) ? NOW.minusNanos(1_000) : null);
        }
        jdbc.execute("SET CONSTRAINTS ALL IMMEDIATE");

        JsonNode dashboard = dashboard(admin);
        JsonNode summary = dashboard.get("jobs");
        assertEquals(NOW, Instant.parse(dashboard.get("generatedAt").stringValue()));
        assertEquals(dashboard.get("generatedAt"), dashboard.get("metadata").get("asOf"));
        assertEquals(before.running() + 1, summary.get("running").longValue());
        assertEquals(before.queued() + 1, summary.get("queued").longValue());
        assertEquals(before.failed24h() + 2, summary.get("failed24h").longValue());
        assertEquals(running, summary.get("active").get("id").stringValue());
        assertEquals(2, summary.get("active").get("planRun").get("totalUnits").intValue());
        assertEquals(0, summary.get("active").get("planRun").get("readyUnits").intValue());
        assertEquals("ai_processing_handoff", summary.get("active").get("planRun").get("completion").stringValue());
        assertFalse(summary.get("active").get("planRun").get("publicChanged").booleanValue());
        assertEquals(publicJob(admin, running), summary.get("active"));
        assertEquals(5, summary.get("recent").size());
        assertEquals(List.of(queued, tied.get(6), tied.get(5), tied.get(4), tied.get(3)),
                ids(summary.get("recent")));
        for (JsonNode job : summary.get("recent")) {
            assertEquals(publicJob(admin, job.get("id").stringValue()), job);
        }
        JsonNode current = summary.get("recent").get(0);
        assertEquals("analyze_plan", current.get("kind").stringValue());
        assertEquals("계획 분석", current.get("label").stringValue());
        assertEquals("awaiting_admission", current.get("planRun").get("phase").stringValue());
        assertTrue(current.get("planRun").get("totalUnits").isNull());
        JsonNode historical = summary.get("recent").get(1);
        assertFalse(historical.has("planRun"));
        for (String field : List.of("report", "ingest", "flush", "ledgerBefore", "ledgerAfter")) {
            assertTrue(historical.has(field));
            assertTrue(historical.get(field).isNull(), field);
        }
        assertTrue(dashboard.get("candidates").isNull());
        assertTrue(dashboard.get("ai").isNull());
        assertTrue(dashboard.get("briefings").isNull());
        for (JsonNode failure : dashboard.get("metadata").get("failures")) {
            assertFalse("jobs".equals(failure.get("section").stringValue()));
        }
    }

    @Test
    void dashboardPreservesFrozenPlanOutcomeWhenANewerAppAttemptContinuesTheSamePlan() throws Exception {
        Cookie admin = login();
        String original = planJob(NOW.minusSeconds(2));
        plans.cancelQueued(original, NOW.minusSeconds(1));
        JsonNode frozen = publicJob(admin, original);
        var source = jobs.adminJob(original).orElseThrow();
        String retry = id();
        jobs.insertQueued(retry, "analyze_plan", source.label(), "synthetic continuation", "dashboard-test", NOW,
                original, "dashboard-retry:" + retry, source.input(), source.planId());
        jdbc.execute("SET CONSTRAINTS ALL IMMEDIATE");

        JsonNode recent = dashboard(admin).get("jobs").get("recent");
        JsonNode historical = null;
        for (JsonNode job : recent) {
            if (original.equals(job.get("id").stringValue())) historical = job;
        }
        assertNotNull(historical);
        assertEquals(frozen.get("planRun"), historical.get("planRun"));
        assertEquals("cancelled", historical.get("planRun").get("phase").stringValue());
        assertTrue(historical.get("planRun").get("totalUnits").isNull());
        assertEquals(publicJob(admin, original), historical);
        assertEquals(retry, recent.get(0).get("id").stringValue());
    }

    private JsonNode dashboard(Cookie admin) throws Exception {
        return mapper.readTree(mvc.perform(get("/api/v1/admin/dashboard").cookie(admin))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString());
    }

    private JsonNode publicJob(Cookie admin, String id) throws Exception {
        return mapper.readTree(mvc.perform(get("/api/v1/admin/jobs/{id}", id).cookie(admin))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString());
    }

    private Cookie login() throws Exception {
        String suffix = UUID.randomUUID().toString();
        String email = "dashboard-" + suffix + "@example.com";
        String password = "Secure admin password 2026";
        provisioning.provision(email, "Dashboard Test", password, "dashboard-provision-" + suffix);
        var response = mvc.perform(post("/api/v1/admin/auth/login").header("Origin", ORIGIN)
                        .contentType("application/json")
                        .content("{\"email\":\"" + email + "\",\"password\":\"" + password + "\"}"))
                .andExpect(status().isOk()).andReturn().getResponse();
        Cookie cookie = response.getCookie(AdminSessionCookie.NAME);
        assertNotNull(cookie);
        return cookie;
    }

    private String planJob(Instant requested) {
        String id = id();
        var reference = new PlanReference("s2plan-" + Canonical.sha256(id), DIGEST);
        plans.register(reference, BINDING, "dashboard-test", requested);
        String input = "{\"schemaVersion\":\"zoop-app-analyze-plan-1\",\"planId\":\"" + reference.planId()
                + "\",\"planDigest\":\"" + DIGEST + "\"}";
        jobs.insertQueued(id, "analyze_plan", "계획 분석", "synthetic dashboard read", "dashboard-test", requested,
                null, "dashboard:" + id, input, reference.planId());
        return id;
    }

    private PlanAdmission admission(PlanReference reference) {
        List<PlanManifest.Unit> units = new ArrayList<>();
        for (int i = 1; i <= 2; i++) {
            String job = "dashboard-s2-" + UUID.randomUUID();
            String input = String.valueOf(i).repeat(64);
            units.add(new PlanManifest.Unit(job, new ExtractionSubmission(job, DIGEST, ExecutionMode.REPLAY), input,
                    new RelationSubmission(PlanIdentity.relationJobId(reference, job, input),
                            PipelineJob.SourceKind.SYNTHETIC, ExecutionMode.REPLAY, new RelationUpstream(job, input))));
        }
        var manifest = new PlanManifest(reference, DIGEST, BINDING.expectedPrincipal(),
                new PlanManifest.Round("authored-source", "authored-round", DIGEST),
                new PipelineJob.Provenance(PipelineJob.SourceKind.SYNTHETIC, ExecutionMode.REPLAY), units, DIGEST);
        return new PlanAdmission(PlanIdentity.admissionId(BINDING.expectedPrincipal(), reference), NOW, 1, DIGEST,
                manifest, new PlanAdmission.Authority(PlanAdmission.State.ACTIVE, Optional.empty()));
    }

    private void legacy(String id, String scope, String state, Instant requested, Instant finished) {
        jdbc.update("""
                INSERT INTO analysis_jobs(id,kind,scope,label,status,reason,requested_by,requested_at,started_at,
                                          finished_at,command_key,input)
                VALUES (?, 'project', ?, 'historical job', ?, 'synthetic dashboard read', 'dashboard-test', ?, ?, ?, ?, '{}')
                """, id, scope, state, Timestamp.from(requested),
                "queued".equals(state) ? null : Timestamp.from(requested),
                finished == null ? null : Timestamp.from(finished), "dashboard:" + id);
    }

    private static List<String> ids(JsonNode rows) {
        List<String> result = new ArrayList<>();
        for (JsonNode row : rows) result.add(row.get("id").stringValue());
        return result;
    }

    private static String id() { return "job-" + UUID.randomUUID(); }
}
