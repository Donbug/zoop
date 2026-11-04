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
 private final PersonalBriefingAudience audience;
 private String afterMember="";
 private final com.zoop.briefing.scheduling.BriefingSchedule schedule;
 public PersonalBriefingDeliveryScheduler(JdbcTemplate jdbc,PersonalBriefingPreferences service,Clock clock,PersonalBriefingAudience audience){this(jdbc,service,clock,audience,com.zoop.briefing.scheduling.BriefingSchedule.legacy());}
 @org.springframework.beans.factory.annotation.Autowired
 public PersonalBriefingDeliveryScheduler(JdbcTemplate jdbc,PersonalBriefingPreferences service,Clock clock,PersonalBriefingAudience audience,com.zoop.briefing.scheduling.BriefingSchedule schedule){this.jdbc=jdbc;this.service=service;this.clock=clock;this.audience=audience;this.schedule=schedule;}
 private String cohort(){return String.join(",",java.util.Collections.nCopies(audience.memberIds().size(),"?"));}
 @Scheduled(cron="0 20 9 * * *",zone="Asia/Seoul") public void captureMorning(){capture("morning");}
 @Scheduled(cron="0 30 17 * * *",zone="Asia/Seoul") public void captureEvening(){capture("evening");}
 public void capture(String edition){
  if(audience.memberIds().isEmpty())return;
  var slot=schedule.today(clock.instant(),edition);
  for(String member:jdbc.query("SELECT id FROM members WHERE status='active' AND id IN ("+cohort()+") ORDER BY id",(r,i)->r.getString(1),audience.memberIds().toArray()))
   if(audience.automatic(member))
   try{service.captureEligibility(new MemberPrincipal(member,"scheduled"),slot);}catch(RuntimeException e){LoggerFactory.getLogger(getClass()).warn("Personal briefing slot unobserved: {}",e.getClass().getSimpleName());}
 }
 @Scheduled(fixedDelayString="${zoop.briefing.personal-scheduler-delay-ms:30000}")
 public void tick(){
  if(audience.memberIds().isEmpty())return;
  // Polling also handles an explicit one-day test clock without an extra recurring cron.
  var now=clock.instant();for(var edition:java.util.List.of("morning","evening")){var slot=schedule.today(now,edition);if(!now.isBefore(slot)&&now.isBefore(slot.plusSeconds(120)))capture(edition);}
  // Initialize ahead of the cutoff, even if the member never opens the briefing page.
  var members=jdbc.query("""
   SELECT m.id FROM members m WHERE m.status='active' AND m.id COLLATE "C">? COLLATE "C"
   AND m.id IN (%s)
   AND NOT EXISTS(SELECT 1 FROM briefing_personal_preferences p WHERE p.member_id=m.id AND p.scope='scheduled')
   ORDER BY m.id COLLATE "C" LIMIT 100
   """.formatted(cohort()),(r,i)->r.getString(1),arguments(afterMember));
  for(String member:members)if(audience.automatic(member))try{service.initialize(new MemberPrincipal(member,"scheduled"));}catch(RuntimeException e){LoggerFactory.getLogger(getClass()).warn("Personal briefing defaults deferred: {}",e.getClass().getSimpleName());}
  afterMember=members.size()<100?"":members.getLast();
  var due=jdbc.query("""
   SELECT DISTINCT p.member_id,r.id,r.scheduled_at FROM briefing_rounds r
   JOIN briefing_personal_preferences p ON p.scope='scheduled' AND p.effective_from<=r.scheduled_at AND p.created_at<r.scheduled_at
   JOIN members m ON m.id=p.member_id AND m.status='active'
   JOIN briefing_personal_slot_eligibility e ON e.member_id=p.member_id AND e.scheduled_at=r.scheduled_at AND e.has_companies IS TRUE
   WHERE r.status='published' AND r.scheduled_at<=? AND EXISTS(SELECT 1 FROM briefing_personal_pools pool WHERE pool.round_id=r.id)
   AND p.member_id IN (%s)
   AND NOT EXISTS(SELECT 1 FROM briefing_personal_deliveries d WHERE d.member_id=p.member_id AND d.round_id=r.id AND d.mode='scheduled')
   ORDER BY r.scheduled_at,p.member_id,r.id LIMIT 20
   """.formatted(cohort()),(r,i)->new String[]{r.getString(1),r.getString(2)},arguments(Timestamp.from(clock.instant())));
  for(var row:due)if(audience.automatic(row[0]))try{service.prepare(row[1],new MemberPrincipal(row[0],"scheduled"),false,null,"personal-scheduler");}catch(RuntimeException e){LoggerFactory.getLogger(getClass()).warn("Personal briefing preparation deferred: {}",e.getClass().getSimpleName());}
  for(var row:jdbc.query("SELECT id,member_id FROM briefing_personal_deliveries WHERE status='generating' AND result_snapshot IS NULL AND member_id IN ("+cohort()+") ORDER BY created_at LIMIT 20",(r,i)->new String[]{r.getString(1),r.getString(2)},audience.memberIds().toArray()))
   if(audience.automatic(row[1]))try{service.complete(row[0]);}catch(RuntimeException e){LoggerFactory.getLogger(getClass()).warn("Personal briefing completion deferred: {}",e.getClass().getSimpleName());}
 }
 private Object[] arguments(Object first){var args=new java.util.ArrayList<Object>();args.add(first);args.addAll(audience.memberIds());return args.toArray();}
}
