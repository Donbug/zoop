package com.zoop.briefing.personal;
import java.time.*;
import java.util.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.dao.DataAccessException;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.briefing.storage.BriefingRoundRepository;
import com.zoop.common.exception.CustomException;
import tools.jackson.databind.node.ObjectNode;
import static org.junit.jupiter.api.Assertions.*;
/** Optional replay acceptance gate. Existing outputs are reused; every write rolls back. No model transport. */
@SpringBootTest(properties={"server.address=127.0.0.1","zoop.briefing.personal-scheduler-enabled=false","zoop.briefing.personal-demo-enabled=true","zoop.briefing.selected-generation-enabled=false"})
@org.springframework.test.context.ActiveProfiles("local")
@Tag("briefing-postgres")
@EnabledIfEnvironmentVariable(named="ZOOP_PREFERENCE_REPLAY_TEST",matches="true")
@Transactional
class PersonalPreferencePostgresTest {
 @Autowired JdbcTemplate jdbc;@Autowired ExplicitBriefingService selection;@Autowired SelectedGenerationService generation;@Autowired BriefingRoundRepository rounds;@Autowired PersonalCandidateAccess access;
 final String round="sim-2026-10-22-morning-0537f757d685";
 final ExplicitBriefingService.Choice choice=new ExplicitBriefingService.Choice(List.of("NASDAQ:AAPL"),3,0,3);
 MemberPrincipal member;MutableClock clock;PersonalBriefingPreferences service;
 com.zoop.graph.read.PersonalCompanies personal;
 @BeforeEach void setup(){
  String url=Objects.requireNonNull(System.getenv("DB_URL"));assertTrue(url.contains("zoop_briefing_replay_personal216"),"acceptance only in the isolated task replay copy");
  String id="pref-test-"+UUID.randomUUID();
  jdbc.update("INSERT INTO members(id,analytics_key,email,email_key,display_name,signup_method,status,created_at,mode,completed,tutorial_completed,settings_version,updated_at) VALUES(?,?,?,?,?,'google','active',now(),'watchlist',true,true,1,now())",id,id,id+"@example.invalid",id+"@example.invalid","[합성] 설정 시험");
  member=new MemberPrincipal(id,"test");
  clock=new MutableClock("2026-10-21T20:00:00Z");personal=org.mockito.Mockito.mock(com.zoop.graph.read.PersonalCompanies.class);
  org.mockito.Mockito.when(personal.of(org.mockito.ArgumentMatchers.any())).thenReturn(new com.zoop.graph.read.PersonalCompanies.Ids(List.of("NASDAQ:AAPL"),List.of()));
  service=new PersonalBriefingPreferences(jdbc,clock,selection,generation,rounds,access,personal,true);
 }
 @Test void initializesHoldingsAndWatchlistOnceAndPreservesExistingChoice(){
  org.mockito.Mockito.when(personal.of(member)).thenReturn(new com.zoop.graph.read.PersonalCompanies.Ids(List.of("NASDAQ:AAPL"),List.of("NASDAQ:AAPL","NYSE:TSM")));
  var first=service.initialize(member);assertEquals("initialized",first.path("initializationStatus").asString());assertEquals(2,first.path("preference").path("choice").path("companyIds").size());
  assertEquals("2026-10-22T00:20:00Z",first.path("preference").path("effectiveFrom").asString());
  var again=service.initialize(member);assertEquals("existing",again.path("initializationStatus").asString());assertEquals(first.path("preference"),again.path("preference"));
  org.mockito.Mockito.verify(personal,org.mockito.Mockito.times(1)).of(member);
 }
 @Test void emptyHoldingsAndWatchlistCreateNoPreferenceDeliveryOrAiJob(){
  org.mockito.Mockito.when(personal.of(member)).thenReturn(new com.zoop.graph.read.PersonalCompanies.Ids(List.of(),List.of()));
  var response=service.initialize(member);assertEquals("no_companies",response.path("initializationStatus").asString());assertTrue(response.path("preference").isNull());
  assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM briefing_personal_preferences WHERE member_id=?",Integer.class,member.memberId()));
  assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM briefing_personal_deliveries WHERE member_id=?",Integer.class,member.memberId()));
  assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM briefing_selected_generation_jobs WHERE member_id=?",Integer.class,member.memberId()));
 }
 @Test void slotEligibilityAndExistingPublicationSurviveLaterPortfolioRemoval(){
  service.save(member,new PersonalBriefingPreferences.Save(choice,null));clock.now=Instant.parse("2026-10-22T00:20:00Z");service.captureEligibility(member,clock.now);clock.now=Instant.parse("2026-10-22T01:00:00Z");
  var original=service.prepare(round,member,false,null,"test");
  org.mockito.Mockito.when(personal.of(member)).thenReturn(new com.zoop.graph.read.PersonalCompanies.Ids(List.of(),List.of()));
  assertEquals(original,service.prepare(round,member,false,null,"test"));
  assertEquals(original,service.get(round,member,false,"test"));
 }
 @Test void noCompaniesAtTheSlotNeverCreatesADeliveryEvenIfStocksAreAddedLater(){
  service.save(member,new PersonalBriefingPreferences.Save(choice,null));clock.now=Instant.parse("2026-10-22T00:20:00Z");
  org.mockito.Mockito.when(personal.of(member)).thenReturn(new com.zoop.graph.read.PersonalCompanies.Ids(List.of(),List.of()));service.captureEligibility(member,clock.now);
  org.mockito.Mockito.when(personal.of(member)).thenReturn(new com.zoop.graph.read.PersonalCompanies.Ids(List.of("NASDAQ:AAPL"),List.of()));
  clock.now=Instant.parse("2026-10-22T01:00:00Z");assertEquals("no_companies",service.prepare(round,member,false,null,"test").path("status").asString());
  assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM briefing_personal_deliveries WHERE member_id=?",Integer.class,member.memberId()));
 }
 @Test void commonSlotsAreQueuedOnceAndCarryThePreviousCutoff(){
  clock.now=Instant.parse("2026-10-30T01:00:00Z");var timer=new com.zoop.briefing.scheduling.CommonBriefingScheduler(jdbc,clock);timer.reconcileToday();timer.reconcileToday();
  assertEquals(1,jdbc.queryForObject("SELECT count(*) FROM briefing_common_schedule_jobs WHERE round_date='2026-10-30' AND edition='morning'",Integer.class));
  assertEquals(java.sql.Timestamp.from(Instant.parse("2026-10-29T08:30:00Z")),jdbc.queryForObject("SELECT window_from FROM briefing_common_schedule_jobs WHERE round_date='2026-10-30' AND edition='morning'",java.sql.Timestamp.class));
  assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM briefing_common_schedule_jobs WHERE round_date='2026-10-30' AND edition='evening'",Integer.class));
 }
 @Test void defaultsDoNotSilentlyTruncateMoreThanTwentyCompanies(){
  var all=jdbc.query("SELECT id FROM companies ORDER BY id",(r,i)->r.getString(1));assertTrue(all.size()>20);
  org.mockito.Mockito.when(personal.of(member)).thenReturn(new com.zoop.graph.read.PersonalCompanies.Ids(all,List.of(all.getFirst())));
  assertEquals(all.size(),service.initialize(member).path("preference").path("choice").path("companyIds").size());
 }
 @Test void changesApplyToNextSlotAndNeverRewritePublishedDelivery(){
  var first=service.save(member,new PersonalBriefingPreferences.Save(choice,null)).path("preference");assertEquals("2026-10-22T00:20:00Z",first.path("effectiveFrom").asString());
  clock.now=Instant.parse("2026-10-22T00:20:00Z");service.captureEligibility(member,clock.now);clock.now=Instant.parse("2026-10-22T01:00:00Z");var published=service.prepare(round,member,false,null,"test");assertEquals("ready",published.path("status").asString());assertEquals(3,published.path("selection").path("presentation").path("items").size());
  var changed=new ExplicitBriefingService.Choice(List.of("NASDAQ:AAPL","NYSE:TSM"),3,0,3);var second=service.save(member,new PersonalBriefingPreferences.Save(changed,first.path("revisionId").asString())).path("preference");assertEquals("2026-10-22T08:30:00Z",second.path("effectiveFrom").asString());
  assertEquals(published,service.get(round,member,false,"test"));assertEquals(published,service.prepare(round,member,false,null,"test"));
  assertEquals(first.path("revisionId"),published.path("preferenceRevision"));
  assertThrows(CustomException.class,()->service.save(member,new PersonalBriefingPreferences.Save(choice,first.path("revisionId").asString())));
  assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM briefing_selected_generation_jobs WHERE created_at>now()-interval '1 minute'",Integer.class));
 }
 @Test void settingsSavedTodayCannotBackdateARealPersonalPublicationButDemoIsSeparate(){
  clock.now=Instant.parse("2026-10-30T06:00:00Z");var pref=service.save(member,new PersonalBriefingPreferences.Save(choice,null)).path("preference");
  assertEquals("not_scheduled",service.prepare(round,member,false,null,"test").path("status").asString());
  assertEquals("not_published",service.get(round,member,false,"test").path("status").asString());
  var preview=service.prepare(round,member,true,pref.path("revisionId").asString(),"test");assertEquals("demo",preview.path("mode").asString());assertEquals("ready",preview.path("status").asString());
  assertEquals(preview,service.prepare(round,member,true,pref.path("revisionId").asString(),"test"));
  assertEquals("not_published",service.get(round,member,false,"test").path("status").asString());
 }
 @Test void publicationDispatcherCreatesTheRoundWithoutAUserGenerationRequest(){
  service.save(member,new PersonalBriefingPreferences.Save(choice,null));clock.now=Instant.parse("2026-10-22T00:20:00Z");service.captureEligibility(member,clock.now);clock.now=Instant.parse("2026-10-22T01:00:00Z");
  new PersonalBriefingDeliveryScheduler(jdbc,service,clock).tick();
  var automatic=service.get(round,member,false,"test");assertEquals("ready",automatic.path("status").asString());
  assertEquals(3,automatic.path("selection").path("presentation").path("items").size());
  new PersonalBriefingDeliveryScheduler(jdbc,service,clock).tick();
  assertEquals(automatic,service.get(round,member,false,"test"));
 }
 @Test void backgroundInitializationNeedsNoPersonalPageVisit(){
  new PersonalBriefingDeliveryScheduler(jdbc,service,clock).tick();
  assertEquals(1,service.settings(member).path("preference").path("revision").asInt());
  assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM briefing_personal_deliveries WHERE member_id=?",Integer.class,member.memberId()));
 }
 @Test void missedEligibilityCannotInventThePastPortfolio(){
  clock.now=Instant.parse("2026-10-22T00:22:00Z");
  assertThrows(CustomException.class,()->service.captureEligibility(member,Instant.parse("2026-10-22T00:20:00Z")));
  assertEquals(0,jdbc.queryForObject("SELECT count(*) FROM briefing_personal_slot_eligibility WHERE member_id=?",Integer.class,member.memberId()));
 }
 @Test void finalResultCannotBeRewrittenInTheDatabase(){
  service.save(member,new PersonalBriefingPreferences.Save(choice,null));clock.now=Instant.parse("2026-10-22T00:20:00Z");service.captureEligibility(member,clock.now);clock.now=Instant.parse("2026-10-22T01:00:00Z");var row=service.prepare(round,member,false,null,"test");
  assertThrows(DataAccessException.class,()->jdbc.update("UPDATE briefing_personal_deliveries SET result_snapshot='{}'::jsonb WHERE id=?",row.path("id").asString()));
 }
 @Test void otherMemberCannotReadOrReuseTheDelivery(){
  var pref=service.save(member,new PersonalBriefingPreferences.Save(choice,null)).path("preference");clock.now=Instant.parse("2026-10-22T00:20:00Z");service.captureEligibility(member,clock.now);clock.now=Instant.parse("2026-10-22T01:00:00Z");service.prepare(round,member,false,null,"test");assertEquals("not_published",service.get(round,new MemberPrincipal("unrelated","s"),false,"test").path("status").asString());
  assertThrows(CustomException.class,()->service.prepare(round,member,true,"wrong-pref","test"));
 }
 static class MutableClock extends Clock {Instant now;MutableClock(String now){this.now=Instant.parse(now);}public ZoneId getZone(){return ZoneOffset.UTC;}public Clock withZone(ZoneId z){return this;}public Instant instant(){return now;}}
}
