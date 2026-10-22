package com.zoop.briefing.replay;

import com.zoop.ZoopApplication;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.StrictJson;
import java.net.*;
import java.net.http.*;
import java.nio.file.*;
import java.util.*;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.boot.web.server.servlet.context.ServletWebServerApplicationContext;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import tools.jackson.databind.node.ObjectNode;
import static org.junit.jupiter.api.Assertions.*;

/** Actual offline producer → importer → PostgreSQL → public HTTP; never contacts a model/provider. */
@Tag("briefing-replay-postgres")
@EnabledIfEnvironmentVariable(named="DB_URL",matches="jdbc:postgresql:.*briefing_replay.*")
class BriefingReviewFixesPostgresTest {
    @Test void unresolvedInitialSelectionDoesNotBlockTheOtherThirteenRounds() throws Exception { verify("--unresolved"); }
    @Test void unresolvedCorrectionDoesNotBlockTheOtherThirteenRounds() throws Exception { verify("--unresolved-correction"); }
    @Test void rejectedSummaryRepairKeepsAllNewsPublicationsAndAuditedAttempts() throws Exception { verify("--failed-repair"); }
    @Test void frozenCalendarReachesStorageAndTamperingIsRejected() throws Exception { verify("--frozen-calendar"); }

    private void verify(String mode) throws Exception {
        boolean grouped=mode.startsWith("--unresolved"), calendar=mode.equals("--frozen-calendar");
        Path root=Files.createTempDirectory("zoop-review-replay-").toRealPath();
        String schema="review098_"+UUID.randomUUID().toString().replace("-","");
        String parent=System.getenv("DB_URL"), url=parent+(parent.contains("?")?"&":"?")+"currentSchema="+schema+",public";
        String user=System.getenv().getOrDefault("DB_USERNAME","company_test"), pass=System.getenv().getOrDefault("DB_PASSWORD","");
        var ds=new DriverManagerDataSource(url,user,pass);var db=new JdbcTemplate(ds);ConfigurableApplicationContext server=null;
        try {
            Path script=Path.of(grouped?"scripts/briefing_grouped_fixture.py":"scripts/briefing_market_context_fixture.py").toAbsolutePath();
            Process process=new ProcessBuilder("python3",script.toString(),root.toString(),mode).redirectErrorStream(true)
                    .redirectOutput(root.resolve("fixture.log").toFile()).start();
            assertEquals(0,process.waitFor(),()->{try{return Files.readString(root.resolve("fixture.log"));}catch(Exception e){return e.toString();}});
            db.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public");db.execute("CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public");
            Flyway.configure().dataSource(ds).schemas(schema).defaultSchema(schema).load().migrate();
            db.update("INSERT INTO companies(id,name) VALUES (?,?)",grouped?"company-authored":"authored-context-company",grouped?"합성 기업":"시험 기업");
            Path bundle=root.resolve((grouped?"output":"enriched")+"/bundle-v2.json"), source=root.resolve("sources.jsonl"), artifacts=Files.createDirectory(root.resolve("artifacts"));
            String inbox=grouped?"inbox/authored-grouped-run.md":"inbox/authored-market-context.md";
            var importer=new BriefingReplayImporter(db,new DataSourceTransactionManager(ds),new BriefingReplaySettings(source,bundle,artifacts,
                    root.resolve("grants.json"),root.resolve("manifest.json"),ArtifactFileStore.sha256(Files.readAllBytes(source)),inbox,root.resolve("clocks.json")));
            importer.importBundle();
            assertEquals(grouped?13:14,db.queryForObject("SELECT count(*) FROM briefing_rounds WHERE published_at IS NOT NULL",Integer.class));
            assertTrue(importer.importBundle().alreadyImported());
            if(grouped) {
                assertEquals(1,db.queryForObject("SELECT count(*) FROM artifacts WHERE id LIKE '%held-selection-reservation%'",Integer.class));
                assertEquals(1,db.queryForObject("SELECT count(*) FROM briefing_rounds WHERE status='failed' AND published_payload IS NULL",Integer.class));
                StrictJson.Obj saved=StrictJson.parseObject(Files.readAllBytes(bundle)), row=saved.objects("rounds").getFirst();
                String digest=row.object("groupedUnresolvedPaidRequest").string("requestDigest");
                assertFalse(Files.exists(bundle.getParent().resolve("calls/"+digest+".response.json")));
                assertFalse(Files.exists(bundle.getParent().resolve("calls/"+digest+".complete.json")));
            } else if(calendar) {
                assertEquals(1,db.queryForObject("SELECT count(*) FROM artifacts WHERE id LIKE '%-frozen-calendar'",Integer.class));
            } else {
                StrictJson.Obj saved=StrictJson.parseObject(Files.readAllBytes(bundle)).object("marketEnrichment").objects("rounds").getFirst().object("summaryResult");
                assertTrue(saved.objects("claims").isEmpty());assertTrue(saved.isNull("verificationRequestDigest"));assertEquals(2,saved.objects("attempts").size());
            }
            server=new SpringApplicationBuilder(ZoopApplication.class).web(WebApplicationType.SERVLET).profiles("local").run(
                    "--server.port=0","--server.address=127.0.0.1","--spring.datasource.url="+url,"--spring.datasource.username="+user,"--spring.datasource.password="+pass,
                    "--spring.flyway.schemas="+schema,"--spring.flyway.default-schema="+schema,"--spring.jpa.properties.hibernate.default_schema="+schema,
                    "--ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test","--ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                    "--zoop.briefing.replay.read-enabled=true","--zoop.briefing.replay.manifest="+root.resolve("manifest.json"),
                    "--zoop.document-read.grants="+root.resolve("grants.json"),"--zoop.document-read.artifact-root="+artifacts);
            int port=((ServletWebServerApplicationContext)server).getWebServer().getPort();
            for(String edition:List.of("morning","evening")) {
                var response=HttpClient.newHttpClient().send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+"/api/v1/briefings?date=2026-10-02&edition="+edition)).GET().build(),HttpResponse.BodyHandlers.ofString());
                assertEquals(200,response.statusCode(),response.body());var result=StrictJson.parseObject(response.body());
                assertEquals(grouped&&edition.equals("morning")?"failed":"published",result.string("status"));
                if(!grouped&&!calendar&&edition.equals("morning")) assertFalse(result.object("marketSummary").has("text"));
            }
            String before=db.queryForObject("SELECT md5(string_agg(row_to_json(r)::text,'' ORDER BY id)) FROM briefing_rounds r",String.class);
            if(grouped) {
                var altered=(ObjectNode)StrictJson.parseObject(Files.readAllBytes(bundle)).node().deepCopy();
                ((ObjectNode)altered.at("/rounds/0/groupedUnresolvedPaidRequest")).put("preexistingAtProcessStart",false);
                Files.write(bundle,StrictJson.write(altered));
                assertTrue(assertThrows(RuntimeException.class,importer::importBundle).getMessage().contains("unresolved_selection_disposition"));
            } else if(calendar) {
                try(var files=Files.list(bundle.getParent().resolve("market/calendars"))) {Files.writeString(files.findFirst().orElseThrow(),"{}");}
                assertTrue(assertThrows(RuntimeException.class,importer::importBundle).getMessage().contains("frozen_calendar_bytes"));
            }
            assertEquals(before,db.queryForObject("SELECT md5(string_agg(row_to_json(r)::text,'' ORDER BY id)) FROM briefing_rounds r",String.class));
        } finally {
            if(server!=null)server.close();db.execute("DROP SCHEMA IF EXISTS "+schema+" CASCADE");
            try(var paths=Files.walk(root)){for(Path path:paths.sorted(Comparator.reverseOrder()).toList())Files.deleteIfExists(path);}
        }
    }
}
