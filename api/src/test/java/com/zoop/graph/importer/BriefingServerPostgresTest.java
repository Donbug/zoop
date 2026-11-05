package com.zoop.graph.importer;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Base64;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.Canonical;
import com.zoop.document.analysis.repository.JdbcDocumentAnalysisRepository;
import com.zoop.document.evidence.service.DocumentReadSources;
import com.zoop.document.importer.IngestionExportParser;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.JdbcDocumentRegistryRepository;
import com.zoop.document.repository.VersionRow;
import com.zoop.graph.publication.GraphPublicationAuthority;
import com.zoop.graph.publication.GraphPublicationComposer;
import com.zoop.graph.publication.GraphPublicationPreparer;
import com.zoop.graph.publication.GraphPublicationReader;
import com.zoop.graph.publication.JdbcGraphPublicationRepository;
import com.zoop.graph.publication.PublicationComposeRequest;
import com.zoop.graph.publication.PublicationMerger;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.version.JdbcGraphVersionRepository;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.node.ObjectNode;
import static org.junit.jupiter.api.Assertions.*;

/** Native graph -> actual Python producer -> Java ledger -> fenced publication, with synthetic provider replies only. */
@Tag("graph-postgres")
class BriefingServerPostgresTest {
    private static final Instant NOW = Instant.parse("2026-11-02T01:02:03Z");
    private static final Clock CLOCK = Clock.fixed(NOW, ZoneOffset.UTC);
    @TempDir Path temp;
    private String schema;
    private JdbcTemplate jdbc;
    private JdbcDocumentRegistryRepository registry;
    private JdbcGraphHandoffRepository graph;
    private JdbcGraphVersionRepository versions;
    private JdbcGraphPublicationRepository publications;
    private TransactionTemplate transaction;
    private ArtifactFileStore files;
    private Path authority;
    private String url;
    private Path grant;
    private Path work;

    @BeforeEach void start(org.junit.jupiter.api.TestInfo info) throws Exception {
        boolean dayOnly=info.getTestMethod().orElseThrow().getName().startsWith("dayOnlySource");
        schema = "prepare_" + UUID.randomUUID().toString().replace("-", "");
        url = System.getenv("ZOOP_COMPANY_TEST_DB_URL");
        if (url == null || !url.matches("jdbc:postgresql://127\\.0\\.0\\.1:[0-9]+/zoop_company_test_19")) {
            throw new IllegalStateException("Set ZOOP_COMPANY_TEST_DB_URL to the dedicated localhost zoop_company_test_19 database");
        }
        url=url + "?currentSchema=" + schema + ",public";
        var dataSource = new DriverManagerDataSource(url, "company_test",
                password());
        jdbc = new JdbcTemplate(dataSource);
        jdbc.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public");
        jdbc.execute("CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public");
        Flyway.configure().dataSource(dataSource).schemas(schema).defaultSchema(schema).load().migrate();
        var named = new NamedParameterJdbcTemplate(jdbc);
        registry = new JdbcDocumentRegistryRepository(named);
        graph = new JdbcGraphHandoffRepository(named, new JdbcDocumentAnalysisRepository(named));
        versions = new JdbcGraphVersionRepository(named, CLOCK);
        publications = new JdbcGraphPublicationRepository(named);
        transaction = new TransactionTemplate(new DataSourceTransactionManager(dataSource));
        transaction.setTimeout(300);
        jdbc.update("INSERT INTO companies (id, name, name_key, search_text) VALUES (?, ?, '', ''), (?, ?, '', '')",
                HandoffFixtures.COMPANY_A, "합성기업", HandoffFixtures.COMPANY_B, "합성부품");
        files = ArtifactFileStore.at(Files.createDirectory(temp.toRealPath().resolve("producer")));
        authority = temp.toRealPath().resolve("authority.json");
        Files.writeString(authority, """
                {"schemaVersion":"zoop-ingestion-s2-1","revision":"registry-a","sources":[{
                  "sourceId":"synthetic-source","adapter":"authored-files","inputRoot":"/synthetic",
                  "allowedHosts":["example.invalid"],"scopes":[{"scopeId":"scope-a","selection":"all",
                    "initialCursor":null,"articleXPath":null,"timestampLimitations":["synthetic"]}],
                  "grant":{"grantId":"operator-grant","revision":"rights-1","sourceId":"synthetic-source","enabled":true,
                    "rights":"known","allowedOperations":["read","store","quote-display"],"recipients":[],
                    "purposes":[],"evidence":["synthetic operator grant"],"expiresAt":null}}]}
                """);
        byte[] text = HandoffFixtures.TEXT.getBytes(StandardCharsets.UTF_8);
        String textId = "text-" + HandoffFixtures.ARTICLE_VERSION;
        try (var session = files.open()) {
            var stored = session.put("extracted_text", textId + ".txt", text);
            transaction.executeWithoutResult(status -> {
                registry.insertArticleIfAbsent(HandoffFixtures.ARTICLE_ID, "news", HandoffFixtures.SOURCE, NOW);
                registry.insertArtifactIfAbsent(new ArtifactRow(textId, "extracted_text", stored.uri(), stored.sha256(), stored.bytes(), "text/plain; charset=utf-8", NOW));
                registry.insertVersionIfAbsent(new VersionRow(HandoffFixtures.ARTICLE_ID, HandoffFixtures.ARTICLE_VERSION, "합성 제목", null,
                        "https://example.invalid/a", dayOnly?null:Instant.parse("2026-10-08T00:00:00Z"), dayOnly?java.time.LocalDate.parse("2026-10-08"):null, dayOnly?"day":"datetime", null, textId,
                        info.getTestMethod().orElseThrow().getName().startsWith("recoverySourceObservedAfter") ? NOW.minusSeconds(30) : Instant.parse("2026-10-14T01:02:03.456789Z")));
            });
        }
    }

