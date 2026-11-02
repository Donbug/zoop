package com.zoop.briefing.personal;
import com.zoop.briefing.scheduling.CommonBriefingScheduler;
import java.time.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import org.springframework.jdbc.core.JdbcTemplate;
class CommonBriefingSchedulerTest {
 @Test void kstMorningAndEveningUseExactUtcCutoffs(){
  var now=Instant.parse("2026-10-30T01:00:00Z");
  assertEquals(Instant.parse("2026-10-30T00:20:00Z"),CommonBriefingScheduler.scheduledAt(now,"morning"));
  assertEquals(Instant.parse("2026-10-30T08:30:00Z"),CommonBriefingScheduler.scheduledAt(now,"evening"));
 }
 @Test void cannotCreateFutureSlot(){var jdbc=mock(JdbcTemplate.class);new CommonBriefingScheduler(jdbc,Clock.fixed(Instant.parse("2026-10-30T00:19:59Z"),ZoneOffset.UTC)).reconcileToday();verifyNoInteractions(jdbc);}
 @Test void midnightBoundaryUsesKoreanDate(){assertEquals(Instant.parse("2026-10-31T00:20:00Z"),CommonBriefingScheduler.scheduledAt(Instant.parse("2026-10-30T15:01:00Z"),"morning"));}
}
