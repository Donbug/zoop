package com.zoop.briefing.personal;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.*;
import java.time.*;
import java.sql.Timestamp;
import org.slf4j.LoggerFactory;
/** Runs after a common publication/pool exists; never backdates a setting or dispatches from a page read. */
@Configuration
@EnableScheduling
@ConditionalOnProperty(name="zoop.briefing.personal-scheduler-enabled",havingValue="true")
public class PersonalBriefingDeliveryScheduler {
 private final JdbcTemplate jdbc;private final PersonalBriefingPreferences service;private final Clock clock;
 private String afterMember="";
 public PersonalBriefingDeliveryScheduler(JdbcTemplate jdbc,PersonalBriefingPreferences service,Clock clock){this.jdbc=jdbc;this.service=service;this.clock=clock;}
 @Scheduled(cron="0 20 9 * * *",zone="Asia/Seoul") public void captureMorning(){capture("morning");}
 @Scheduled(cron="0 30 17 * * *",zone="Asia/Seoul") public void captureEvening(){capture("evening");}
 public void capture(String edition){
  var slot=com.zoop.briefing.scheduling.CommonBriefingScheduler.scheduledAt(clock.instant(),edition);
  for(String member:jdbc.query("SELECT id FROM members WHERE status='active' ORDER BY id",(r,i)->r.getString(1)))
   try{service.captureEligibility(new MemberPrincipal(member,"scheduled"),slot);}catch(RuntimeException e){LoggerFactory.getLogger(getClass()).warn("Personal briefing slot unobserved: {}",e.getClass().getSimpleName());}
 }
 @Scheduled(fixedDelayString="${zoop.briefing.personal-scheduler-delay-ms:30000}")
 public void tick(){
  // Initialize ahead of the cutoff, even if the member never opens the briefing page.
  var members=jdbc.query("""
   SELECT m.id FROM members m WHERE m.status='active' AND m.id COLLATE "C">? COLLATE "C"
   AND NOT EXISTS(SELECT 1 FROM briefing_personal_preferences p WHERE p.member_id=m.id)
   ORDER BY m.id COLLATE "C" LIMIT 100
   """,(r,i)->r.getString(1),afterMember);
  for(String member:members)try{service.initialize(new MemberPrincipal(member,"scheduled"));}catch(RuntimeException e){LoggerFactory.getLogger(getClass()).warn("Personal briefing defaults deferred: {}",e.getClass().getSimpleName());}
  afterMember=members.size()<100?"":members.getLast();
  var due=jdbc.query("""
   SELECT DISTINCT p.member_id,r.id,r.scheduled_at FROM briefing_rounds r
   JOIN briefing_personal_preferences p ON p.effective_from<=r.scheduled_at AND p.created_at<r.scheduled_at
   JOIN members m ON m.id=p.member_id AND m.status='active'
   JOIN briefing_personal_slot_eligibility e ON e.member_id=p.member_id AND e.scheduled_at=r.scheduled_at AND e.has_companies IS TRUE
   WHERE r.status='published' AND r.scheduled_at<=? AND EXISTS(SELECT 1 FROM briefing_personal_pools pool WHERE pool.round_id=r.id)
   AND NOT EXISTS(SELECT 1 FROM briefing_personal_deliveries d WHERE d.member_id=p.member_id AND d.round_id=r.id AND d.mode='scheduled')
   ORDER BY r.scheduled_at,p.member_id,r.id LIMIT 20
   """,(r,i)->new String[]{r.getString(1),r.getString(2)},Timestamp.from(clock.instant()));
  for(var row:due)try{service.prepare(row[1],new MemberPrincipal(row[0],"scheduled"),false,null,"personal-scheduler");}catch(RuntimeException e){LoggerFactory.getLogger(getClass()).warn("Personal briefing preparation deferred: {}",e.getClass().getSimpleName());}
  for(String id:jdbc.query("SELECT id FROM briefing_personal_deliveries WHERE status='generating' AND result_snapshot IS NULL ORDER BY created_at LIMIT 20",(r,i)->r.getString(1)))
   try{service.complete(id);}catch(RuntimeException e){LoggerFactory.getLogger(getClass()).warn("Personal briefing completion deferred: {}",e.getClass().getSimpleName());}
 }
}
