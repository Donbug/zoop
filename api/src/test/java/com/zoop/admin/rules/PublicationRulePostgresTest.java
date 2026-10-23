package com.zoop.admin.rules;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.hamcrest.Matchers.contains;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.jayway.jsonpath.JsonPath;
import com.zoop.admin.auth.provision.AdminProvisioningService;
import com.zoop.admin.auth.service.AdminSessionCookie;
import com.zoop.common.request.RequestIdFilter;
import jakarta.servlet.http.Cookie;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.context.WebApplicationContext;

/** The admin publication rule API over the real migration, admin session, CSRF, publication lock and audit tables. */
@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "ZOOP_AUTH_ALLOWED_ORIGINS=https://zoop.example"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
class PublicationRulePostgresTest {
    private static final String ORIGIN = "https://zoop.example";
    private static final String PASSWORD = "Secure admin password 2026";

    @Autowired WebApplicationContext context;
    @Autowired RequestIdFilter requestIds;
    @Autowired JdbcTemplate jdbc;
    @Autowired AdminProvisioningService provisioning;

    private MockMvc mvc;

    private record Login(Cookie cookie, String csrf) {
    }

    @BeforeEach
    void setUp() {
        mvc = MockMvcBuilders.webAppContextSetup(context).addFilters(requestIds).build();
    }

    @Test
    void theListNeedsAnAdminAndPagesEveryRuleOnceInIdOrder() throws Exception {
        mvc.perform(get("/api/v1/admin/pipeline/rules")).andExpect(status().isUnauthorized());
        String suffix = UUID.randomUUID().toString().replace("-", "");
        Login login = login(suffix);
        List<String> ours = List.of(insertRule("Ta" + suffix, false), insertRule("Tb" + suffix, true),
                insertRule("Tc" + suffix, false));

        List<String> seen = new ArrayList<>();
        String cursor = null;
        do {
            var request = get("/api/v1/admin/pipeline/rules").param("limit", "2").cookie(login.cookie());
            if (cursor != null) request = request.param("cursor", cursor);
            String body = mvc.perform(request).andExpect(status().isOk())
                    .andExpect(jsonPath("$.asOf").isNotEmpty())
                    .andReturn().getResponse().getContentAsString();
            seen.addAll(JsonPath.read(body, "$.items[*].id"));
            cursor = JsonPath.read(body, "$.nextCursor");
        } while (cursor != null);
        assertEquals(seen.size(), seen.stream().distinct().count(), "no rule twice");
        assertEquals(ours, seen.stream().filter(ours::contains).toList(), "every rule once, in id order");

        // An untouched rule is in its default state: no change, no counts until the source projection exists.
        mvc.perform(get("/api/v1/admin/pipeline/rules").param("limit", "100").cookie(login.cookie()))
                .andExpect(jsonPath("$.items[?(@.id == '" + ours.get(1) + "')].enabled").value(true))
                .andExpect(jsonPath("$.items[?(@.id == '" + ours.get(1) + "')].defaultEnabled").value(true))
                .andExpect(jsonPath("$.items[?(@.id == '" + ours.get(1) + "')].changedAt").value(nullValue()))
                .andExpect(jsonPath("$.items[?(@.id == '" + ours.get(1) + "')].eligible").value(nullValue()))
                .andExpect(jsonPath("$.items[?(@.id == '" + ours.get(1) + "')].publishedEvents").value(nullValue()))
                .andExpect(jsonPath("$.items[?(@.id == '" + ours.get(1) + "')].history.length()").value(0));

        String first = mvc.perform(get("/api/v1/admin/pipeline/rules").param("limit", "1").cookie(login.cookie()))
                .andReturn().getResponse().getContentAsString();
        String issued = JsonPath.read(first, "$.nextCursor");
        assertNotNull(issued);
        mvc.perform(get("/api/v1/admin/pipeline/rules").param("cursor", issued).param("limit", "2").cookie(login.cookie()))
                .andExpect(status().isUnprocessableContent());
        mvc.perform(get("/api/v1/admin/pipeline/rules").param("cursor", issued).cookie(login(suffix + "o").cookie()))
                .andExpect(status().isUnprocessableContent());
        mvc.perform(get("/api/v1/admin/pipeline/rules").param("limit", "101").cookie(login.cookie()))
                .andExpect(status().isUnprocessableContent());
    }