    @AfterEach void stop() {
        if (jdbc != null) jdbc.execute("DROP SCHEMA IF EXISTS " + schema + " CASCADE");
    }

    private static String password(){String value=System.getenv("ZOOP_COMPANY_TEST_DB_PASSWORD");return value==null||value.isBlank()?"synthetic-test-only":value;}
    private com.zoop.briefing.server.BriefingServerCommand server() throws Exception { return server(java.util.Map.of()); }
    private com.zoop.briefing.server.BriefingServerCommand server(java.util.Map<String,String> overrides) throws Exception {
        work=temp.toRealPath().resolve("work");Files.createDirectories(work);
        grant=temp.resolve("grants.json");
        if(!Files.exists(grant))Files.writeString(grant,"""
            {"schemaVersion":"zoop-ai-s1-1","grants":[{"grantId":"synthetic-briefing","revision":"v1","sourceId":"synthetic-source",
             "enabled":true,"rights":"known","allowedOperations":["read","store","quote-display","model-send"],
             "recipients":["openai"],"purposes":["briefing-outlook","semantic-verification"],"evidence":["synthetic operator authorization"],"expiresAt":null}]}
            """);
        Path scope=temp.toRealPath().resolve("model-scope.json");
        if(!Files.exists(scope))Files.writeString(scope,"{\"schemaVersion\":\"briefing-model-scope-v1\",\"authorizationRef\":\"synthetic\",\"sources\":[{\"sourceId\":\""+HandoffFixtures.SOURCE+"\",\"documentId\":\""+HandoffFixtures.ARTICLE_ID+"\",\"documentVersion\":\""+HandoffFixtures.ARTICLE_VERSION+"\",\"bodySha256\":\""+Canonical.sha256(HandoffFixtures.TEXT.getBytes(StandardCharsets.UTF_8))+"\"}]}");
        var env=new java.util.HashMap<>(java.util.Map.of(
            "DB_URL",url,"DB_USERNAME","company_test","DB_PASSWORD",password(),
            "BRIEFING_SERVER_WORK_ROOT",work.toString(),"BRIEFING_USAGE_ARTIFACT_ROOT",temp.toRealPath().resolve("producer").toString(),
            "BRIEFING_SERVER_SOURCE_SCOPE",scope.toString(),"ZOOP_DOCUMENT_READ_GRANTS",grant.toString(),"ZOOP_DOCUMENT_READ_INGESTION_SOURCES",authority.toString()));
        env.putAll(overrides);return new com.zoop.briefing.server.BriefingServerCommand(env);
    }
    private ObjectNode request(String edition) {
        var request=com.zoop.common.json.StrictJson.newObject();request.putObject("round")
            .put("id","brf-2026-11-02-"+edition).put("date","2026-11-02").put("edition",edition)
            .put("scheduledAt","2026-11-02T01:03:03Z").put("windowFrom","2026-10-07T00:00:00Z").put("windowTo","2026-11-02T01:03:03Z");return request;
    }
    private ObjectNode prepared() throws Exception {
        publish(importNative(HandoffFixtures.Spec.standard()));
        return server().prepare(com.zoop.common.json.StrictJson.Obj.of(request("morning")));
    }
    private ObjectNode failedRecoveryRequest() {
        var request=request("morning");var r=(ObjectNode)request.get("round");String cutoff=NOW.minusSeconds(120).toString();
        r.put("scheduledAt",cutoff).put("windowTo",cutoff);request.put("recordedRecovery",true);
        jdbc.update("INSERT INTO briefing_rounds(id,round_date,edition,scheduled_at,window_from,window_to,open_start,status) VALUES('brf-2026-11-02-morning','2026-11-02','morning',?::timestamptz,'2026-10-07T00:00:00Z',?::timestamptz,false,'failed')",cutoff,cutoff);
        jdbc.update("INSERT INTO briefing_common_schedule_jobs(id,round_date,edition,scheduled_at,window_from,status,finished_at) VALUES('brf-2026-11-02-morning','2026-11-02','morning',?::timestamptz,'2026-10-07T00:00:00Z','requires_recovery',now())",cutoff);
        jdbc.update("INSERT INTO briefing_attempts(id,round_id,attempt_no,request_key,purpose,trigger,owner_token,status,stages,started_at,finished_at,lease_until) VALUES('old-failed','brf-2026-11-02-morning',1,'old-request','generation','scheduler','old-owner','failed','{}',now(),now(),now())");
        return request;
    }
    private java.util.Map<String,String> recoveryEnvironment() {
        return java.util.Map.of("BRIEFING_RECORDED_RECOVERY_AUTHORIZATION","synthetic-explicit-recovery", "BRIEFING_RECORDED_RECOVERY_ROUND","brf-2026-11-02-morning");
    }
    @Test void recordedRecoveryRequiresExactOperatorBindingAndPreservesFailedHistory() throws Exception {
        publish(importNative(HandoffFixtures.Spec.standard()));var request=failedRecoveryRequest();
        assertThrows(IllegalStateException.class,()->server().prepare(com.zoop.common.json.StrictJson.Obj.of(request)));
        var result=server(recoveryEnvironment()).prepare(com.zoop.common.json.StrictJson.Obj.of(request));
        assertEquals("recorded-cutoff-recovery-v1",result.at("/recovery/kind").asString());
        assertEquals("failed",jdbc.queryForObject("SELECT status FROM briefing_attempts WHERE id='old-failed'",String.class));
        assertEquals(1,result.path("candidates").size());
        request.put("recordedRecovery",false);
        assertThrows(IllegalStateException.class,()->server(recoveryEnvironment()).prepare(com.zoop.common.json.StrictJson.Obj.of(request)));
    }
    @Test void recoverySourceObservedAfterCutoffCannotBeBackdatedByItsPublisherTime() throws Exception {
        publish(importNative(HandoffFixtures.Spec.standard()));var request=failedRecoveryRequest();
        assertThrows(IllegalStateException.class,()->server(recoveryEnvironment()).prepare(com.zoop.common.json.StrictJson.Obj.of(request)));
    }
    @Test void forgedQuoteCannotPassByRecomputingTheInputHash() throws Exception {
        ObjectNode input=prepared();var candidate=(ObjectNode)input.path("candidates").get(0);
        var source=(ObjectNode)candidate.path("sources").values().iterator().next();source.put("quote","forged synthetic quote");
        candidate.remove("snapshotSha256");candidate.put("snapshotSha256",Canonical.sha256(Canonical.appBytes(candidate)));
        input.remove("inputSha256");input.put("inputSha256",Canonical.sha256(Canonical.appBytes(input)));
        assertThrows(IllegalArgumentException.class,()->server().check(com.zoop.common.json.StrictJson.Obj.of(input)));
    }
    @Test void changedGrantStopsBeforeAnyModelExecution() throws Exception {
        ObjectNode input=prepared();Files.writeString(grant,Files.readString(grant).replace("\"enabled\":true","\"enabled\":false"));
        assertThrows(IllegalArgumentException.class,()->server().check(com.zoop.common.json.StrictJson.Obj.of(input)));
        assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM ai_executions",Integer.class));
    }
    @Test void sourceScopeRemovalStopsAnOtherwiseGrantedDocument() throws Exception {
        ObjectNode input=prepared();Files.writeString(temp.toRealPath().resolve("model-scope.json"),"{\"schemaVersion\":\"briefing-model-scope-v1\",\"authorizationRef\":\"synthetic\",\"sources\":[]}");
        assertThrows(IllegalArgumentException.class,()->server().check(com.zoop.common.json.StrictJson.Obj.of(input)));
        assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM ai_executions",Integer.class));
    }
    @Test void historicalGraphWithoutCurrentWindowEvidenceCannotBecomeNoNews() throws Exception {
        prepared();var r=request("morning");((ObjectNode)r.get("round")).put("windowFrom","2026-11-02T01:02:30Z");
        assertThrows(IllegalStateException.class,()->server().prepare(com.zoop.common.json.StrictJson.Obj.of(r)));
        assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM briefing_rounds",Integer.class));
    }
    @Test void actualProducerPublishesReadableMorningAndEveningWithRecordedCalls() throws Exception {
        publish(importNative(HandoffFixtures.Spec.standard()));server();
        for(String edition:List.of("morning","evening")) {
            runProducer(edition,"normal");
            var round=new com.zoop.briefing.storage.BriefingRoundRepository(jdbc).findById("brf-2026-11-02-"+edition).orElseThrow();
            assertEquals("published",round.status());com.zoop.briefing.query.BriefingSnapshotValidator.validate(round);
        }
        try(var app=new org.springframework.boot.builder.SpringApplicationBuilder(com.zoop.ZoopApplication.class).run(
            "--server.port=0","--spring.datasource.url="+url,"--spring.datasource.username=company_test","--spring.datasource.password="+password(),
            "--spring.flyway.enabled=false","--spring.jpa.properties.hibernate.default_schema="+schema,
            "--zoop.document-read.grants="+grant,"--zoop.document-read.artifact-root="+temp.toRealPath().resolve("producer"),
            "--zoop.document-read.ingestion-sources="+authority,"--zoop.graph.snapshot.source=artifact",
            "--zoop.graph.snapshot.artifact-root="+temp.toRealPath().resolve("producer"),
            "--ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test","--ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")) {
            int port=((org.springframework.boot.web.server.context.WebServerApplicationContext)app).getWebServer().getPort();
            var http=java.net.http.HttpClient.newHttpClient();
            var uri=java.net.URI.create("http://127.0.0.1:"+port+"/api/v1/briefings?date=2026-11-02&edition=morning");
            var response=http.send(java.net.http.HttpRequest.newBuilder(uri).GET().build(),java.net.http.HttpResponse.BodyHandlers.ofString());
            assertEquals(200,response.statusCode(),response.body());
            var dto=com.zoop.common.json.StrictJson.parseObject(response.body());assertEquals("published",dto.string("status"));assertEquals(1,dto.array("items").size());
            String event=dto.array("items").get(0).path("eventId").asString();
            var detailUri=java.net.URI.create("http://127.0.0.1:"+port+"/api/v1/briefings/brf-2026-11-02-morning/items/"+event);
            var detail=http.send(java.net.http.HttpRequest.newBuilder(detailUri).GET().build(),java.net.http.HttpResponse.BodyHandlers.ofString());
            assertEquals(200,detail.statusCode(),detail.body());
            var evidence=com.zoop.common.json.StrictJson.parseObject(detail.body()).array("evidence").get(0);
            assertEquals(jdbc.queryForObject("SELECT quote FROM evidence WHERE id=?",String.class,evidence.path("id").asString()),evidence.path("quote").asString());assertEquals("",evidence.path("publisher").asString());
            byte[] original=Files.readAllBytes(grant);Files.writeString(grant,new String(original,StandardCharsets.UTF_8).replace("\"enabled\":true","\"enabled\":false"));
            var denied=http.send(java.net.http.HttpRequest.newBuilder(uri).GET().build(),java.net.http.HttpResponse.BodyHandlers.ofString());
            assertEquals(503,denied.statusCode());Files.write(grant,original);
        }
        assertEquals(2,jdbc.queryForObject("SELECT count(*) FROM briefing_attempts WHERE status='completed'",Integer.class));
        assertEquals(8,jdbc.queryForObject("SELECT count(*) FROM ai_executions WHERE execution_mode='live'",Integer.class));
        assertEquals(4,jdbc.queryForObject("SELECT count(*) FROM ai_executions WHERE feature='briefing-outlook'",Integer.class));
        assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM ai_executions WHERE input_tokens IS NULL OR actual_cost IS NOT NULL",Integer.class));
        assertEquals(8,jdbc.queryForObject("SELECT count(*) FROM ai_executions WHERE estimated_cost IS NOT NULL AND currency='USD'",Integer.class));
        assertEquals(2,jdbc.queryForObject("SELECT count(*) FROM briefing_personal_pools WHERE (snapshot->>'complete')::boolean",Integer.class));
    }

