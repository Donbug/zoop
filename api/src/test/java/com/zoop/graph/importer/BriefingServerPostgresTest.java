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
                        Instant.parse("2026-10-14T01:02:03.456789Z")));
            });
        }
    }

    @AfterEach void stop() {
        if (jdbc != null) jdbc.execute("DROP SCHEMA IF EXISTS " + schema + " CASCADE");
    }

    private static String password(){String value=System.getenv("ZOOP_COMPANY_TEST_DB_PASSWORD");return value==null||value.isBlank()?"synthetic-test-only":value;}
    private com.zoop.briefing.server.BriefingServerCommand server() throws Exception {
        work=temp.toRealPath().resolve("work");Files.createDirectories(work);
        grant=temp.resolve("grants.json");
        if(!Files.exists(grant))Files.writeString(grant,"""
            {"schemaVersion":"zoop-ai-s1-1","grants":[{"grantId":"synthetic-briefing","revision":"v1","sourceId":"synthetic-source",
             "enabled":true,"rights":"known","allowedOperations":["read","store","quote-display","model-send"],
             "recipients":["openai"],"purposes":["briefing-outlook","semantic-verification"],"evidence":["synthetic operator authorization"],"expiresAt":null}]}
            """);
        Path scope=temp.toRealPath().resolve("model-scope.json");
        if(!Files.exists(scope))Files.writeString(scope,"{\"schemaVersion\":\"briefing-model-scope-v1\",\"authorizationRef\":\"synthetic\",\"sources\":[{\"sourceId\":\""+HandoffFixtures.SOURCE+"\",\"documentId\":\""+HandoffFixtures.ARTICLE_ID+"\",\"documentVersion\":\""+HandoffFixtures.ARTICLE_VERSION+"\",\"bodySha256\":\""+Canonical.sha256(HandoffFixtures.TEXT.getBytes(StandardCharsets.UTF_8))+"\"}]}");
        return new com.zoop.briefing.server.BriefingServerCommand(java.util.Map.of(
            "DB_URL",url,"DB_USERNAME","company_test","DB_PASSWORD",password(),
            "BRIEFING_SERVER_WORK_ROOT",work.toString(),"BRIEFING_USAGE_ARTIFACT_ROOT",temp.toRealPath().resolve("producer").toString(),
            "BRIEFING_SERVER_SOURCE_SCOPE",scope.toString(),"ZOOP_DOCUMENT_READ_GRANTS",grant.toString(),"ZOOP_DOCUMENT_READ_INGESTION_SOURCES",authority.toString()));
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
