package com.zoop.briefing.integration;

import com.zoop.auth.service.MemberSessionService;
import com.zoop.briefing.query.SavedBriefingBundle;
import com.zoop.briefing.query.SavedBriefingPublisher;
import com.zoop.common.json.Canonical;
import java.net.URI;
import java.net.http.*;
import java.nio.file.*;
import java.sql.DriverManager;
import java.util.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import tools.jackson.databind.json.JsonMapper;
import static org.junit.jupiter.api.Assertions.*;

/** Optional private input, always a disposable LOCAL database; never a provider call or live account login. */
@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT,properties={
 "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test","ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
 "zoop.briefing.personal-demo-enabled=false","zoop.briefing.personal-scheduler-enabled=false",
 "zoop.briefing.common-scheduler-enabled=false","zoop.briefing.selected-generation-enabled=false"})
@EnabledIfEnvironmentVariable(named="DB_URL",matches="jdbc:postgresql:.*")
@EnabledIfEnvironmentVariable(named="BRIEFING_FINALIZED_BUNDLE",matches=".+")
@Tag("briefing-postgres")
@DirtiesContext(classMode=DirtiesContext.ClassMode.AFTER_CLASS)
class SavedBriefingRealBundlePostgresTest {
 static final String SCHEMA="saved_actual_"+UUID.randomUUID().toString().replace("-","");
 static final JsonMapper JSON=JsonMapper.builder().build();
 @Autowired JdbcTemplate jdbc;@Autowired SavedBriefingPublisher publisher;@Autowired MemberSessionService sessions;
 @LocalServerPort int port;
 static String url() {
  String base=System.getenv("DB_URL");var address=URI.create(base.substring(5));
  if(!List.of("localhost","127.0.0.1","[::1]").contains(address.getHost())||!address.getPath().contains("test"))
   throw new IllegalArgumentException("disposable_local_database_required");
  try(var c=DriverManager.getConnection(base,user(),password());var s=c.createStatement();var r=s.executeQuery("SELECT string_agg(DISTINCT n.nspname,',') FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace")){
   r.next();return base+(base.contains("?")?"&":"?")+"currentSchema="+SCHEMA+",public"+(r.getString(1)==null?"":","+r.getString(1));
  }catch(java.sql.SQLException e){throw new IllegalStateException(e);}
 }
 static String user(){return System.getenv().getOrDefault("DB_USERNAME","briefing_test");}
 static String password(){return System.getenv().getOrDefault("DB_PASSWORD","");}
 @DynamicPropertySource static void properties(DynamicPropertyRegistry p){
  p.add("spring.datasource.url",SavedBriefingRealBundlePostgresTest::url);p.add("spring.flyway.schemas",()->SCHEMA);
  p.add("spring.flyway.default-schema",()->SCHEMA);p.add("spring.jpa.properties.hibernate.default_schema",()->SCHEMA);
  p.add("zoop.document-read.grants",()->System.getenv("BRIEFING_FINALIZED_GRANTS"));
  p.add("zoop.document-read.artifact-root",()->System.getenv("BRIEFING_FINALIZED_BUNDLE"));
  p.add("zoop.document-read.ingestion-sources",()->"");
  p.add("zoop.graph.snapshot.source",()->"artifact");p.add("zoop.graph.snapshot.artifact-root",()->System.getenv("BRIEFING_FINALIZED_BUNDLE"));
 }
 @Test void stagesPublishesAndReadsEverySavedCommonAndMemberResultWithNoAiExecution()throws Exception {
  Path root=Path.of(System.getenv("BRIEFING_FINALIZED_BUNDLE")).toRealPath();
  var bundle=SavedBriefingBundle.read(root,Canonical.sha256(Files.readAllBytes(root.resolve("manifest.json"))));
  String member=bundle.manifest().path("finalization").path("memberId").asString();
  jdbc.update("""
   INSERT INTO members(id,analytics_key,email,email_key,display_name,signup_method,status,created_at,
    mode,completed,tutorial_completed,settings_version,updated_at)
   VALUES(?,?,'saved-private@example.invalid','saved-private@example.invalid','[local private fixture]','google',
    'active','2026-01-01T00:00:00Z','watchlist',true,true,1,now())
   """,member,member);
  jdbc.execute(Files.readString(Path.of(System.getenv("BRIEFING_FINALIZED_SQL"))));
  var result=publisher.publish(bundle.manifest(),bundle.manifestSha256(),bundle.tables());
  assertEquals(bundle.tables().get("briefing_rounds").size(),result.path("publishedRounds").asInt());
  assertEquals(bundle.tables().get("briefing_personal_deliveries").size(),result.path("demoDeliveries").asInt());
  String token=sessions.issue(member,null,"local-private-bundle-verification").token();
  for(var round:bundle.tables().get("briefing_rounds")) {
   var response=get("/api/v1/briefings?date="+round.path("round_date").asString()+"&edition="+round.path("edition").asString(),null);
   assertEquals(200,response.statusCode(),"saved common HTTP");
   var body=JSON.readTree(response.body());assertEquals("published",body.path("status").asString());
   assertEquals(round.path("published_payload").path("items"),body.path("items"));
   var personal=get("/api/v1/briefings/"+round.path("id").asString()+"/personalized/delivery?demo=true",token);
   assertEquals(200,personal.statusCode(),"saved personal HTTP");
   assertEquals("ready",JSON.readTree(personal.body()).path("status").asString(),"saved personal status");
  }
  assertTrue(publisher.publish(bundle.manifest(),bundle.manifestSha256(),bundle.tables()).path("reused").asBoolean());
  assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM ai_executions",Integer.class));
  assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM briefing_personal_preferences WHERE scope='scheduled'",Integer.class));
 }
 HttpResponse<String> get(String path,String token)throws Exception {
  var b=HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+path));if(token!=null)b.header("Cookie","zoop_session="+token);
  return HttpClient.newHttpClient().send(b.GET().build(),HttpResponse.BodyHandlers.ofString());
 }
 @AfterAll static void cleanup()throws Exception{
  try(var c=DriverManager.getConnection(url(),user(),password());var s=c.createStatement()){s.execute("DROP SCHEMA "+SCHEMA+" CASCADE");}
 }
}