    @Test @Tag("briefing-auto-postgres")
    void actualCollectionNativeRegistrationPriorityPublicationAndReplayProtection() throws Exception {
        collectionAndPublication(false);
    }
    @Test @Tag("briefing-auto-postgres")
    void heldFirstDocumentContinuesAndPersonalSharesVerifiedCommonWithinSixteenCalls() throws Exception {
        collectionAndPublication(true);
    }
    private void collectionAndPublication(boolean shared) throws Exception {
        String previous=publish(importNative(HandoffFixtures.Spec.standard()));server();
        int previousIssues=reader().read(previous).snapshot().issues().size();
        jdbc.update("INSERT INTO companies(id,name,name_key,search_text) VALUES('SYNTH-1','합성기업','','')");
        Path script=Path.of("../scripts/tests/fixtures/briefing_auto_chain_smoke.py").toAbsolutePath().normalize();
        var process=new ProcessBuilder(System.getenv().getOrDefault("BRIEFING_AUTO_TEST_PYTHON","python3"),script.toString(),temp.toString(),System.getProperty("zoop.briefing.usage.classpath"));
        var e=process.environment();e.put("DB_URL",url);e.put("DB_USERNAME","company_test");e.put("DB_PASSWORD",password());
        if(shared)e.put("BRIEFING_AUTO_TEST_SHARED","true");
        e.put("BRIEFING_USAGE_ARTIFACT_ROOT",temp.toRealPath().resolve("producer").toString());
        e.put("ZOOP_DOCUMENT_READ_GRANTS",grant.toString());e.put("ZOOP_DOCUMENT_READ_INGESTION_SOURCES",authority.toString());
        e.put("JAVA",Path.of(System.getProperty("java.home"),"bin/java").toString());
        Path log=temp.resolve("auto-smoke.log");process.redirectErrorStream(true).redirectOutput(log.toFile());var child=process.start();
        assertTrue(child.waitFor(180,java.util.concurrent.TimeUnit.SECONDS));assertEquals(0,child.exitValue(),Files.readString(log));
        System.out.println("Synthetic chain proof: "+Files.readString(temp.resolve("auto-proof.json")));
        var round=new com.zoop.briefing.storage.BriefingRoundRepository(jdbc).findById("brf-2026-11-04-morning").orElseThrow();
        com.zoop.briefing.query.BriefingSnapshotValidator.validate(round);assertEquals("published",round.status());
        assertTrue(round.publicSnapshot().at("/commonPriority/items/0/sources/0/publishedAt").isNull());
        assertEquals("2026-11-04",round.publicSnapshot().at("/commonPriority/items/0/sources/0/publishedDate").asString());
        assertEquals("completed",jdbc.queryForObject("SELECT status FROM briefing_common_schedule_jobs",String.class));
        assertEquals(shared?3:2,jdbc.queryForObject("SELECT count(*) FROM briefing_attempts WHERE status='completed'",Integer.class));
        assertTrue(jdbc.queryForObject("SELECT count(*) FROM ai_executions",Integer.class)<=16);
        assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM ai_executions WHERE actual_cost IS NOT NULL OR input_tokens IS NULL",Integer.class));
        String active=versions.active().orElseThrow().id();assertNotEquals(previous,active);
        assertTrue(reader().read(active).snapshot().issues().size()>previousIssues);
        assertEquals(previousIssues,reader().read(previous).snapshot().issues().size());
        var grants=temp.toRealPath().resolve("auto-authority/serving-grants.json");var sources=temp.toRealPath().resolve("auto-authority/serving-delegates.json");
        try(var app=new org.springframework.boot.builder.SpringApplicationBuilder(com.zoop.ZoopApplication.class).run(
            "--server.port=0","--spring.datasource.url="+url,"--spring.datasource.username=company_test","--spring.datasource.password="+password(),
            "--spring.flyway.enabled=false","--spring.jpa.properties.hibernate.default_schema="+schema,
            "--zoop.document-read.grants="+grants,"--zoop.document-read.artifact-root="+temp.toRealPath().resolve("producer"),
            "--zoop.document-read.ingestion-sources="+sources,"--zoop.graph.snapshot.source=artifact","--zoop.graph.snapshot.artifact-root="+temp.toRealPath().resolve("producer"),
            "--ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test","--ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")){
            assertTrue(com.zoop.briefing.query.BriefingPriorityRules.storedSourcesMatch(round.publicSnapshot().get("commonPriority"),jdbc),"source metadata changed after publication");
            assertTrue(app.getBean(com.zoop.briefing.query.BriefingContentAccess.class).mayRead(round,"auto-gate"),"API authority disagrees with publisher");
            int port=((org.springframework.boot.web.server.context.WebServerApplicationContext)app).getWebServer().getPort();
            var response=java.net.http.HttpClient.newHttpClient().send(java.net.http.HttpRequest.newBuilder(java.net.URI.create("http://127.0.0.1:"+port+"/api/v1/briefings?date=2026-11-04&edition=morning")).GET().build(),java.net.http.HttpResponse.BodyHandlers.ofString());
            assertEquals(200,response.statusCode(),response.body());assertEquals(1,com.zoop.common.json.StrictJson.parseObject(response.body()).node().path("commonPriority").path("items").size());
            assertFalse(response.body().contains("generationRequestDigest"));
            // Exercise prospective settings and the actual dispatcher, rather than inserting a finished delivery.
            String member="auto-member",peer="auto-peer",other="auto-other";
            for(String id:List.of(member,peer,other))jdbc.update("""
                INSERT INTO members(id,analytics_key,email,email_key,display_name,signup_method,status,created_at,
                    mode,completed,tutorial_completed,settings_version,updated_at)
                VALUES(?,?,?,?,?,'google','active',now(),'watchlist',true,true,1,now())
                """,id,id,id+"@example.invalid",id+"@example.invalid","합성 자동화 시험");
            jdbc.update("INSERT INTO member_watchlist(member_id,company_id,position) VALUES(?,?,0)",member,"SYNTH-1");
            jdbc.update("INSERT INTO member_watchlist(member_id,company_id,position) VALUES(?,?,0)",peer,"SYNTH-1");
            jdbc.update("INSERT INTO member_watchlist(member_id,company_id,position) VALUES(?,?,0)",other,"SYNTH-1");
            var principal=new com.zoop.auth.service.MemberSessionService.MemberPrincipal(member,"auto-test");
            var before=autoPreferences(app,Clock.fixed(Instant.parse("2026-11-04T00:01:00Z"),ZoneOffset.UTC));
            transaction.executeWithoutResult(s->before.initialize(principal));
            var peerPrincipal=new com.zoop.auth.service.MemberSessionService.MemberPrincipal(peer,"auto-test");
            transaction.executeWithoutResult(s->before.initialize(peerPrincipal));
            var atSlot=Clock.fixed(Instant.parse("2026-11-04T00:20:30Z"),ZoneOffset.UTC);
            var personal=autoPreferences(app,atSlot);
            var scheduler=new com.zoop.briefing.personal.PersonalBriefingDeliveryScheduler(jdbc,personal,atSlot,new com.zoop.briefing.personal.PersonalBriefingAudience(member+","+peer,true));
            transaction.executeWithoutResult(s->scheduler.captureMorning());
            int calls=jdbc.queryForObject("SELECT count(*) FROM ai_executions",Integer.class);
            transaction.executeWithoutResult(s->scheduler.tick());
            var delivery=personal.get(round.id(),principal,false,"auto-delivery");
            assertEquals("ready",delivery.path("status").asString());
            assertEquals(1,delivery.at("/selection/presentation/personalPriority/items").size());
            var peerDelivery=personal.get(round.id(),peerPrincipal,false,"auto-peer-delivery");
            assertEquals("ready",peerDelivery.path("status").asString());
            assertNotEquals(delivery.path("id"),peerDelivery.path("id"));
            assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM briefing_personal_slot_eligibility WHERE member_id=?",Integer.class,other));
            assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM briefing_personal_preferences WHERE member_id=?",Integer.class,other));
            assertTrue(delivery.at("/selection/presentation/personalPriority/items/0/sources/0/publishedAt").isNull());
            transaction.executeWithoutResult(s->scheduler.tick());
            assertEquals(delivery,personal.get(round.id(),principal,false,"auto-repeat"));
            assertEquals(calls,jdbc.queryForObject("SELECT count(*) FROM ai_executions",Integer.class));
            assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM briefing_selected_generation_jobs",Integer.class));
            var sessions=app.getBean(com.zoop.auth.service.MemberSessionService.class);
            var http=java.net.http.HttpClient.newHttpClient();
            var uri=java.net.URI.create("http://127.0.0.1:"+port+"/api/v1/briefings/"+round.id()+"/personalized/delivery");
            String token=sessions.issue(member,null,"auto-http").token();
            var mine=http.send(java.net.http.HttpRequest.newBuilder(uri).header("Cookie","zoop_session="+token).GET().build(),java.net.http.HttpResponse.BodyHandlers.ofString());
            assertEquals(200,mine.statusCode(),mine.body());assertEquals("no-store",mine.headers().firstValue("Cache-Control").orElseThrow());
            assertEquals("ready",com.zoop.common.json.StrictJson.parseObject(mine.body()).string("status"));
            String otherToken=sessions.issue(other,null,"auto-other").token();
            var notMine=http.send(java.net.http.HttpRequest.newBuilder(uri).header("Cookie","zoop_session="+otherToken).GET().build(),java.net.http.HttpResponse.BodyHandlers.ofString());
            assertEquals(200,notMine.statusCode());assertEquals("not_published",com.zoop.common.json.StrictJson.parseObject(notMine.body()).string("status"));
            Path leaf=temp.toRealPath().resolve("auto-authority/grants.json");byte[] approved=Files.readAllBytes(leaf);
            try {
                Files.writeString(leaf,new String(approved,StandardCharsets.UTF_8).replace("\"enabled\":true","\"enabled\":false"));
                var revoked=http.send(java.net.http.HttpRequest.newBuilder(uri).header("Cookie","zoop_session="+token).GET().build(),java.net.http.HttpResponse.BodyHandlers.ofString());
                assertEquals(503,revoked.statusCode());
            } finally {Files.write(leaf,approved);}
            // Optional local browser gate; no environment setting in CI, no production endpoint or clock override.
            String browser=System.getenv("ZOOP_BRIEFING_AUTO_BROWSER");
            if(browser!=null){
                Path marker=Path.of(browser);assertTrue(marker.isAbsolute());
                Files.writeString(marker,"{\"api\":\"http://127.0.0.1:"+port+"\",\"round\":\""+round.id()+"\"}");
                long end=System.nanoTime()+java.util.concurrent.TimeUnit.MINUTES.toNanos(5);
                while(!Files.exists(marker.resolveSibling(marker.getFileName()+".done"))&&System.nanoTime()<end)Thread.sleep(250);
                assertTrue(Files.exists(marker.resolveSibling(marker.getFileName()+".done")),"local browser gate timed out");
            }
        }
    }

