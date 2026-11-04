package com.zoop.briefing.scheduling;
import static org.junit.jupiter.api.Assertions.*;
import java.time.*;
import org.junit.jupiter.api.Test;
class BriefingScheduleTest {
 final BriefingSchedule policy=new BriefingSchedule("08:30","17:30","2026-11-05","2026-11-04T22:00:00+09:00");
 @Test void prospectivePolicyRetainsOldRoundsAndTestDoesNotRepeat(){
  assertEquals(Instant.parse("2026-11-04T00:20:00Z"),policy.slot(LocalDate.parse("2026-11-04"),"morning"));
  assertEquals(Instant.parse("2026-11-04T13:00:00Z"),policy.next(Instant.parse("2026-11-04T12:00:00Z")));
  assertEquals(Instant.parse("2026-11-04T23:30:00Z"),policy.next(Instant.parse("2026-11-04T13:00:00Z")));
  assertEquals(Instant.parse("2026-11-05T08:30:00Z"),policy.slot(LocalDate.parse("2026-11-05"),"evening"));
 }
 @Test void comparisonWindowFollowsActualPreviousTestAndMorningSlots(){
  assertEquals(Instant.parse("2026-11-04T13:00:00Z"),policy.start(Instant.parse("2026-11-04T23:30:00Z"),"morning"));
  assertEquals(Instant.parse("2026-11-04T23:30:00Z"),policy.start(Instant.parse("2026-11-05T08:30:00Z"),"evening"));
  assertTrue(policy.matches(Instant.parse("2026-11-04T23:30:00Z"),"morning"));
  assertFalse(policy.matches(Instant.parse("2026-11-05T00:20:00Z"),"morning"));
 }
 @Test void invalidClockDoesNotFallBackSilently(){assertThrows(IllegalArgumentException.class,()->new BriefingSchedule("18:30","17:30","2026-11-05",""));}
}
