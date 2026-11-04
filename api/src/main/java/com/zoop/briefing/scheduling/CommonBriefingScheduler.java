package com.zoop.briefing.scheduling;
import java.time.*;
import java.sql.Timestamp;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.*;
/** Server clock -> idempotent common producer queue. No user-page or model invocation. */
@Configuration
@EnableScheduling
@ConditionalOnProperty(name="zoop.briefing.common-scheduler-enabled",havingValue="true")
public class CommonBriefingScheduler {
 private final JdbcTemplate jdbc;private final Clock clock;private final BriefingSchedule schedule;
 public CommonBriefingScheduler(JdbcTemplate jdbc,Clock clock){this(jdbc,clock,BriefingSchedule.legacy());}
 @org.springframework.beans.factory.annotation.Autowired public CommonBriefingScheduler(JdbcTemplate jdbc,Clock clock,BriefingSchedule schedule){this.jdbc=jdbc;this.clock=clock;this.schedule=schedule;}
 @Scheduled(cron="0 20 9 * * *",zone="Asia/Seoul") public void morning(){enqueue("morning");}
 @Scheduled(cron="0 30 17 * * *",zone="Asia/Seoul") public void evening(){enqueue("evening");}
 @Scheduled(fixedDelayString="${zoop.briefing.common-scheduler-delay-ms:30000}")
 public void reconcileToday(){enqueue("morning");enqueue("evening");}
 public static Instant scheduledAt(Instant now,String edition){
  if(!edition.equals("morning")&&!edition.equals("evening"))throw new IllegalArgumentException("edition");
  return now.atZone(ZoneId.of("Asia/Seoul")).toLocalDate().atTime(edition.equals("morning")?LocalTime.of(9,20):LocalTime.of(17,30)).atZone(ZoneId.of("Asia/Seoul")).toInstant();
 }
 public void enqueue(String edition){
  var now=clock.instant();var slot=schedule.today(now,edition);if(slot.isAfter(now))return;
  var date=slot.atZone(ZoneId.of("Asia/Seoul")).toLocalDate();
  var previous=schedule.start(slot,edition);
  jdbc.update("INSERT INTO briefing_common_schedule_jobs(id,round_date,edition,scheduled_at,window_from) VALUES (?,?,?,?,?) ON CONFLICT(round_date,edition) DO NOTHING",
   "brf-"+date+"-"+edition,date,edition,Timestamp.from(slot),Timestamp.from(previous));
 }
}
