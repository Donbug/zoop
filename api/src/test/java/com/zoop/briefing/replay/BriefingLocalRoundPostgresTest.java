package com.zoop.briefing.replay;

import com.zoop.ZoopApplication;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.briefing.reconstruction.BriefingGraphReconstructor;
import com.zoop.common.json.StrictJson;
import java.net.URI;
import java.net.http.*;
import java.nio.file.*;
import java.util.UUID;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.boot.web.server.servlet.context.ServletWebServerApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import tools.jackson.databind.node.ObjectNode;
import static org.junit.jupiter.api.Assertions.*;

/** Authored source/provider control; real PostgreSQL -> importer -> HTTP -> graph registration. */
@Tag("briefing-replay-postgres")
@EnabledIfEnvironmentVariable(named="DB_URL", matches="jdbc:postgresql:.*briefing_replay.*")
class BriefingLocalRoundPostgresTest {
    @Test void singleCollectedRoundImportsReadsAndMapsWithoutHistoricalBackfill() throws Exception {
        Path root=Files.createTempDirectory("zoop-local-round-").toRealPath();
        var command=new ProcessBuilder("python3",Path.of("scripts/briefing_local_fixture.py").toAbsolutePath().toString(),root.toString());
        command.environment().put("PYTHONDONTWRITEBYTECODE","1");
        var child=command.redirectErrorStream(true).redirectOutput(root.resolve("fixture.log").toFile()).start();
        assertEquals(0,child.waitFor(),()->read(root.resolve("fixture.log")));
        String schema="local_round_"+UUID.randomUUID().toString().replace("-","");
        String url=System.getenv("DB_URL")+"?currentSchema="+schema+",public";
        String user=System.getenv().getOrDefault("DB_USERNAME","company_test"), password=System.getenv().getOrDefault("DB_PASSWORD","");
        var ds=new DriverManagerDataSource(url,user,password);var db=new JdbcTemplate(ds);
        Path source=root.resolve("sources.jsonl"),bundle=root.resolve("output/bundle-v2.json"),
            artifacts=Files.createDirectory(root.resolve("artifacts")),grants=root.resolve("grants.json"),manifest=root.resolve("manifest.json");
        try {
            Flyway.configure().dataSource(ds).schemas(schema).defaultSchema(schema).load().migrate();
            db.update("INSERT INTO companies(id,name) VALUES ('company-authored','합성 기업')");
            var settings=new BriefingReplaySettings(source,bundle,artifacts,grants,manifest,
                ArtifactFileStore.sha256(Files.readAllBytes(source)),"inbox/authored-grouped-run.md",root.resolve("clocks.json"),40,null);
            var importer=new BriefingReplayImporter(db,new DataSourceTransactionManager(ds),settings);
            var imported=importer.importBundle();
            assertEquals(1,imported.roundIds().size());assertFalse(imported.alreadyImported());
            String id=imported.roundIds().getFirst();
            assertTrue(importer.importBundle().alreadyImported());
            assertEquals(1,db.queryForObject("SELECT count(*) FROM briefing_rounds",Integer.class));
            assertEquals("local_collection_validation",db.queryForObject("SELECT public_snapshot->'replay'->>'scope' FROM briefing_rounds",String.class));
            assertFalse(db.queryForObject("SELECT (public_snapshot->'replay'->>'retrospectiveBodies')::boolean FROM briefing_rounds",Boolean.class));
            try (var server=new SpringApplicationBuilder(ZoopApplication.class).web(WebApplicationType.SERVLET).profiles("local").run(
                "--server.port=0","--server.address=127.0.0.1","--spring.datasource.url="+url,
                "--spring.datasource.username="+user,"--spring.datasource.password="+password,
                "--spring.flyway.schemas="+schema,"--spring.flyway.default-schema="+schema,
                "--spring.jpa.properties.hibernate.default_schema="+schema,
                "--ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test","--ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                "--zoop.briefing.replay.read-enabled=true","--zoop.briefing.replay.manifest="+manifest,
                "--zoop.document-read.grants="+grants,"--zoop.document-read.artifact-root="+artifacts,
                "--zoop.graph.snapshot.source=artifact","--zoop.graph.snapshot.artifact-root="+artifacts)) {
                int port=((ServletWebServerApplicationContext)server).getWebServer().getPort();
                var http=HttpClient.newHttpClient();
                var news=http.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+"/api/v1/briefings?date=2026-10-02&edition=morning")).GET().build(),HttpResponse.BodyHandlers.ofString());
                assertEquals(200,news.statusCode());assertTrue(news.body().contains("zoop-briefing-local-collection-validation"));
                server.getBean(BriefingGraphReconstructor.class).reconstruct(id,artifacts);
                var graph=http.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+"/api/v1/briefings/"+id+"/graph")).GET().build(),HttpResponse.BodyHandlers.ofString());
                assertEquals(200,graph.statusCode());assertTrue(graph.body().contains("available"));
            }
            String before=db.queryForObject("SELECT payload_sha256 FROM briefing_rounds",String.class);
            Path catalogue=root.resolve("output/publication-companies.json");
            byte[] originalCatalogue=Files.readAllBytes(catalogue);
            Files.writeString(catalogue,"{\"companies\":[]}");
            assertThrows(RuntimeException.class,importer::importBundle);
            assertEquals(before,db.queryForObject("SELECT payload_sha256 FROM briefing_rounds",String.class));
            Files.write(catalogue,originalCatalogue);
            byte[] original=Files.readAllBytes(bundle);
            var changed=(ObjectNode)StrictJson.parseObject(original).node().deepCopy();
            ((ObjectNode)changed.path("localCollection")).put("discoveryTo","2999-01-01T00:00:00Z");
            ((ObjectNode)changed.path("authorization")).set("localCollection",changed.path("localCollection").deepCopy());
            Files.write(bundle,StrictJson.write(changed));
            assertThrows(RuntimeException.class,importer::importBundle);
            assertEquals(before,db.queryForObject("SELECT payload_sha256 FROM briefing_rounds",String.class));
            Files.write(bundle,original);
        } finally {db.execute("DROP SCHEMA IF EXISTS "+schema+" CASCADE");}
    }
    private static String read(Path p) {try{return Files.readString(p);}catch(Exception e){return e.getClass().getSimpleName();}}
}