    private com.zoop.briefing.personal.PersonalBriefingPreferences autoPreferences(org.springframework.context.ConfigurableApplicationContext app,Clock clock){
        return new com.zoop.briefing.personal.PersonalBriefingPreferences(jdbc,clock,
            app.getBean(com.zoop.briefing.personal.ExplicitBriefingService.class),app.getBean(com.zoop.briefing.personal.SelectedGenerationService.class),
            app.getBean(com.zoop.briefing.storage.BriefingRoundRepository.class),app.getBean(com.zoop.briefing.personal.PersonalCandidateAccess.class),
            app.getBean(com.zoop.graph.read.PersonalCompanies.class),false);
    }

    private void runProducer(String edition,String mode) throws Exception {
        Path script=Path.of("../scripts/tests/fixtures/briefing_server_smoke.py").toAbsolutePath().normalize();
        var process=new ProcessBuilder("python3",script.toString(),temp.toString(),System.getProperty("zoop.briefing.usage.classpath"),edition,mode);
        var e=process.environment();e.put("DB_URL",url);e.put("DB_USERNAME","company_test");e.put("DB_PASSWORD",password());
        e.put("BRIEFING_SERVER_WORK_ROOT",work.toString());e.put("BRIEFING_USAGE_ARTIFACT_ROOT",temp.toRealPath().resolve("producer").toString());
        e.put("BRIEFING_SERVER_SOURCE_SCOPE",temp.toRealPath().resolve("model-scope.json").toString());e.put("ZOOP_DOCUMENT_READ_GRANTS",grant.toString());e.put("ZOOP_DOCUMENT_READ_INGESTION_SOURCES",authority.toString());
        e.put("JAVA",Path.of(System.getProperty("java.home"),"bin/java").toString());
        Path log=temp.resolve("smoke-"+edition+".log");process.redirectErrorStream(true).redirectOutput(log.toFile());var child=process.start();
        assertTrue(child.waitFor(120,java.util.concurrent.TimeUnit.SECONDS));assertEquals(0,child.exitValue(),Files.readString(log));
    }
    @Test void unsupportedSelectedIssueIsHeldAndItsRepairIsOneRetryUnit() throws Exception {
        publish(importNative(HandoffFixtures.Spec.standard()));server();runProducer("morning","withheld");
        assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM briefing_rounds WHERE published_at IS NOT NULL",Integer.class));
        assertEquals("failed",jdbc.queryForObject("SELECT status FROM briefing_attempts",String.class));
        assertEquals(6,jdbc.queryForObject("SELECT count(*) FROM ai_executions WHERE execution_mode='live'",Integer.class));
        assertEquals(2,jdbc.queryForObject("SELECT count(*) FROM ai_executions WHERE retry_unit_id IS NOT NULL",Integer.class));
        assertEquals(1,jdbc.queryForObject("SELECT count(DISTINCT retry_unit_id) FROM ai_executions WHERE retry_unit_id IS NOT NULL",Integer.class));
    }
    @Test void briefingIntakeActivationKeepsEveryExistingGraphRecord() throws Exception {
        String first=publish(importNative(HandoffFixtures.Spec.standard()));server();
        var env=new java.util.HashMap<String,String>();
        env.put("DB_URL",url);env.put("DB_USERNAME","company_test");env.put("DB_PASSWORD",password());
        env.put("BRIEFING_SERVER_WORK_ROOT",work.toString());env.put("BRIEFING_USAGE_ARTIFACT_ROOT",temp.toRealPath().resolve("producer").toString());
        env.put("ZOOP_DOCUMENT_READ_GRANTS",grant.toString());env.put("ZOOP_DOCUMENT_READ_INGESTION_SOURCES",authority.toString());
        env.put("BRIEFING_SERVER_AUTHORITY_ROOT",temp.toRealPath().toString());env.put("BRIEFING_SERVER_ADDITIVE_GRAPH_ALLOWED","true");
        env.put("BRIEFING_SERVER_AUTHORIZATION_REF","synthetic-additive-test");
        var command=new com.zoop.briefing.server.BriefingNativeCommand(env);var baseline=command.state();
        var before=reader().read(first).snapshot();
        String second=importNative(HandoffFixtures.Spec.standard().withIssueId("issue-second-intake"));
        var request=com.zoop.common.json.StrictJson.newObject();request.set("baseline",baseline);
        request.putObject("incoming").put("sourceVersion",second).put("receiptSha256",registry.findArtifact("artifact-receipt-"+second).orElseThrow().sha256());
        var result=command.activate(com.zoop.common.json.StrictJson.Obj.of(request));
        assertEquals(first,result.path("previousGraphVersion").asString());
        var after=reader().read(result.path("graphVersion").asString()).snapshot();
        assertTrue(after.issues().containsAll(before.issues()));assertTrue(after.relations().containsAll(before.relations()));
        assertTrue(after.evidence().containsAll(before.evidence()));assertTrue(after.articles().containsAll(before.articles()));
        assertTrue(versions.everActivated(result.path("graphVersion").asString()));
        assertThrows(IllegalStateException.class,()->command.activate(com.zoop.common.json.StrictJson.Obj.of(request)));
    }

