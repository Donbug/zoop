package com.zoop.admin.briefings;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import com.zoop.admin.auth.provision.AdminProvisioningService;
import com.zoop.admin.auth.service.AdminPrincipal;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;
import java.util.List;
import java.util.ArrayList;
import java.util.concurrent.Callable;
import java.util.concurrent.Executors;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;

/** Committed, isolated fixture verifies cross-connection races and transaction rollback (no enclosing test transaction). */
@SpringBootTest(properties = {
    "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test", "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    "ZOOP_AUTH_ALLOWED_ORIGINS=https://zoop.example"
})
@EnabledIfEnvironmentVariable(named="DB_URL", matches="jdbc:postgresql:.*")
@Tag("auth-postgres")
class AdminBriefingChangeConcurrencyTest {
    @Autowired JdbcTemplate jdbc;
    @Autowired AdminProvisioningService provisioning;
    @Autowired AdminBriefingChangeService service;
    private String adminId;

    @Test void committedRacesAndAuditFailurePreserveOneHistoryAndOriginal() throws Exception {
        String suffix=UUID.randomUUID().toString(), email="concurrency-"+suffix+"@example.com";
        adminId=provisioning.provision(email,"Concurrency Test","Secure admin password 2026",suffix);
        AdminPrincipal admin=new AdminPrincipal(adminId,email,"Concurrency Test","admin","synthetic-session");
        String id="concurrency-"+suffix;
        LocalDate date=LocalDate.of(1900,1,1);
        while(Boolean.TRUE.equals(jdbc.queryForObject("SELECT EXISTS(SELECT 1 FROM briefing_rounds WHERE round_date=? AND edition='morning')",Boolean.class,date)))date=date.plusDays(1);
        seed(id,date.toString(),date+"T00:20:00Z","scheduled");
        publishEmpty(id);
        String original=jdbc.queryForObject("SELECT published_payload::text||public_snapshot::text||payload_sha256 FROM briefing_rounds WHERE id=?",String.class,id);
        var correction=new AdminBriefingChangeController.Correction(null,"동시 요청 정정","표현 확인");
        try(var pool=Executors.newFixedThreadPool(4)) {
            List<Callable<Long>> same=new ArrayList<>();
            for(int i=0;i<4;i++)same.add(()->service.correct(id,correction,"same-key",admin,UUID.randomUUID().toString()).path("id").asLong());
            var results=pool.invokeAll(same);
            long first=results.getFirst().get();
            for(var result:results)assertThat(result.get()).isEqualTo(first);
            List<Callable<Long>> distinct=new ArrayList<>();
            for(int i=0;i<4;i++){int n=i;distinct.add(()->service.correct(id,correction,"distinct-"+n,admin,UUID.randomUUID().toString()).path("id").asLong());}
            for(var result:pool.invokeAll(distinct))assertThat(result.get()).isPositive();
            assertThat(jdbc.queryForList("SELECT seq FROM briefing_changes WHERE round_id=? AND kind='correction' ORDER BY seq",Integer.class,id)).containsExactly(1,2,3,4,5);
            List<Callable<String>> states=new ArrayList<>();
            for(int i=0;i<4;i++){int n=i;states.add(()->service.suspend(id,new AdminBriefingChangeController.Suspension("suspend","확인 중"),"suspend-"+n,admin,suffix).path("status").asText());}
            for(var result:pool.invokeAll(states))assertThat(result.get()).isEqualTo("suspended");
        }
        assertThat(jdbc.queryForObject("SELECT count(*) FROM briefing_changes WHERE round_id=? AND kind='suspension'",Long.class,id)).isEqualTo(1L);
        service.suspend(id,new AdminBriefingChangeController.Suspension("resume","확인 완료"),"resume",admin,suffix);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM audit_logs WHERE target_id=? AND action LIKE 'briefing.%'",Long.class,id)).isEqualTo(7L);
        long before=jdbc.queryForObject("SELECT count(*) FROM briefing_changes WHERE round_id=?",Long.class,id);
        jdbc.execute("CREATE OR REPLACE FUNCTION admin202_fail_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.target_id='"+id+"' AND NEW.action='briefing.suspend' THEN RAISE EXCEPTION 'synthetic audit failure'; END IF; RETURN NEW; END $$");
        jdbc.execute("CREATE TRIGGER admin202_fail_audit BEFORE INSERT ON audit_logs FOR EACH ROW EXECUTE FUNCTION admin202_fail_audit()");
        try {
            assertThatThrownBy(()->service.suspend(id,new AdminBriefingChangeController.Suspension("suspend","재확인"),"audit-failure",admin,suffix)).isInstanceOf(DataAccessException.class);
            assertThat(jdbc.queryForObject("SELECT status FROM briefing_rounds WHERE id=?",String.class,id)).isEqualTo("published");
            assertThat(jdbc.queryForObject("SELECT count(*) FROM briefing_changes WHERE round_id=?",Long.class,id)).isEqualTo(before);
            assertThat(jdbc.queryForObject("SELECT count(*) FROM idempotency_records WHERE principal_id=? AND idem_key='audit-failure'",Long.class,adminId)).isZero();
        } finally {
            jdbc.execute("DROP TRIGGER admin202_fail_audit ON audit_logs");
            jdbc.execute("DROP FUNCTION admin202_fail_audit()");
        }
        assertThat(jdbc.queryForObject("SELECT published_payload::text||public_snapshot::text||payload_sha256 FROM briefing_rounds WHERE id=?",String.class,id)).isEqualTo(original);
    }
    private void seed(String id, String date, String scheduled, String status) {
        jdbc.update("""
            INSERT INTO briefing_rounds(id,round_date,edition,scheduled_at,window_to,open_start,status)
            VALUES(?,?,'morning',?,?,true,?)
            """, id, LocalDate.parse(date), Timestamp.from(Instant.parse(scheduled)), Timestamp.from(Instant.parse(scheduled)), status);
    }
    private void publishEmpty(String id) {
        jdbc.update("INSERT INTO artifacts(id,kind,storage_uri,sha256,bytes,media_type,created_at) VALUES(?,'extracted_text',?,?,0,'text/plain',now())", id+"-artifact", "file:///synthetic/"+id, "a".repeat(64));
        jdbc.update("INSERT INTO articles(id,kind,provider,provider_key,lineage_key,access_status,created_at) VALUES(?,'news','synthetic',?,?,'available',now())", id+"-article",id,id);
        jdbc.update("INSERT INTO article_versions(article_id,version,title,publication_precision,text_artifact_id,collected_at) VALUES(?,'v1','Synthetic fixture','unknown',?,now())",id+"-article",id+"-artifact");
        jdbc.update("""
            WITH data AS (SELECT id,jsonb_build_object('id',id,'date',round_date,'edition',edition,
                'scheduledAt',scheduled_at,'generatedAt',scheduled_at,'dataWindow',jsonb_build_object('start',null,'end',window_to,'openStart',true),
                'graphVersion',null,'reviewRevision',1,'ruleRevision',null,'items','[]'::jsonb,
                'references',jsonb_build_object('eventIds','[]'::jsonb,'companyIds','[]'::jsonb,'evidenceIds','[]'::jsonb),
                'emptyReason','no_issues_in_window','selectedFrom',0,'marketVariables',null,'metadata','{}'::jsonb,'outlook',null) p
                FROM briefing_rounds WHERE id=?)
            UPDATE briefing_rounds r SET status='published',generated_at=scheduled_at,published_at=scheduled_at,
                review_revision=1,published_payload=data.p,public_snapshot=jsonb_build_object('marketSummary',null,'sourceBindings',jsonb_build_array(jsonb_build_object('documentId',r.id||'-article','documentVersion','v1','grantId','synthetic','grantRevision','v1','recipients',jsonb_build_array('admin-test')))),
                schema_version='admin-test-v1',payload_sha256=encode(sha256(convert_to(data.p::text,'UTF8')),'hex')
            FROM data WHERE r.id=data.id
            """, id);
    }
}
