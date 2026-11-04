package com.zoop.briefing.integration;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.DriverManager;
import java.util.UUID;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import tools.jackson.databind.json.JsonMapper;
import static org.junit.jupiter.api.Assertions.*;

/** Real private records stay unpublished. This test owns a fresh, loopback-only schema. */
@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT,properties={
    "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test", "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    "zoop.graph.snapshot.source=none", "zoop.briefing.personal-demo-enabled=false"
})
@EnabledIfEnvironmentVariable(named="BRIEFING_STAGING_SQL",matches=".+")
@Tag("briefing-postgres")
@DirtiesContext(classMode=DirtiesContext.ClassMode.AFTER_CLASS)
class PreparedServerBundlePostgresTest {
    private static final String SCHEMA="prep258_"+UUID.randomUUID().toString().replace("-","");
    private static final String OWNER="prep258-local-validation-owner";
    @Autowired JdbcTemplate jdbc;
    @LocalServerPort int port;
    private final JsonMapper json=JsonMapper.builder().build();

    private static String url() {
        String base=System.getenv("DB_URL");
        if(base==null || !base.matches("jdbc:postgresql://127\\.0\\.0\\.1:[0-9]+/zoop_briefing_replay_258_test"))
            throw new IllegalArgumentException("only the task-owned disposable loopback DB is allowed");
        return base+"?currentSchema="+SCHEMA;
    }
    private static String user(){return System.getenv().getOrDefault("DB_USERNAME","briefing_test");}
    private static String password(){return System.getenv().getOrDefault("DB_PASSWORD","");}
    @DynamicPropertySource static void database(DynamicPropertyRegistry p) {
        p.add("spring.datasource.url",PreparedServerBundlePostgresTest::url);
        p.add("spring.flyway.schemas",()->SCHEMA);p.add("spring.flyway.default-schema",()->SCHEMA);
        p.add("spring.jpa.properties.hibernate.default_schema",()->SCHEMA);
    }
    @AfterAll static void dropOnlyOwnedSchema() throws Exception {
        try(var c=DriverManager.getConnection(url(),user(),password());var s=c.createStatement()){
            s.execute("DROP SCHEMA "+SCHEMA+" CASCADE");
        }
    }
    private void executePlan(String sql) throws Exception {
        try(var c=DriverManager.getConnection(url(),user(),password());var s=c.createStatement()) {
            try{s.execute(sql);}catch(Exception error){s.execute("ROLLBACK");throw error;}
        }
    }
    private String snapshot(String table) {
        return jdbc.queryForObject("SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY id)::text,'[]') FROM "+table+" t",String.class);
    }
    @Test void stagesActualRecordsIdempotentlyWithoutPublishingOrChangingPriorFeedback() throws Exception {
        jdbc.update("""
            INSERT INTO members(id,analytics_key,email,email_key,display_name,signup_method,status,created_at,
                mode,completed,tutorial_completed,settings_version,updated_at)
            VALUES (?,?,'prep258@example.invalid','prep258@example.invalid','Local staging contract','google','active',now(),
                'watchlist',true,true,1,now())
            """,OWNER,OWNER);
        jdbc.update("""
            INSERT INTO briefing_rounds(id,round_date,edition,scheduled_at,window_to,open_start,status)
            VALUES ('prep258-existing','2099-01-01','morning','2099-01-01T00:20Z','2099-01-01T00:20Z',true,'scheduled')
            """);
        jdbc.update("""
            INSERT INTO briefing_feedback(id,member_id,feature,target_id,target_version,round_id,value,created_at,updated_at)
            VALUES ('prep258-feedback',?,'briefing_round','prep258-existing','saved-version','prep258-existing','up',now(),now())
            """,OWNER);
        String feedback=snapshot("briefing_feedback");
        String existing=jdbc.queryForObject("SELECT to_jsonb(t)::text FROM briefing_rounds t WHERE id='prep258-existing'",String.class);
        String plan=Files.readString(Path.of(System.getenv("BRIEFING_STAGING_SQL")));
        executePlan(plan);
        assertEquals(12,jdbc.queryForObject("SELECT count(*) FROM briefing_rounds WHERE id<>'prep258-existing'",Integer.class));
        assertEquals(12,jdbc.queryForObject("SELECT count(*) FROM briefing_personal_deliveries",Integer.class));
        assertEquals(12,jdbc.queryForObject("SELECT count(*) FROM briefing_personal_pools",Integer.class));
        assertEquals(60,jdbc.queryForObject("SELECT count(*) FROM evidence",Integer.class));
        assertEquals(17,jdbc.queryForObject("SELECT count(*) FROM articles WHERE access_status='private'",Integer.class));
        Path bundle=Path.of(System.getenv("BRIEFING_SERVER_BUNDLE"));
        var store=com.zoop.artifact.storage.ArtifactFileStore.at(bundle.toRealPath());
        for(String line:Files.readAllLines(bundle.resolve("tables/artifacts.jsonl"))) {
            var source=json.readTree(line);
            var artifact=jdbc.queryForMap("SELECT storage_uri,sha256,bytes FROM artifacts WHERE id=?",source.path("id").asString());
            assertEquals(source.path("bytes").asLong(),store.readVerified((String)artifact.get("storage_uri"),
                (String)artifact.get("sha256"),((Number)artifact.get("bytes")).longValue()).length);
        }
        for(String line:Files.readAllLines(bundle.resolve("source-observations.jsonl"))) {
            var source=json.readTree(line);
            var version=jdbc.queryForMap("SELECT version,collected_at FROM article_versions WHERE article_id=?",source.path("documentId").asString());
            assertEquals(source.path("originalObservation").path("documentVersion").asString(),version.get("version"));
            assertEquals(java.time.Instant.parse(source.path("collectedAt").asString()),((java.sql.Timestamp)version.get("collected_at")).toInstant());
            assertEquals(source.path("originalObservation").path("sourceId").asString(),
                jdbc.queryForObject("SELECT provider FROM articles WHERE id=?",String.class,source.path("documentId").asString()));
        }
        for(String line:Files.readAllLines(bundle.resolve("tables/briefing_rounds.jsonl"))) {
            var source=json.readTree(line);
            var stored=json.readTree(jdbc.queryForObject("SELECT public_snapshot::text FROM briefing_rounds WHERE id=?",String.class,source.path("id").asString()));
            assertEquals(source.path("public_snapshot").path("commonPriority"),stored.path("commonPriority"));
            assertEquals(source.path("public_snapshot").path("prioritySummary"),stored.path("prioritySummary"));
            assertEquals(source.path("public_snapshot").path("priorityContext"),stored.path("priorityContext"));
        }
        for(String line:Files.readAllLines(bundle.resolve("tables/briefing_personal_deliveries.jsonl"))) {
            var source=json.readTree(line);
            var stored=json.readTree(jdbc.queryForObject("SELECT result_snapshot::text FROM briefing_personal_deliveries WHERE round_id=?",String.class,source.path("round_id").asString()));
            assertEquals(source.path("result_snapshot").path("presentation"),stored.path("presentation"));
        }
        for(String table:new String[]{"briefing_rounds","briefing_personal_deliveries","briefing_personal_preferences","briefing_personal_pools"}){
            String before=snapshot(table);executePlan(plan);assertEquals(before,snapshot(table),table);
        }
        String preflight=System.getenv("BRIEFING_BINDINGS_PREFLIGHT");
        if(preflight!=null && !preflight.isBlank()) {
            String readOnly=Files.readString(Path.of(preflight));
            assertTrue(readOnly.contains("BEGIN READ ONLY;"));
            assertTrue(readOnly.stripTrailing().endsWith("ROLLBACK;"));
            String preferences=snapshot("briefing_personal_preferences");
            String deliveries=snapshot("briefing_personal_deliveries");
            executePlan(readOnly);
            assertEquals(preferences,snapshot("briefing_personal_preferences"));
            assertEquals(deliveries,snapshot("briefing_personal_deliveries"));
        }
        assertEquals(feedback,snapshot("briefing_feedback"));
        assertEquals(existing,jdbc.queryForObject("SELECT to_jsonb(t)::text FROM briefing_rounds t WHERE id='prep258-existing'",String.class));
        assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM briefing_rounds WHERE published_at IS NOT NULL",Integer.class));
        assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM briefing_rounds WHERE payload_sha256 IS NOT NULL AND payload_sha256<>encode(sha256(convert_to(published_payload::text,'UTF8')),'hex')",Integer.class));
        assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM briefing_personal_deliveries WHERE result_sha256<>encode(sha256(convert_to(result_snapshot::text,'UTF8')),'hex')",Integer.class));
        assertThrows(DataAccessException.class,()->jdbc.update("UPDATE briefing_personal_deliveries SET status='withheld'"));
        assertThrows(DataAccessException.class,()->jdbc.update("UPDATE briefing_personal_preferences SET choice='{}'::jsonb"));
        String changed=plan.replace("artifact-root:artifacts/","artifact-root:different_artifacts/");
        changed=changed.replace("BEGIN;","BEGIN; INSERT INTO companies(id,name,ticker,exchange_code,name_key,search_text) VALUES ('prep258-rollback','rollback','ROLLBACK','NASDAQ','','');");
        String rejected=changed;
        assertThrows(Exception.class,()->executePlan(rejected));
        assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM companies WHERE id='prep258-rollback'",Integer.class));
        assertEquals(feedback,snapshot("briefing_feedback"));
        var client=HttpClient.newHttpClient();
        for(String slot:new String[]{"2026-10-28&edition=morning","2026-11-02&edition=evening"}) {
            var response=client.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+"/api/v1/briefings?date="+slot)).GET().build(),HttpResponse.BodyHandlers.ofString());
            assertEquals(200,response.statusCode());
            assertEquals("not_ready",json.readTree(response.body()).path("status").asString());
            assertFalse(response.body().contains("aiAnalyses"));
        }
        var pool=json.readTree(Files.readAllLines(Path.of(System.getenv("BRIEFING_SERVER_BUNDLE")).resolve("tables/briefing_personal_pools.jsonl")).getFirst());
        String rid=pool.path("round_id").asString();
        var guest=client.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+"/api/v1/briefings/"+rid+"/personalized/delivery?demo=true")).GET().build(),HttpResponse.BodyHandlers.ofString());
        assertEquals(401,guest.statusCode());
        assertFalse(guest.body().contains("personalPriority"));
    }
}