    @Test void dayOnlySourceUsesObservedClockAndPreservesNullPublicationInstant() throws Exception {
        var spec=HandoffFixtures.Spec.standard().withPublication("2026-10-08","day");
        var built=HandoffFixtures.build(spec.withHandoffId("day-source-"+UUID.randomUUID()));
        var ingestion=new HandoffFixtures.FakeIngestion();
        ingestion.serve=selector->{
            var exported=com.zoop.common.json.StrictJson.parseObject(HandoffFixtures.standardIngestionExport());
            var observation=(ObjectNode)exported.raw("observation");
            observation.putNull("publishedAt");observation.put("provenance","collected_http");
            var collection=observation.putObject("collection").put("provenance","collected_http").put("collectionId","synthetic-day-source");
            collection.putObject("receipt").put("file","collections/synthetic-day-source/receipts/"+"7".repeat(64)+".json").put("sha256","7".repeat(64));
            collection.put("fetchedAt","2026-10-14T01:02:03.456789Z").put("finalUrl","https://example.invalid/a").put("httpStatus",200)
                .put("contentType","text/html").put("bodySha256","9".repeat(64)).put("documentKind","news").put("network","synthetic_loopback");
            collection.putObject("published").put("raw","2026-10-08").put("precision","day").put("date","2026-10-08").put("basis","declared");
            return com.zoop.common.json.StrictJson.write(exported.node());
        };
        var importer=new GraphHandoffImporter(new HandoffFixtures.FakeHandoff(built.envelopeBytes()),ingestion,
                new IngestionExportParser(),files,registry,graph,transaction,CLOCK);
        var imported=importer.run(built.request());
        assertTrue(imported.succeeded(),new String(GraphHandoffResultWriter.toBytes(imported),StandardCharsets.UTF_8));publish(built.versionId());
        var input=server().prepare(com.zoop.common.json.StrictJson.Obj.of(request("morning")));
        var source=input.path("candidates").get(0).path("sources").values().iterator().next();
        assertTrue(source.path("publishedAt").isNull());assertEquals("2026-10-08",source.path("publishedDate").asString());
        assertEquals("2026-10-14T01:02:03.456789Z",source.path("availableAt").asString());
        server().check(com.zoop.common.json.StrictJson.Obj.of(input));runProducer("morning","normal");
        assertEquals("2026-10-08",jdbc.queryForObject("SELECT published_payload->'items'->0->>'reportedAt' FROM briefing_rounds",String.class));
        assertEquals(1,jdbc.queryForObject("SELECT count(*) FROM briefing_rounds WHERE published_at IS NOT NULL",Integer.class));
        var pool=com.zoop.common.json.StrictJson.parseObject(jdbc.queryForObject("SELECT snapshot::text FROM briefing_personal_pools",String.class));
        var poolSource=pool.array("candidates").get(0).path("sources").get(0);
        assertTrue(poolSource.path("publishedAt").isNull());
        assertEquals(HandoffFixtures.ARTICLE_VERSION,poolSource.path("documentVersion").asString());
        assertEquals("synthetic-briefing",poolSource.path("grantId").asString());
    }

