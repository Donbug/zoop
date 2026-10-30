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
import java.util.Map;
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
class AdminBriefingChangePostgresTest {
    private static final String URL = "/api/v1/admin/briefings/write-test";
    @Autowired WebApplicationContext context;
    @Autowired RequestIdFilter requestIds;
    @Autowired AdminProvisioningService provisioning;
    @Autowired JdbcTemplate jdbc;
    @Autowired ObjectMapper mapper;
    private MockMvc mvc;
    private String adminId;
    private Cookie cookie;
    private String csrf;

    @BeforeEach void setup() throws Exception {
        mvc = MockMvcBuilders.webAppContextSetup(context).addFilters(requestIds).build();
        String suffix=UUID.randomUUID().toString(), email="write-"+suffix+"@example.com";
        String password="Secure admin password 2026";
        adminId=provisioning.provision(email,"Briefing Write Test",password,suffix);
        var response=mvc.perform(post("/api/v1/admin/auth/login")
            .with(r->{r.setRemoteAddr("192.0.2.202");return r;})
            .header("Origin","https://zoop.example").contentType("application/json")
            .content(mapper.writeValueAsString(Map.of("email",email,"password",password))))
            .andExpect(status().isOk()).andReturn().getResponse();
        cookie=response.getCookie(AdminSessionCookie.NAME);
        csrf=mapper.readTree(response.getContentAsString()).path("csrfToken").asText();
        seed("write-test","2020-01-01","2020-01-01T00:20:00Z","scheduled");
        publishEmpty("write-test");
    }

    @Test void correctionPreservesOriginalAndReplaysSameResponseOnce() throws Exception {
        String original=original();
        String body="{\"correctedText\":\"확인된 정정 내용\",\"reason\":\"표현 정정\"}";
        String response=write("corrections",body,"correction-1").andExpect(status().isCreated())
            .andExpect(jsonPath("$.seq").value(1)).andReturn().getResponse().getContentAsString();
        String replay=write("corrections",body,"correction-1").andExpect(status().isCreated())
            .andReturn().getResponse().getContentAsString();
        assertThat(mapper.readTree(replay)).isEqualTo(mapper.readTree(response));
        assertThat(count("briefing_changes")).isEqualTo(1);
        assertThat(audits()).isEqualTo(1);
        assertThat(original()).isEqualTo(original);
        mvc.perform(get(URL).cookie(cookie)).andExpect(status().isOk())
            .andExpect(jsonPath("$.correctionCount").value(1))
            .andExpect(jsonPath("$.corrections[0].corrected").value("확인된 정정 내용"));
        write("corrections",body.replace("표현 정정","다른 사유"),"correction-1")
            .andExpect(status().isConflict()).andExpect(jsonPath("$.error.code").value("IDEMPOTENCY_CONFLICT"));
    }

    @Test void suspensionResumeAndRepeatedTargetStateKeepAppendOnlyHistoryAndOriginal() throws Exception {
        String original=original();
        write("suspension","{\"action\":\"suspend\",\"reason\":\"근거 확인 중\"}","suspend-1")
            .andExpect(status().isOk()).andExpect(jsonPath("$.status").value("suspended"))
            .andExpect(jsonPath("$.suspension.reason").value("근거 확인 중"));
        write("suspension","{\"action\":\"suspend\",\"reason\":\"추가 요청\"}","suspend-2").andExpect(status().isOk());
        assertThat(count("briefing_changes")).isEqualTo(1);
        mvc.perform(get("/api/v1/briefings").param("date","2020-01-01").param("edition","morning"))
            .andExpect(status().isOk()).andExpect(jsonPath("$.status").value("suspended"));
        write("suspension","{\"action\":\"resume\",\"reason\":\"확인 완료\"}","resume-1")
            .andExpect(status().isOk()).andExpect(jsonPath("$.status").value("published"))
            .andExpect(jsonPath("$.suspension").isEmpty());
        assertThat(count("briefing_changes")).isEqualTo(2);
        assertThat(audits()).isEqualTo(2);
        assertThat(original()).isEqualTo(original);
        // A lost response replays the original answer; it must not suspend the resumed round again.
        write("suspension","{\"action\":\"suspend\",\"reason\":\"근거 확인 중\"}","suspend-1")
            .andExpect(status().isOk()).andExpect(jsonPath("$.status").value("suspended"));
        assertThat(jdbc.queryForObject("SELECT status FROM briefing_rounds WHERE id='write-test'",String.class)).isEqualTo("published");
        assertThat(count("briefing_changes")).isEqualTo(2);
    }