    @Test
    void aSwitchRecordsOneChangeUnderTheLockAndTheSameStateRecordsNothing() throws Exception {
        String suffix = UUID.randomUUID().toString().replace("-", "");
        Login login = login(suffix);
        String rule = insertRule("Ts" + suffix, true);
        String other = insertRule("To" + suffix, false);
        long reviewRevision = jdbc.queryForObject("SELECT COALESCE(MAX(global_revision), 0) FROM review_decisions", Long.class);

        set(login, rule, false, "공개 정책 시험").andExpect(status().isOk())
                .andExpect(jsonPath("$.idempotent").value(false))
                .andExpect(jsonPath("$.reviewRevision").value(reviewRevision))
                .andExpect(jsonPath("$.rule.enabled").value(false))
                .andExpect(jsonPath("$.rule.defaultEnabled").value(true))
                .andExpect(jsonPath("$.rule.reason").value("공개 정책 시험"))
                .andExpect(jsonPath("$.rule.changedBy").value("rules-admin-" + suffix + "@example.com"))
                .andExpect(jsonPath("$.rule.history.length()").value(1))
                .andExpect(jsonPath("$.rule.history[0].enabled").value(false));
        long firstLog = logRevision(rule, 1);

        // The state it already has: nothing recorded, the same rule back.
        set(login, rule, false, "다시").andExpect(status().isOk())
                .andExpect(jsonPath("$.idempotent").value(true))
                .andExpect(jsonPath("$.rule.history.length()").value(1));
        assertEquals(1, changeCount(rule));
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM audit_logs WHERE action = 'publication.rule.switch' "
                + "AND target_id = ?", Integer.class, rule));

        // Another rule's change takes the next app-wide log revision; the rule's own revision starts at 1 again.
        set(login, other, true, "켬").andExpect(jsonPath("$.idempotent").value(false));
        assertTrue(logRevision(other, 1) > firstLog);
        set(login, rule, true, "되돌림").andExpect(jsonPath("$.rule.history.length()").value(2))
                .andExpect(jsonPath("$.rule.history[0].enabled").value(true));
        assertTrue(logRevision(rule, 2) > logRevision(other, 1));
        assertEquals("false|true|2", jdbc.queryForObject("""
                SELECT (detail->>'beforeEnabled') || '|' || (detail->>'afterEnabled') || '|' || (detail->>'revision')
                FROM audit_logs WHERE action = 'publication.rule.switch' AND target_id = ? AND detail->>'revision' = '2'
                """, String.class, rule));

        set(login, "Tmissing" + suffix + "@1", true, "없음").andExpect(status().isNotFound());
        set(login, rule, true, " ").andExpect(status().isUnprocessableContent());
        mvc.perform(put("/api/v1/admin/pipeline/rules/{id}", rule).cookie(login.cookie()).header("Origin", ORIGIN)
                        .contentType("application/json").content("{\"enabled\":false,\"reason\":\"x\"}"))
                .andExpect(status().isForbidden());
        assertEquals(2, changeCount(rule));

        // The length limit is on the stored, stripped reason (code points, like the table's CHECK).
        set(login, rule, false, "가".repeat(501)).andExpect(status().isUnprocessableContent());
        set(login, other, false, "가".repeat(500) + "\\n").andExpect(status().isOk())
                .andExpect(jsonPath("$.rule.reason").value("가".repeat(500)));
        assertEquals(2, changeCount(rule));
    }

    @Test
    void aRuleBackAtItsDefaultKeepsItsLatestChangeAndTheWholeHistory() throws Exception {
        String suffix = UUID.randomUUID().toString().replace("-", "");
        Login login = login(suffix);
        String rule = insertRule("Th" + suffix, false);
        set(login, rule, true, "켬").andExpect(status().isOk());
        set(login, rule, false, "기본값으로 되돌림").andExpect(status().isOk());

        mvc.perform(get("/api/v1/admin/pipeline/rules").param("limit", "100").cookie(login.cookie()))
                .andExpect(jsonPath("$.items[?(@.id == '" + rule + "')].enabled").value(contains(false)))
                .andExpect(jsonPath("$.items[?(@.id == '" + rule + "')].reason").value(contains("기본값으로 되돌림")))
                .andExpect(jsonPath("$.items[?(@.id == '" + rule + "')].history.length()").value(contains(2)))
                .andExpect(jsonPath("$.items[?(@.id == '" + rule + "')].history[1].reason").value(contains("켬")));
    }

    @Test
    void theDefinitionIsFixedAndTheChangeLogIsAppendOnly() throws Exception {
        String suffix = UUID.randomUUID().toString().replace("-", "");
        Login login = login(suffix);
        String rule = insertRule("Tf" + suffix, false);
        for (String change : List.of("title = 'other'", "summary = 'other'", "definition = '{\"x\":1}'::jsonb",
                "default_enabled = true", "enabled = true")) {
            assertThrows(DataAccessException.class,
                    () -> jdbc.update("UPDATE publication_rules SET " + change + " WHERE id = ?", rule), change);
        }
        set(login, rule, true, "켬").andExpect(status().isOk());
        assertThrows(DataAccessException.class,
                () -> jdbc.update("UPDATE publication_rule_changes SET reason = 'x' WHERE rule_id = ?", rule));
        assertThrows(DataAccessException.class,
                () -> jdbc.update("DELETE FROM publication_rule_changes WHERE rule_id = ?", rule));
        assertThrows(DataAccessException.class,
                () -> jdbc.update("INSERT INTO publication_rules (id, title, summary, definition, default_enabled, enabled, "
                        + "updated_at) VALUES ('no-version', 't', 's', '{}', false, false, now())"), "the id carries a version");
        assertEquals(1, changeCount(rule));
    }

    /** A filter path ({@code [?(...)]}) reads as a list: the one matching rule's value is null. */
    private static org.hamcrest.Matcher<Iterable<?>> nullValue() {
        return contains((Object) null);
    }

    private ResultActions set(Login login, String rule, boolean enabled, String reason) throws Exception {
        return mvc.perform(put("/api/v1/admin/pipeline/rules/{id}", rule).cookie(login.cookie()).header("Origin", ORIGIN)
                .header("X-CSRF-Token", login.csrf()).contentType("application/json")
                .content("{\"enabled\":" + enabled + ",\"reason\":\"" + reason + "\"}"));
    }

    private Login login(String suffix) throws Exception {
        String email = "rules-admin-" + suffix + "@example.com";
        provisioning.provision(email, "Rules Admin", PASSWORD, "rules-admin-provision-" + suffix);
        MockHttpServletResponse response = mvc.perform(post("/api/v1/admin/auth/login")
                        .header("Origin", ORIGIN).contentType("application/json")
                        .content("{\"email\":\"" + email + "\",\"password\":\"" + PASSWORD + "\"}"))
                .andExpect(status().isOk()).andReturn().getResponse();
        Cookie cookie = response.getCookie(AdminSessionCookie.NAME);
        assertNotNull(cookie);
        return new Login(cookie, JsonPath.read(response.getContentAsString(), "$.csrfToken"));
    }

    /** A synthetic rule in its default state; the prefix keeps it apart from other runs in a shared database. */
    private String insertRule(String name, boolean defaultEnabled) {
        String id = name + "@1";
        jdbc.update("""
                INSERT INTO publication_rules (id, title, summary, definition, default_enabled, enabled, updated_at)
                VALUES (?, '합성 규칙', '시험용 공개 정책', '{"kind":"test"}'::jsonb, ?, ?, now())
                """, id, defaultEnabled, defaultEnabled);
        return id;
    }

    private long logRevision(String rule, long revision) {
        return jdbc.queryForObject("SELECT log_revision FROM publication_rule_changes WHERE rule_id = ? AND revision = ?",
                Long.class, rule, revision);
    }

    private int changeCount(String rule) {
        return jdbc.queryForObject("SELECT count(*) FROM publication_rule_changes WHERE rule_id = ?", Integer.class, rule);
    }
}