    @Test void unavailableInputIsAFailedPrepareAttemptWithoutAnyModelCall() throws Exception {
        server();runProducer("morning","input-failed");
        assertEquals("failed",jdbc.queryForObject("SELECT status FROM briefing_attempts",String.class));
        assertEquals("prepare",jdbc.queryForObject("SELECT stages->>'failureStage' FROM briefing_attempts",String.class));
        assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM ai_executions",Integer.class));
    }

    private GraphPublicationReader reader() {
        return new GraphPublicationReader(graph, registry, files, publications);
    }

    private GraphPublicationComposer composer() {
        var sources = new DocumentReadSources(authority);
        var rights = new GraphPublicationAuthority(registry, sources,
                version -> new DisclosureExclusions(0, Set.of(), Set.of(), Set.of(), Set.of()), CLOCK);
        return new GraphPublicationComposer(files, graph, registry, versions, publications, reader(), rights, sources, transaction, CLOCK);
    }

    private GraphPublicationPreparer preparer() {
        return new GraphPublicationPreparer(versions, graph, publications, reader(), composer());
    }

    private static byte[] decisionBytes(ObjectNode result) {
        return Base64.getDecoder().decode(result.get("decisionsBase64").asString());
    }

    private static tools.jackson.databind.JsonNode change(ObjectNode result, String field) {
        return result.get("changes").values().stream().filter(c -> field.equals(c.get("field").asString())).findFirst().orElseThrow();
    }

