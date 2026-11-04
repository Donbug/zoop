package com.zoop.briefing.scheduling;
import java.time.*;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
/** Prospective policy. Stored round clocks are never rewritten. */
@Component
public class BriefingSchedule {
 private static final ZoneId KST=ZoneId.of("Asia/Seoul");
 private final LocalTime morning,evening;private final LocalDate effective;private final OffsetDateTime testEvening;
 public BriefingSchedule(@Value("${zoop.briefing.morning-time:09:20}")String morning,
  @Value("${zoop.briefing.evening-time:17:30}")String evening,
  @Value("${zoop.briefing.schedule-effective-from:9999-12-31}")String effective,
  @Value("${zoop.briefing.test-evening-at:}")String testEvening){
  this.morning=LocalTime.parse(morning);this.evening=LocalTime.parse(evening);this.effective=LocalDate.parse(effective);
  this.testEvening=testEvening.isBlank()?null:OffsetDateTime.parse(testEvening);
  if(!this.morning.isBefore(this.evening)||this.morning.getSecond()!=0||this.evening.getSecond()!=0||this.morning.getNano()!=0||this.evening.getNano()!=0)throw new IllegalArgumentException("briefing schedule");
  if(this.testEvening!=null&&(!this.testEvening.getOffset().equals(ZoneOffset.ofHours(9))||this.testEvening.getSecond()!=0||this.testEvening.getNano()!=0||!this.testEvening.toLocalTime().isAfter(this.evening)))throw new IllegalArgumentException("briefing test clock");
 }
 public static BriefingSchedule legacy(){return new BriefingSchedule("09:20","17:30","9999-12-31","");}
 public Instant slot(LocalDate date,String edition){
  if(!List.of("morning","evening").contains(edition))throw new IllegalArgumentException("edition");
  if(edition.equals("evening")&&testEvening!=null&&date.equals(testEvening.toLocalDate()))return testEvening.toInstant();
  var time=date.isBefore(effective)?(edition.equals("morning")?LocalTime.of(9,20):LocalTime.of(17,30)):(edition.equals("morning")?morning:evening);
  return date.atTime(time).atZone(KST).toInstant();
 }
 public Instant today(Instant now,String edition){return slot(now.atZone(KST).toLocalDate(),edition);}
 public Instant start(Instant at,String edition){var day=at.atZone(KST).toLocalDate();return slot(edition.equals("morning")?day.minusDays(1):day,edition.equals("morning")?"evening":"morning");}
 public Instant next(Instant now){var day=now.atZone(KST).toLocalDate();for(var edition:List.of("morning","evening")){var s=slot(day,edition);if(s.isAfter(now))return s;}return slot(day.plusDays(1),"morning");}
 public List<String> times(Instant now){var day=next(now).atZone(KST).toLocalDate();return List.of(slot(day,"morning").atZone(KST).toLocalTime().toString(),slot(day,"evening").atZone(KST).toLocalTime().toString());}
 public boolean matches(Instant at,String edition){return today(at,edition).equals(at);}
}