    @Test void missingCsrfOriginAndIdempotencyKeyCannotChangeARecord() throws Exception {
        String body="{\"action\":\"suspend\",\"reason\":\"확인 중\"}";
        mvc.perform(post(URL+"/suspension").contentType("application/json").content(body)).andExpect(status().isUnauthorized());
        mvc.perform(post(URL+"/suspension").cookie(cookie).contentType("application/json").content(body)).andExpect(status().isForbidden());
        mvc.perform(post(URL+"/suspension").cookie(cookie).header("Origin","https://evil.example").header("X-CSRF-Token",csrf)
            .contentType("application/json").content(body)).andExpect(status().isForbidden());
        mvc.perform(post(URL+"/suspension").cookie(cookie).header("Origin","https://zoop.example").header("X-CSRF-Token",csrf)
            .contentType("application/json").content(body)).andExpect(status().isUnprocessableContent());
        assertThat(count("briefing_changes")).isZero();
    }

    @Test void badEventInvalidInputAndUnpublishedRoundCannotCreateHistory() throws Exception {
        write("corrections","{\"eventId\":\"unknown\",\"correctedText\":\"정정\",\"reason\":\"확인\"}","unknown-event").andExpect(status().isUnprocessableContent());
        for(String body:new String[]{"{}","{\"action\":\"other\",\"reason\":\"확인\"}","{\"action\":\"suspend\",\"reason\":\"token=secret\"}"})
            write("suspension",body,UUID.randomUUID().toString()).andExpect(status().isUnprocessableContent());
        seed("unpublished","2020-01-02","2020-01-02T00:20:00Z","failed");
        mvc.perform(post("/api/v1/admin/briefings/unpublished/suspension").cookie(cookie).header("Origin","https://zoop.example")
            .header("X-CSRF-Token",csrf).header("Idempotency-Key","unpublished").contentType("application/json")
            .content("{\"action\":\"suspend\",\"reason\":\"확인\"}")).andExpect(status().isConflict());
        assertThat(count("briefing_changes")).isZero();
    }

    private org.springframework.test.web.servlet.ResultActions write(String op,String body,String key) throws Exception {
        return mvc.perform(post(URL+"/"+op).cookie(cookie).header("Origin","https://zoop.example").header("X-CSRF-Token",csrf)
            .header("Idempotency-Key",key).contentType("application/json").content(body));
    }
    private String original(){return jdbc.queryForObject("SELECT published_payload::text||public_snapshot::text||payload_sha256 FROM briefing_rounds WHERE id='write-test'",String.class);}
    private long count(String table){return jdbc.queryForObject("SELECT count(*) FROM "+table+" WHERE round_id='write-test'",Long.class);}
    private long audits(){return jdbc.queryForObject("SELECT count(*) FROM audit_logs WHERE target_type='briefing_round' AND target_id='write-test'",Long.class);}
    private void seed(String id, String date, String scheduled, String status) {
        jdbc.update("""
            INSERT INTO briefing_rounds(id,round_date,edition,scheduled_at,window_to,open_start,status)
            VALUES(?,?,'morning',?,?,true,?)
            """, id, LocalDate.parse(date), Timestamp.from(Instant.parse(scheduled)), Timestamp.from(Instant.parse(scheduled)), status);
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