    private String importNative(HandoffFixtures.Spec spec) {
        var built = HandoffFixtures.build(spec.withHandoffId("prepare-" + UUID.randomUUID()));
        var importer = new GraphHandoffImporter(new HandoffFixtures.FakeHandoff(built.envelopeBytes()), new HandoffFixtures.FakeIngestion(),
                new IngestionExportParser(), files, registry, graph, transaction, CLOCK);
        assertTrue(importer.run(built.request()).succeeded());
        return built.versionId();
    }

    /** Composes the first publication from {@code source} like the operator B4 and makes it the active version a person approved. */
    private String publish(String source) {
        String id = compose(null, source);
        jdbc.update("UPDATE graph_versions SET active = true,published_at=? WHERE id = ?",Timestamp.from(NOW.minusSeconds(60)), id);
        jdbc.update("""
                INSERT INTO graph_activations (version_id, previous_version_id, action, actor_kind, pointer_changed, admin_id,
                    admin_email_snapshot, reason, activated_at) VALUES (?, NULL, 'activate', 'system', true, NULL, 'system', 'synthetic', ?)
                """, id, Timestamp.from(NOW.minusSeconds(60)));
        return id;
    }

    /** An operator compose (B4) of {@code source} on {@code base} with no decisions; not activated. */
    private String compose(String base, String source) {
        byte[] decisions = Canonical.bytes(PublicationMerger.emptyDecisions().node());
        var state = graph.publicationState();
        var pins = new java.util.TreeMap<String, String>();
        pins.put(source, registry.findArtifact("artifact-receipt-" + source).orElseThrow().sha256());
        String basePin = base == null ? null : registry.findArtifact("artifact-receipt-" + base).orElseThrow().sha256();
        var request = new PublicationComposeRequest(base, List.of(source), base, basePin, pins, state.ruleRevision(), state.reviewRevision(),
                Canonical.sha256(decisions), "synthetic");
        var composed = composer().run(request, decisions);
        assertEquals("succeeded", composed.get("status").asString(), composed.toString());
        return composed.get("graphVersionId").asString();
    }

    private void activate(String id) {
        String previous = versions.active().orElseThrow().id();
        jdbc.update("UPDATE graph_versions SET active = false WHERE active");
        jdbc.update("UPDATE graph_versions SET active = true,published_at=? WHERE id = ?",Timestamp.from(NOW.minusSeconds(60)), id);
        jdbc.update("""
                INSERT INTO graph_activations (version_id, previous_version_id, action, actor_kind, pointer_changed, admin_id,
                    admin_email_snapshot, reason, activated_at) VALUES (?, ?, 'activate', 'system', true, NULL, 'system', 'synthetic', ?)
                """, id, previous, Timestamp.from(NOW));
    }

    private static List<String> strings(ObjectNode node, String field) {
        return node.get(field).values().stream().map(v -> v.asString()).toList();
    }
}
