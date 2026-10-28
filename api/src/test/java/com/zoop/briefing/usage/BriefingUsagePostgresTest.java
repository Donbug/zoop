package com.zoop.briefing.usage;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.DriverManager;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.Executors;
import java.util.concurrent.CyclicBarrier;

import com.zoop.common.json.StrictJson;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.node.ObjectNode;

import static org.junit.jupiter.api.Assertions.*;

/** Real isolated PostgreSQL and actual Python producer -> JSONL Java command -> JDBC. All provider replies are authored. */
@Tag("briefing-postgres")
@EnabledIfEnvironmentVariable(named="DB_URL",matches="jdbc:postgresql:.*")
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class BriefingUsagePostgresTest {
    private final String schema="brf_usage_"+UUID.randomUUID().toString().replace("-","");
    private JdbcTemplate jdbc;
    private DriverManagerDataSource source;
    private BriefingUsageLedger ledger;
    private Path root;
    private String url;
    @BeforeAll void setup() throws Exception {
        String original=System.getenv("DB_URL");
        url=original+(original.contains("?")?"&":"?")+"currentSchema="+schema+",public";
        source=new DriverManagerDataSource(url,System.getenv().getOrDefault("DB_USERNAME","briefing_usage_test"),System.getenv().getOrDefault("DB_PASSWORD",""));
        // Extensions are shared test prerequisites, never owned/deleted by our disposable schema.
        var prerequisites=new JdbcTemplate(source);
        prerequisites.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public");
        prerequisites.execute("CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public");
        Flyway.configure().dataSource(source).schemas(schema).defaultSchema(schema).load().migrate();
        jdbc=new JdbcTemplate(source);root=Files.createTempDirectory("brf-usage-artifacts-").toRealPath();
        Files.setPosixFilePermissions(root,java.nio.file.attribute.PosixFilePermissions.fromString("rwx------"));
        ledger=new BriefingUsageLedger(new NamedParameterJdbcTemplate(source),new DataSourceTransactionManager(source),root,Duration.ofSeconds(120));
    }
    @BeforeEach void clean() {jdbc.execute("TRUNCATE ai_executions,briefing_attempts,briefing_rounds RESTART IDENTITY CASCADE");}
    @AfterAll void destroy() throws Exception {
        if(jdbc!=null)jdbc.execute("DROP SCHEMA "+schema+" CASCADE");
        if(root!=null)try(var paths=Files.walk(root)){for(Path p:paths.sorted(java.util.Comparator.reverseOrder()).toList())Files.deleteIfExists(p);}
    }
    private ObjectNode call(ObjectNode c) {return ledger.execute(StrictJson.Obj.of(c));}
    private ObjectNode claim(String key,String purpose) {
        ObjectNode c=StrictJson.newObject().put("op","claim").put("requestKey",key).put("purpose",purpose).put("trigger","scheduler").putNull("adminId").putNull("inputArtifactId");
        c.set("round",round());c.put("inputDigest","a".repeat(64));return c;
    }
    private ObjectNode round() {return StrictJson.newObject().put("id","usage-round").put("date","2026-10-28").put("edition","morning")
        .put("scheduledAt","2026-10-28T00:20:00Z").putNull("windowFrom").put("windowTo","2026-10-28T00:20:00Z");}
    private ObjectNode owner(String op,ObjectNode a) {return StrictJson.newObject().put("op",op).put("attemptId",a.path("attemptId").stringValue()).put("ownerToken",a.path("ownerToken").stringValue());}
    private ObjectNode start(ObjectNode a,String id,String feature) {return owner("model_start",a).put("callId",id).put("stage",feature.equals("briefing")?"round_generation":"company_outlook_generation")
        .put("feature",feature).put("provider","openai").put("model","authored-model").put("promptVersion","authored-v1").putNull("retryUnit").put("reasoningEffort","low");}
    private ObjectNode receipt(ObjectNode a,String id,String status) {
        return owner("model_finish",a).put("callId",id).put("status",status).put("transmissionConfirmed",true)
            .put("inputTokens",12).put("outputTokens",5).put("finishedAt",Instant.now().toString()).putNull("errorCode")
            .put("responseSha256","a".repeat(64)).putNull("estimate").put("reportedModel","authored-reported-model");
    }
    private ObjectNode finish(ObjectNode a,String outcome) {return owner("finish",a).put("outcome",outcome).putNull("failureStage").putNull("failureReason");}
    private void expire(ObjectNode a) {
        new TransactionTemplate(new DataSourceTransactionManager(source)).execute(s->{
            jdbc.update("UPDATE briefing_attempts SET lease_until=clock_timestamp()-interval '1 second' WHERE id=?",a.path("attemptId").stringValue());
            jdbc.update("UPDATE briefing_rounds SET lease_until=(SELECT lease_until FROM briefing_attempts WHERE id=?) WHERE id='usage-round' AND status IN ('generating','verifying')",a.path("attemptId").stringValue());return null;});
    }
    @Test void claimIsIdempotentAndChangedCommandIsRejected() {
        ObjectNode command=claim("request-a","generation"),a=call(command),b=call(command);
        assertEquals(a.get("attemptId"),b.get("attemptId"));assertTrue(b.path("reused").booleanValue());
        assertEquals(1,jdbc.queryForObject("SELECT count(*) FROM briefing_attempts",Integer.class));
        assertThrows(BriefingUsageLedger.Rejected.class,()->call(claim("request-a","outlook")));
        assertThrows(BriefingUsageLedger.Rejected.class,()->call(command.deepCopy().put("inputDigest","b".repeat(64))));
    }
    @Test void simultaneousClaimsHaveOneWinner() throws Exception {
        var barrier=new CyclicBarrier(2);
        try(var pool=Executors.newFixedThreadPool(2)) {
            List<Callable<Boolean>> work=new ArrayList<>();
            for(int i=0;i<2;i++){String key="request-"+i;work.add(()->{barrier.await();try{call(claim(key,"generation"));return true;}catch(RuntimeException e){return false;}});}
            int wins=0;for(var f:pool.invokeAll(work))if(f.get())wins++;
            assertEquals(1,wins);assertEquals(1,jdbc.queryForObject("SELECT count(*) FROM briefing_attempts WHERE status='running'",Integer.class));
        }
    }
    @Test void expiryEndsOldAttemptAndFencesOldWorkerButKeepsItsExpense() {
        ObjectNode a=call(claim("old","generation"));call(start(a,"sent-before-crash","briefing"));expire(a);
        ObjectNode b=call(claim("new","generation"));assertEquals(2,b.path("attemptNo").intValue());
        assertEquals("failed",jdbc.queryForObject("SELECT status FROM briefing_attempts WHERE attempt_no=1",String.class));
        assertEquals("round_generation",jdbc.queryForObject("SELECT stages->>'failureStage' FROM briefing_attempts WHERE attempt_no=1",String.class));
        assertEquals("lease_expired",jdbc.queryForObject("SELECT failure_reason FROM briefing_attempts WHERE attempt_no=1",String.class));
        assertEquals("unknown",jdbc.queryForObject("SELECT status FROM ai_executions",String.class));
        assertThrows(BriefingUsageLedger.Rejected.class,()->call(owner("heartbeat",a)));
        assertThrows(BriefingUsageLedger.Rejected.class,()->ledger.publish(a.path("attemptId").stringValue(),a.path("ownerToken").stringValue(),()->{fail("stale publisher called");return null;}));
        call(receipt(a,"sent-before-crash","succeeded"));
        assertEquals(1,jdbc.queryForObject("SELECT count(*) FROM ai_executions",Integer.class));
        assertEquals("succeeded",jdbc.queryForObject("SELECT status FROM ai_executions",String.class));
        call(start(b,"new-send","briefing"));assertNotNull(jdbc.queryForObject("SELECT retry_unit_id FROM ai_executions WHERE ai_attempt_id='new-send'",String.class));
    }
    @Test void callStartsBeforeResponseAndPartialUsageRemainsNullable() {
        ObjectNode a=call(claim("request","generation"));call(start(a,"call-a","briefing"));
        assertNull(jdbc.queryForMap("SELECT input_tokens,actual_cost,transmission_confirmed FROM ai_executions").get("input_tokens"));
        assertEquals("running",jdbc.queryForObject("SELECT status FROM ai_executions",String.class));
        ObjectNode r=receipt(a,"call-a","failed").putNull("outputTokens").put("errorCode","provider_failed");call(r);
        Map<String,Object> row=jdbc.queryForMap("SELECT * FROM ai_executions");
        assertEquals(12L,row.get("input_tokens"));assertNull(row.get("output_tokens"));assertNull(row.get("actual_cost"));assertNull(row.get("error_message"));
        assertEquals("authored-reported-model",row.get("model"));
        assertEquals("failed",jdbc.queryForObject("SELECT stages->'round_generation'->>'status' FROM briefing_attempts",String.class));
    }
    @Test void receiptIngestionIsIdempotentAndDifferentBytesCannotReplaceIt() {
        ObjectNode a=call(claim("request","generation"));call(start(a,"call-a","briefing"));ObjectNode r=receipt(a,"call-a","succeeded");
        call(r);assertTrue(call(r).path("reused").booleanValue());
        assertEquals(1,jdbc.queryForObject("SELECT count(*) FROM ai_executions",Integer.class));
        assertThrows(BriefingUsageLedger.Rejected.class,()->call(r.deepCopy().put("inputTokens",999)));
        assertEquals(1,jdbc.queryForObject("SELECT count(*) FROM artifacts WHERE id LIKE 'brf-usage-%'",Integer.class));
        assertThrows(DataAccessException.class,()->jdbc.update("UPDATE ai_executions SET input_tokens=999"));
    }
    @Test void unresolvedTransmissionIsNotZeroOrFailureAndCanBeReconciledWithoutNewCall() {
        ObjectNode a=call(claim("request","generation"));call(start(a,"call-a","briefing"));
        ObjectNode unknown=receipt(a,"call-a","unknown").putNull("transmissionConfirmed").putNull("inputTokens").putNull("outputTokens").putNull("responseSha256").putNull("reportedModel").put("errorCode","transport_unknown");
        call(unknown);assertNull(jdbc.queryForMap("SELECT transmission_confirmed FROM ai_executions").get("transmission_confirmed"));
        assertThrows(BriefingUsageLedger.Rejected.class,()->call(finish(a,"available")));
        call(receipt(a,"call-a","succeeded"));call(finish(a,"available"));
        assertEquals(1,jdbc.queryForObject("SELECT count(*) FROM ai_executions",Integer.class));
        assertEquals(12L,jdbc.queryForObject("SELECT input_tokens FROM ai_executions",Long.class));
    }
    @Test void replayAndSaveOnlyAreLocalRecordsWithNoTokensCostOrRetryUnits() {
        ObjectNode a=call(claim("request","generation"));
        for(String mode:List.of("replay","save_only"))call(owner("local",a).put("eventId",mode).put("stage","result_save").put("feature","briefing").put("mode",mode));
        assertEquals(2,jdbc.queryForObject("SELECT count(*) FROM ai_executions",Integer.class));
        assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM ai_executions WHERE execution_mode='live'",Integer.class));
        assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM ai_executions WHERE input_tokens IS NOT NULL OR retry_unit_id IS NOT NULL OR ai_attempt_id IS NOT NULL",Integer.class));
        call(finish(a,"available"));
        ObjectNode b=call(claim("first-live-after-only-local","generation"));call(start(b,"first-live","briefing"));
        assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM ai_executions WHERE retry_unit_id IS NOT NULL",Integer.class));
    }
    @Test void repairGenerationAndVerificationShareOneRetryUnit() {
        ObjectNode a=call(claim("request","outlook"));
        call(start(a,"repair-generation","briefing-outlook").put("retryUnit","repair-1"));
        call(start(a,"repair-verification","briefing-outlook").put("stage","company_outlook_verification").put("retryUnit","repair-1"));
        assertEquals(1,jdbc.queryForObject("SELECT count(DISTINCT retry_unit_id) FROM ai_executions",Integer.class));
        assertEquals(2,jdbc.queryForObject("SELECT count(*) FROM ai_executions WHERE feature='briefing-outlook'",Integer.class));
    }
    @Test void withholdingDoesNotTurnSuccessfulModelCallIntoModelFailure() {
        ObjectNode a=call(claim("request","outlook"));call(start(a,"call-a","briefing-outlook"));call(receipt(a,"call-a","succeeded"));
        call(finish(a,"withheld").put("failureStage","verification").put("failureReason","quality_withheld"));
        assertEquals("completed",jdbc.queryForObject("SELECT status FROM briefing_attempts",String.class));
        assertEquals("withheld",jdbc.queryForObject("SELECT stages->>'outcome' FROM briefing_attempts",String.class));
        assertEquals("succeeded",jdbc.queryForObject("SELECT status FROM ai_executions",String.class));
        assertThrows(DataAccessException.class,()->jdbc.update("UPDATE briefing_attempts SET failure_reason='changed'"));
    }
    @Test void estimatesHaveExplicitCurrencyBasisAndNeverBecomeActualBills() {
        ObjectNode a=call(claim("request","generation"));call(start(a,"call-a","briefing"));ObjectNode r=receipt(a,"call-a","succeeded");
        r.set("estimate",StrictJson.newObject().put("currency","USD").put("priceVersion","authored-rate-v1").put("inputPerMillion",1).put("outputPerMillion",2));call(r);
        assertEquals(new java.math.BigDecimal("0.000022"),jdbc.queryForObject("SELECT estimated_cost FROM ai_executions",java.math.BigDecimal.class));
        assertNull(jdbc.queryForMap("SELECT actual_cost FROM ai_executions").get("actual_cost"));
        assertEquals("USD",jdbc.queryForObject("SELECT currency FROM ai_executions",String.class));
        assertThrows(RuntimeException.class,()->call(r.deepCopy().put("responseBody","must-never-be-copied")));
        String content=FilesString(jdbc.queryForObject("SELECT storage_uri FROM artifacts WHERE id=(SELECT receipt_artifact_id FROM ai_executions)",String.class));
        assertFalse(content.contains("responseBody"));assertFalse(content.contains("instructions"));
    }
    private String FilesString(String uri) {try{return Files.readString(root.resolve(uri.substring("artifact-root:".length())));}catch(Exception e){throw new AssertionError(e);}}
    @Test void ownerAndFeatureReferencesAreEnforced() {
        ObjectNode a=call(claim("request","outlook"));
        assertThrows(BriefingUsageLedger.Rejected.class,()->call(start(a,"call-a","briefing")));
        assertThrows(BriefingUsageLedger.Rejected.class,()->call(owner("heartbeat",a).put("ownerToken","wrong")));
        assertThrows(DataAccessException.class,()->jdbc.update("INSERT INTO ai_executions(id,feature,execution_mode,status,briefing_attempt_id,started_at) VALUES('bad','briefing','live','running','absent',now())"));
    }
    @Test void publishedRoundAllowsAnOutlookAttemptWithoutChangingItsImmutableSnapshot() {
        ObjectNode a=call(claim("generation","generation"));
        ledger.publish(a.path("attemptId").stringValue(),a.path("ownerToken").stringValue(),()->publishEmpty());
        String before=jdbc.queryForObject("SELECT published_payload::text FROM briefing_rounds",String.class);
        ObjectNode b=call(claim("outlook","outlook"));call(start(b,"call-a","briefing-outlook"));call(receipt(b,"call-a","succeeded"));call(finish(b,"available"));
        assertEquals(before,jdbc.queryForObject("SELECT published_payload::text FROM briefing_rounds",String.class));
        assertEquals("published",jdbc.queryForObject("SELECT status FROM briefing_rounds",String.class));
        assertThrows(BriefingUsageLedger.Rejected.class,()->call(claim("regenerate","generation")));
    }
    @Test void publicationRequiresCurrentOwnerAndRollsBackWithItsCompletion() {
        ObjectNode a=call(claim("generation","generation"));
        assertThrows(DataAccessException.class,this::publishEmpty);
        assertThrows(IllegalStateException.class,()->ledger.publish(a.path("attemptId").stringValue(),a.path("ownerToken").stringValue(),()->{publishEmpty();throw new IllegalStateException("authored publisher crash");}));
        assertEquals("running",jdbc.queryForObject("SELECT status FROM briefing_attempts",String.class));
        assertNull(jdbc.queryForMap("SELECT published_at FROM briefing_rounds").get("published_at"));
        ledger.publish(a.path("attemptId").stringValue(),a.path("ownerToken").stringValue(),this::publishEmpty);
        assertEquals("completed",jdbc.queryForObject("SELECT status FROM briefing_attempts",String.class));
        assertNull(jdbc.queryForMap("SELECT generation_token FROM briefing_rounds").get("generation_token"));
        assertEquals("available",jdbc.queryForObject("SELECT stages->>'outcome' FROM briefing_attempts",String.class));
    }
    @Test void firstOutlookAfterGenerationIsNotARetryAndDuplicateStartCannotDispatch() {
        ObjectNode a=call(claim("generation","generation"));call(finish(a,"available"));
        ObjectNode b=call(claim("first-outlook","outlook"));
        assertTrue(call(start(b,"call-a","briefing-outlook")).path("created").booleanValue());
        assertFalse(call(start(b,"call-a","briefing-outlook")).path("created").booleanValue());
        assertNull(jdbc.queryForMap("SELECT retry_unit_id FROM ai_executions").get("retry_unit_id"));
    }
    @Test void clockSkewDoesNotInventZeroDurationAndDailyGroupingUsesTheStartInKst() {
        ObjectNode a=call(claim("generation","generation"));call(start(a,"call-a","briefing"));
        Instant started=jdbc.queryForObject("SELECT started_at FROM ai_executions",java.sql.Timestamp.class).toInstant();
        call(receipt(a,"call-a","succeeded").put("finishedAt",started.minusSeconds(1).toString()));
        assertNull(jdbc.queryForMap("SELECT finished_at FROM ai_executions").get("finished_at"));
        call(start(a,"kst-call","briefing"));
        jdbc.update("UPDATE ai_executions SET started_at='2026-10-27T14:59:59Z' WHERE ai_attempt_id='kst-call'");
        call(receipt(a,"kst-call","succeeded").put("finishedAt","2026-10-27T15:00:02Z"));
        assertEquals("2026-10-27",jdbc.queryForObject("SELECT (started_at AT TIME ZONE 'Asia/Seoul')::date::text FROM ai_executions WHERE ai_attempt_id='kst-call'",String.class));
    }
    private int publishEmpty() {
        jdbc.update("INSERT INTO artifacts(id,kind,storage_uri,sha256,bytes,media_type,created_at) VALUES('usage-text','extracted_text','artifact-root:authored/usage.txt',?,0,'text/plain',now()) ON CONFLICT DO NOTHING","a".repeat(64));
        jdbc.update("INSERT INTO articles(id,kind,provider,access_status,created_at) VALUES('usage-document','news','authored','available',now()) ON CONFLICT DO NOTHING");
        jdbc.update("INSERT INTO article_versions(article_id,version,publication_precision,text_artifact_id,collected_at) VALUES('usage-document','v1','unknown','usage-text',now()) ON CONFLICT DO NOTHING");
        ObjectNode p=StrictJson.newObject().put("id","usage-round").put("date","2026-10-28").put("edition","morning")
            .put("scheduledAt","2026-10-28T00:20:00Z").put("generatedAt","2026-10-28T00:20:00Z").putNull("graphVersion")
            .put("reviewRevision",0).putNull("ruleRevision").put("emptyReason","no_issues_in_window").put("selectedFrom",0).putNull("marketVariables").putNull("outlook");
        p.putObject("dataWindow").putNull("start").put("end","2026-10-28T00:20:00Z").put("openStart",true);
        p.putObject("references").putArray("eventIds");((ObjectNode)p.get("references")).putArray("evidenceIds");((ObjectNode)p.get("references")).putArray("companyIds");p.putObject("metadata");p.putArray("items");
        return jdbc.update("""
            UPDATE briefing_rounds SET status='published',review_revision=0,generation_token=NULL,lease_until=NULL,
                generated_at='2026-10-28T00:20:00Z',published_at='2026-10-28T00:20:01Z',schema_version='authored-test',
                public_snapshot='{"marketSummary":{"status":"unavailable","reason":"authored"},"sourceBindings":[{"documentId":"usage-document","documentVersion":"v1","grantId":"authored","grantRevision":"v1","recipients":["authored"]}]}'::jsonb,
                published_payload=?::jsonb,payload_sha256=encode(sha256(convert_to((?::jsonb)::text,'UTF8')),'hex') WHERE id='usage-round'
            """,p.toString(),p.toString());
    }
    @Test void actualPythonProducersAndJavaPipeRecordLiveReplaySaveOnlyFailuresAndRepairs() throws Exception {
        Path scripts=Path.of("../scripts/tests/fixtures/briefing_usage_smoke.py").toAbsolutePath().normalize();
        Path work=Files.createTempDirectory("briefing-usage-producer-");
        var process=new ProcessBuilder("python3",scripts.toString(),work.toString(),System.getProperty("zoop.briefing.usage.classpath"));
        process.environment().put("DB_URL",url);process.environment().put("DB_USERNAME",System.getenv().getOrDefault("DB_USERNAME","briefing_usage_test"));
        process.environment().put("DB_PASSWORD",System.getenv().getOrDefault("DB_PASSWORD",""));process.environment().put("BRIEFING_USAGE_ARTIFACT_ROOT",root.toString());
        process.environment().put("JAVA",Path.of(System.getProperty("java.home"),"bin/java").toString());
        Path log=work.resolve("smoke.log");process.redirectErrorStream(true).redirectOutput(log.toFile());var child=process.start();
        assertTrue(child.waitFor(120,java.util.concurrent.TimeUnit.SECONDS));assertEquals(0,child.exitValue(),Files.readString(log));
        assertEquals(5,jdbc.queryForObject("SELECT count(*) FROM briefing_attempts",Integer.class));
        assertEquals(7,jdbc.queryForObject("SELECT count(*) FROM ai_executions WHERE execution_mode='live'",Integer.class));
        assertEquals(4,jdbc.queryForObject("SELECT count(*) FROM ai_executions WHERE execution_mode='replay'",Integer.class));
        assertEquals(1,jdbc.queryForObject("SELECT count(DISTINCT retry_unit_id) FROM ai_executions WHERE execution_mode='live' AND retry_unit_id IS NOT NULL",Integer.class));
        assertEquals(1,jdbc.queryForObject("SELECT count(*) FROM ai_executions WHERE execution_mode='save_only'",Integer.class));
        assertEquals(1,jdbc.queryForObject("SELECT count(*) FROM ai_executions WHERE status='unknown'",Integer.class));
        assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM ai_executions WHERE actual_cost IS NOT NULL",Integer.class));
    }
}
