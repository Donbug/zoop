package com.zoop.briefing.integration;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.auth.service.MemberSessionService;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.briefing.personal.PersonalBriefingPreferences;
import com.zoop.briefing.query.SavedBriefingPublisher;
import com.zoop.common.json.Canonical;
import java.net.URI;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
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
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;
import static org.junit.jupiter.api.Assertions.*;

/** Authored data only: real native-source guards, transaction rollback and authenticated HTTP, no model transport. */
@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT,properties={
 "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test","ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
 "zoop.briefing.personal-demo-enabled=true","zoop.briefing.personal-scheduler-enabled=false","zoop.briefing.common-scheduler-enabled=false"})
@EnabledIfEnvironmentVariable(named="DB_URL",matches="jdbc:postgresql:.*")
@Tag("briefing-postgres")
@DirtiesContext(classMode=DirtiesContext.ClassMode.AFTER_CLASS)
class SavedBriefingPublicationPostgresTest {
 static final String SCHEMA="saved_publish_"+UUID.randomUUID().toString().replace("-","");
 static final Path ROOT=root();static final Path GRANTS=ROOT.resolve("grants.json");
 static final String ROUND="brf-test-2026-10-15-evening", MEMBER="saved-test-member";
 static final String GRAPH="gv-"+Canonical.sha256("saved-synthetic"),EV="ev-"+"7".repeat(64);
 static final String IMPORTED="2026-11-04T00:00:00Z";
 static final JsonMapper JSON=JsonMapper.builder().build();
 @Autowired JdbcTemplate jdbc;@Autowired SavedBriefingPublisher publisher;
 @Autowired MemberSessionService sessions;@Autowired PersonalBriefingPreferences preferences;
 @LocalServerPort int port;
 Map<String,List<JsonNode>> tables;ObjectNode manifest;String pref;String beforeSettings;String beforeFeedback;
 static Path root(){try{Path p=Files.createTempDirectory("saved-briefing-test-").toRealPath();Files.setPosixFilePermissions(p,java.nio.file.attribute.PosixFilePermissions.fromString("rwx------"));try(var files=ArtifactFileStore.at(p).open()){}Files.writeString(p.resolve("sources.json"),"{}");Files.writeString(p.resolve("grants.json"),"{}");return p;}catch(Exception e){throw new IllegalStateException(e);}}
 static String url(){return System.getenv("DB_URL")+(System.getenv("DB_URL").contains("?")?"&":"?")+"currentSchema="+SCHEMA;}
 static String user(){return System.getenv().getOrDefault("DB_USERNAME","briefing_test");}
 static String password(){return System.getenv().getOrDefault("DB_PASSWORD","");}
 @DynamicPropertySource static void properties(DynamicPropertyRegistry p){
  p.add("spring.datasource.url",SavedBriefingPublicationPostgresTest::url);p.add("spring.flyway.schemas",()->SCHEMA);
  p.add("spring.flyway.default-schema",()->SCHEMA);p.add("spring.jpa.properties.hibernate.default_schema",()->SCHEMA);
  p.add("zoop.document-read.grants",()->GRANTS.toString());p.add("zoop.document-read.artifact-root",()->ROOT.toString());
  p.add("zoop.document-read.ingestion-sources",()->ROOT.resolve("sources.json").toString());p.add("zoop.graph.snapshot.source",()->"artifact");p.add("zoop.graph.snapshot.artifact-root",()->ROOT.toString());
 }
 String resource(String name)throws Exception{try(var in=getClass().getClassLoader().getResourceAsStream("briefing/"+name)){return new String(Objects.requireNonNull(in).readAllBytes(),StandardCharsets.UTF_8);}}
 @BeforeEach void stage()throws Exception{
  jdbc.execute("TRUNCATE briefing_result_imports,briefing_changes,briefing_rounds,graph_activations,graph_versions,articles,artifacts,members,companies CASCADE");
  var grants=(ObjectNode)JSON.readTree(resource("grants.json"));var grant=(ObjectNode)grants.path("grants").get(0);
  grant.putArray("allowedOperations").add("read").add("quote-display");grant.putArray("purposes").add("briefing-outlook");
  Files.writeString(GRANTS,grants.toString());Files.setPosixFilePermissions(GRANTS,java.nio.file.attribute.PosixFilePermissions.fromString("rw-------"));
  ArtifactFileStore.StoredFile text,verification;
  try(var f=ArtifactFileStore.at(ROOT).open()){
   text=f.put("extracted_text","saved-text.txt","합성시험 원문입니다.".getBytes(StandardCharsets.UTF_8));
   verification=f.put("verification_receipt","saved-exact.json","{}".getBytes(StandardCharsets.UTF_8));
  }
  String sql=resource("fixture.sql");int begin=sql.indexOf("$records$")+9,end=sql.indexOf("$records$",begin);
  var records=JSON.createArrayNode();ObjectNode record=null;
  for(var r:JSON.readTree(sql.substring(begin,end)))if(ROUND.equals(r.path("p").path("id").asString()))record=(ObjectNode)r;
  assertNotNull(record);record.putNull("published");record.putNull("morning");
  record.set("comparison",JSON.createObjectNode().put("status","unavailable").put("reason","[합성] 이전 회차 없음"));
  var snapshot=(ObjectNode)record.path("snapshot");var priority=(ObjectNode)JSON.readTree(resource("priority-authored.json"));
  snapshot.set("commonPriority",priority);snapshot.putObject("savedResultContext").putArray("previous");records.add(record);
  sql=sql.substring(0,begin)+records+sql.substring(end);
  sql=sql.replace("'published',p->>'graphVersion'","'scheduled',p->>'graphVersion'")
    .replace("(entry->>'published')::timestamptz","NULL")
    .replace("synthetic-graph-v1",GRAPH).replace("brf-test-evidence",EV)
    .replace("artifact://synthetic/briefing-test/text",text.uri()).replace("repeat('a',64),10","'"+text.sha256()+"',"+text.bytes())
    .replace("artifact://synthetic/briefing-test/verification",verification.uri()).replace("repeat('b',64),2","'"+verification.sha256()+"',"+verification.bytes());
  jdbc.execute(sql);
  var graph=(ObjectNode)JSON.readTree(resource("graph-snapshot.json").replace("brf-test-evidence",EV));graph.put("versionId",GRAPH).put("sourceBundleId","saved-synthetic");
  String graphSha;
  try(var f=ArtifactFileStore.at(ROOT).open()){
   var file=f.put("graph_snapshot","saved-graph.json",JSON.writeValueAsBytes(graph));graphSha=file.sha256();
   jdbc.update("INSERT INTO artifacts(id,kind,storage_uri,sha256,bytes,media_type,created_at) VALUES('saved-graph','graph_snapshot',?,?,?,'application/json',now())",file.uri(),file.sha256(),file.bytes());
   jdbc.update("INSERT INTO graph_versions(id,sequence,kind,created_at,published_at,created_by,source_label,issue_count,relation_count,article_count,snapshot_artifact_id,review_revision,active) VALUES(?,1,'snapshot',now(),now(),'system','graph-handoff:saved-synthetic',1,1,1,'saved-graph',1,false)",GRAPH);
   String receipt="{\"schemaVersion\":\"zoop-graph-handoff-import-receipt-1\",\"handoffId\":\"saved-synthetic\",\"bundle\":{\"articles\":[{\"articleId\":\"brf-test-document\",\"articleVersion\":\"synthetic-v1\",\"textSha256\":\""+text.sha256()+"\",\"observations\":[{\"sourceId\":\"authored-replay\",\"grant\":{\"grantId\":\"round-read-grant\",\"revision\":\"r1\"}}]}]}}";
   var proof=f.put("verification_receipt",GRAPH+".json",receipt.getBytes(StandardCharsets.UTF_8));
   jdbc.update("INSERT INTO artifacts(id,kind,storage_uri,sha256,bytes,media_type,created_at) VALUES(?,'verification_receipt',?,?,?,'application/json',now())","artifact-receipt-"+GRAPH,proof.uri(),proof.sha256(),proof.bytes());
   jdbc.update("INSERT INTO graph_version_sources(graph_version_id,ordinal,handoff_id,receipt_artifact_id,bundle_snapshot_artifact_id) VALUES(?,0,'saved-synthetic',?,'saved-graph')",GRAPH,"artifact-receipt-"+GRAPH);
  }
  Files.writeString(ROOT.resolve("sources.json"),"""
   {"schemaVersion":"zoop-ingestion-s2-1","revision":"r1","sources":[{"sourceId":"authored-replay","adapter":"authored-files","inputRoot":"/srv/zoop/test","allowedHosts":["example.invalid"],"scopes":[{"scopeId":"body","selection":"authored test","initialCursor":null,"articleXPath":null,"timestampLimitations":["synthetic"]}],"grant":{"grantId":"round-read-grant","revision":"r1","sourceId":"authored-replay","enabled":true,"rights":"known","allowedOperations":["read","store","quote-display"],"recipients":[],"purposes":[],"evidence":["authored"],"expiresAt":null}}]}
   """);
  jdbc.update("INSERT INTO members(id,analytics_key,email,email_key,display_name,signup_method,status,created_at,mode,completed,tutorial_completed,settings_version,updated_at) VALUES(?,?,'saved@example.invalid','saved@example.invalid','[합성] 회원','google','active','2026-11-01T00:00:00Z','watchlist',true,true,1,now())",MEMBER,MEMBER);
  jdbc.update("INSERT INTO briefing_personal_preferences(id,member_id,scope,revision,choice,created_at,effective_from) VALUES('live-pref',?,'scheduled',1,'{\"companyIds\":[\"brf-test-company\"],\"maxIssues\":3,\"minIssues\":0,\"perCompanyLimit\":3}',now(),now()+interval '1 minute')",MEMBER);
  beforeSettings=preferences.settings(new MemberPrincipal(MEMBER,"test")).path("preference").toString();
  var choice=JSON.readTree("{\"companyIds\":[\"brf-test-company\"],\"maxIssues\":3,\"minIssues\":0,\"perCompanyLimit\":3}");
  pref="prep-pref-"+Canonical.sha256("synthetic-source-ref\n"+MEMBER+"\ndemo\n1").substring(0,24);
  jdbc.update("INSERT INTO briefing_personal_preferences(id,member_id,scope,revision,choice,created_at,effective_from) VALUES(?,?,'demo',1,?::jsonb,?::timestamptz,?::timestamptz+interval '1 microsecond')",pref,MEMBER,choice.toString(),IMPORTED,IMPORTED);
  var source=JSON.createObjectNode().put("evidenceId",EV).put("documentId","brf-test-document").put("documentVersion","synthetic-v1")
   .put("bodySha256",text.sha256()).put("grantId","brf-test-grant").put("grantRevision","synthetic-v1").put("publishedAt","2026-10-13T00:00:00Z").put("quote","합성시험").put("url","https://example.invalid/synthetic-document");source.putArray("recipients").add("authored-replay");
  var pool=JSON.createObjectNode().put("schemaVersion","personal-candidate-pool-v1").put("roundId",ROUND).put("cutoff","2026-10-15T08:30:00Z").put("complete",true).put("candidateCount",1).put("inputSha256","c".repeat(64));
  var candidate=pool.putArray("candidates").addObject().put("issueId","brf-test-event").put("eventKey","saved-event").put("importance",2).put("verified",true);
  candidate.putArray("sources").add(source);candidate.putArray("companies").addObject().put("companyId","brf-test-company").putArray("evidenceIds").add(EV);
  jdbc.update("INSERT INTO briefing_personal_pools(id,round_id,input_sha256,snapshot,snapshot_sha256) VALUES('saved-pool',?,'"+"c".repeat(64)+"',?::jsonb,encode(sha256(convert_to((?::jsonb)::text,'UTF8')),'hex'))",ROUND,pool.toString(),pool.toString());
  var presentation=(ObjectNode)JSON.readTree(record.path("p").toString().replace("synthetic-graph-v1",GRAPH).replace("brf-test-evidence",EV));
  presentation.put("dataAsOf","2026-10-15T08:30:00Z");presentation.set("marketSummary",snapshot.path("marketSummary"));
  var selection=JSON.createObjectNode().put("roundId",ROUND).put("poolVersion","c".repeat(64)).put("selectionVersion","saved-selection-v1");selection.set("choice",choice);selection.set("presentation",presentation);
  String delivery="prep-delivery-"+Canonical.sha256("original-delivery\n"+pref).substring(0,24);
  jdbc.update("INSERT INTO briefing_personal_deliveries(id,member_id,round_id,preference_id,mode,scheduled_at,selection_snapshot,selection_sha256,result_snapshot,result_sha256,status,finished_at) VALUES(?,?,?,?,'demo','2026-10-15T08:30:00Z',?::jsonb,encode(sha256(convert_to((?::jsonb)::text,'UTF8')),'hex'),?::jsonb,encode(sha256(convert_to((?::jsonb)::text,'UTF8')),'hex'),'ready',now())",delivery,MEMBER,ROUND,pref,selection.toString(),selection.toString(),selection.toString(),selection.toString());
  jdbc.update("INSERT INTO briefing_feedback(id,member_id,feature,target_id,target_version,round_id,value,created_at,updated_at) VALUES('preserved-feedback',?,'briefing_round','brf-test-2026-10-16-morning','saved','brf-test-2026-10-16-morning','up',now(),now())",MEMBER);
  beforeFeedback=jdbc.queryForObject("SELECT to_jsonb(f)::text FROM briefing_feedback f WHERE id='preserved-feedback'",String.class);
  tables=new LinkedHashMap<>();
  for(String table:List.of("artifacts","articles","article_versions","evidence","briefing_rounds","briefing_personal_pools","briefing_personal_preferences","briefing_personal_deliveries")) {
   String where=table.equals("briefing_rounds")?" WHERE id='"+ROUND+"'":table.equals("briefing_personal_preferences")?" WHERE id='"+pref+"'":"";
   tables.put(table,jdbc.query("SELECT to_jsonb(t)::text FROM "+table+" t"+where,(rs,i)->JSON.readTree(rs.getString(1))));
  }
  // Tables preserve source IDs; the staging renderer computes the target IDs.
  ((ObjectNode)tables.get("briefing_personal_deliveries").getFirst()).put("id","original-delivery");
  manifest=JSON.createObjectNode().put("memberBindingRef","synthetic-source-ref");
  var f=manifest.putObject("finalization").put("schemaVersion","briefing-finalization-v1").put("memberId",MEMBER).put("preferenceRevision",1).put("importedAt",IMPORTED)
   .put("requestSha256","d".repeat(64)).put("grantsSha256",Canonical.sha256(Files.readAllBytes(GRANTS)));
  f.putArray("rounds").addObject().put("roundId",ROUND).put("graphVersion",GRAPH).put("snapshotSha256",graphSha);
 }
 @Test void publishesSavedResultsOnceAndPreservesLiveSettingsFeedbackAndInactiveMap()throws Exception{
  var result=publisher.publish(manifest,"e".repeat(64),tables);assertFalse(result.path("reused").asBoolean());assertEquals(0,result.path("newAiCalls").asInt());
  assertTrue(publisher.publish(manifest,"e".repeat(64),tables).path("reused").asBoolean());
  assertEquals(beforeSettings,preferences.settings(new MemberPrincipal(MEMBER,"test")).path("preference").toString());
  assertEquals(beforeFeedback,jdbc.queryForObject("SELECT to_jsonb(f)::text FROM briefing_feedback f WHERE id='preserved-feedback'",String.class));
  assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM graph_versions WHERE active",Integer.class));
  assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM ai_executions",Integer.class));
  assertEquals(200,get("/api/v1/briefings?date=2026-10-15&edition=evening",null).statusCode());
  assertEquals(401,get("/api/v1/briefings/"+ROUND+"/personalized/delivery?demo=true",null).statusCode());
  var personal=get("/api/v1/briefings/"+ROUND+"/personalized/delivery?demo=true",sessions.issue(MEMBER,null,"test").token());
  assertEquals(200,personal.statusCode(),personal.body());assertEquals("ready",JSON.readTree(personal.body()).path("status").asString());
  jdbc.update("""
   INSERT INTO members SELECT (jsonb_populate_record(NULL::members,to_jsonb(m)||'{"id":"other-owner","analytics_key":"other-owner","email":"other@example.invalid","email_key":"other@example.invalid"}'::jsonb)).*
   FROM members m WHERE id=?
   """,MEMBER);
  var other=get("/api/v1/briefings/"+ROUND+"/personalized/delivery?demo=true",sessions.issue("other-owner",null,"test").token());
  assertEquals(200,other.statusCode());assertEquals("not_published",JSON.readTree(other.body()).path("status").asString());assertFalse(other.body().contains(pref));
 }
 @Test void changedGrantOrArtifactRollsBackEveryPublication()throws Exception{
  Files.writeString(GRANTS,Files.readString(GRANTS).replace("\"known\"","\"unknown\""));
  assertThrows(RuntimeException.class,()->publisher.publish(manifest,"e".repeat(64),tables));
  assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM briefing_result_imports",Integer.class));
  assertNull(jdbc.queryForObject("SELECT published_at FROM briefing_rounds WHERE id=?",java.sql.Timestamp.class,ROUND));
 }
 @Test void declaredGraphCannotReplaceMissingRealRegistrationAndAllWritesRollback(){
  ((ObjectNode)manifest.path("finalization").path("rounds").get(0)).put("snapshotSha256","f".repeat(64));
  assertThrows(RuntimeException.class,()->publisher.publish(manifest,"e".repeat(64),tables));
  assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM briefing_result_imports",Integer.class));
  assertEquals("scheduled",jdbc.queryForObject("SELECT status FROM briefing_rounds WHERE id=?",String.class,ROUND));
 }
 @Test void revokedNativeAuthorityRollsBackVisibilityAndPublicationTogether()throws Exception{
  jdbc.update("UPDATE articles SET access_status='private' WHERE id='brf-test-document'");
  Path sources=ROOT.resolve("sources.json");Files.writeString(sources,Files.readString(sources).replace("\"enabled\":true","\"enabled\":false"));
  assertThrows(RuntimeException.class,()->publisher.publish(manifest,"e".repeat(64),tables));
  assertEquals("private",jdbc.queryForObject("SELECT access_status FROM articles WHERE id='brf-test-document'",String.class));
  assertEquals("scheduled",jdbc.queryForObject("SELECT status FROM briefing_rounds WHERE id=?",String.class,ROUND));
  assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM briefing_result_imports",Integer.class));
 }
 @Test void changedSourceBytesNeverReachPublication()throws Exception{
  String uri=jdbc.queryForObject("SELECT storage_uri FROM artifacts WHERE id='brf-test-text'",String.class);
  Path file=ROOT.resolve(uri.substring("artifact-root:".length()));byte[] original=Files.readAllBytes(file);
  try{Files.writeString(file,"changed");assertThrows(RuntimeException.class,()->publisher.publish(manifest,"e".repeat(64),tables));}
  finally{Files.write(file,original);}
  assertEquals("scheduled",jdbc.queryForObject("SELECT status FROM briefing_rounds WHERE id=?",String.class,ROUND));
 }
 @Test void demoNeverBlocksRealDefaultInitializationOrUsesItsRevisionSequence(){
  jdbc.update("DELETE FROM briefing_personal_deliveries WHERE member_id=?",MEMBER);
  jdbc.update("DELETE FROM briefing_personal_preferences WHERE id='live-pref'");
  var result=preferences.initialize(new MemberPrincipal(MEMBER,"test"));assertEquals("no_companies",result.path("initializationStatus").asString());assertTrue(result.path("preference").isNull());
  var choice=new com.zoop.briefing.personal.ExplicitBriefingService.Choice(List.of("brf-test-company"),3,0,3);
  assertEquals(1,preferences.save(new MemberPrincipal(MEMBER,"test"),new PersonalBriefingPreferences.Save(choice,null)).path("preference").path("revision").asInt());
 }
 @Test void exactPreviousSummaryVersionIsRequiredAndFailureRollsBackAllRounds()throws Exception {
  previous(false,"different-version");
  assertThrows(RuntimeException.class,()->publisher.publish(manifest,"e".repeat(64),tables));
  assertEquals("scheduled",jdbc.queryForObject("SELECT status FROM briefing_rounds WHERE id=?",String.class,ROUND));
  assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM briefing_result_imports",Integer.class));
 }
 @Test void archivedPreviousInputIsReadableOnlyWithItsExactRetainedArtifactAndEvidence()throws Exception {
  Path artifact=previous(true,"older-retained-version");publisher.publish(manifest,"e".repeat(64),tables);
  String original=jdbc.queryForObject("SELECT public_snapshot::text FROM briefing_rounds WHERE id=?",String.class,ROUND);
  assertEquals(200,get("/api/v1/briefings?date=2026-10-15&edition=evening",null).statusCode());
  Files.writeString(artifact,"changed archive");
  assertEquals(503,get("/api/v1/briefings?date=2026-10-15&edition=evening",null).statusCode());
  assertEquals(original,jdbc.queryForObject("SELECT public_snapshot::text FROM briefing_rounds WHERE id=?",String.class,ROUND));
 }
 Path previous(boolean archive,String version)throws Exception {
  String id="saved-prior-round",cutoff="2026-10-14T08:30:00Z";
  ObjectNode payload=(ObjectNode)tables.get("briefing_rounds").getFirst().path("published_payload").deepCopy();
  payload.put("id",id).put("date","2026-10-14").put("scheduledAt",cutoff).put("generatedAt",cutoff);
  payload.putObject("dataWindow").putNull("start").put("end",cutoff).put("openStart",true);
  ObjectNode current=(ObjectNode)tables.get("briefing_rounds").getFirst().path("public_snapshot").deepCopy();
  ObjectNode prior=current.deepCopy();prior.remove("savedResultContext");prior.putObject("prioritySummary").put("resultVersion","current-prior-version");
  jdbc.update("""
   INSERT INTO briefing_rounds(id,round_date,edition,scheduled_at,window_from,window_to,open_start,status,graph_version_id,review_revision,rule_revision,
    published_payload,payload_sha256,public_snapshot,schema_version,generated_at,published_at,comparison_snapshot)
   SELECT ?,'2026-10-14','evening',?::timestamptz,NULL,?::timestamptz,true,'published',graph_version_id,review_revision,rule_revision,
    ?::jsonb,encode(sha256(convert_to((?::jsonb)::text,'UTF8')),'hex'),?::jsonb,schema_version,?::timestamptz,?::timestamptz,comparison_snapshot
   FROM briefing_rounds WHERE id=?
   """,id,cutoff,cutoff,payload.toString(),payload.toString(),prior.toString(),cutoff,cutoff,ROUND);
  var reference=JSON.createObjectNode().put("roundId",id).put("cutoff",cutoff).put("resultVersion",version);Path target=null;
  if(archive) {
   var value=JSON.createObjectNode().put("status","available").put("roundId",id).put("cutoff",cutoff).put("resultVersion",version);
   value.putObject("draft").put("text","[합성] 보존된 이전 입력").putArray("evidenceIds").add(EV);
   String digest=Canonical.digest(value);var entry=current.putObject("priorityContext").putObject("contexts").putObject("context:previous").put("sha256",digest);entry.set("value",value);
   var archived=JSON.createObjectNode().put("schemaVersion","briefing-archived-previous-context-v1").put("roundId",ROUND).put("sourceContextSha256",digest);archived.set("context",value);
   try(var f=ArtifactFileStore.at(ROOT).open()) {
    var file=f.put("briefing_input","prior-input.json",Canonical.bytes(archived));target=ROOT.resolve(file.uri().substring("artifact-root:".length()));
    jdbc.update("INSERT INTO artifacts(id,kind,storage_uri,sha256,bytes,media_type,created_at) VALUES('saved-prior-input','briefing_input',?,?,?,'application/json',now())",file.uri(),file.sha256(),file.bytes());
   }
   reference.put("artifactId","saved-prior-input").put("contextSha256",digest).putArray("evidenceIds").add(EV);
  }
  var context=current.putObject("savedResultContext");context.putArray("previous");context.putArray("archivedPrevious");context.withArray(archive?"archivedPrevious":"previous").add(reference);
  jdbc.update("UPDATE briefing_rounds SET public_snapshot=?::jsonb WHERE id=?",current.toString(),ROUND);
  tables.put("briefing_rounds",jdbc.query("SELECT to_jsonb(t)::text FROM briefing_rounds t WHERE id=?",(r,i)->JSON.readTree(r.getString(1)),ROUND));
  tables.put("artifacts",jdbc.query("SELECT to_jsonb(t)::text FROM artifacts t",(r,i)->JSON.readTree(r.getString(1))));return target;
 }
 HttpResponse<String> get(String path,String token)throws Exception{var b=HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+path));if(token!=null)b.header("Cookie","zoop_session="+token);return HttpClient.newHttpClient().send(b.GET().build(),HttpResponse.BodyHandlers.ofString());}
 @AfterAll static void cleanup()throws Exception{
  try(var c=DriverManager.getConnection(url(),user(),password());var s=c.createStatement()){s.execute("DROP SCHEMA "+SCHEMA+" CASCADE");}
  try(var paths=Files.walk(ROOT)){for(var p:paths.sorted(Comparator.reverseOrder()).toList())Files.deleteIfExists(p);}
 }
}
