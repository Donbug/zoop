package com.zoop.briefing.market;

import java.time.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class TradingCalendarTest {
    @Test void weekendAndDailyRoundWindowsAreDifferent() {
        var c=MarketSnapshotTest.calendar();
        assertEquals(LocalDate.of(2026,10,19),c.next(LocalDate.of(2026,10,16)));
        assertEquals(LocalDate.of(2026,10,16),c.previous(LocalDate.of(2026,10,19)));
        assertEquals(Instant.parse("2026-10-18T08:30:00Z"),BriefingRoundClock.previousRound(LocalDate.of(2026,10,19),"morning"));
        assertEquals(Instant.parse("2026-10-19T00:20:00Z"),BriefingRoundClock.scheduledAt(LocalDate.of(2026,10,19),"morning"));
    }
    @Test void unknownCoverageNeverUsesWeekdayGuessForNextSession() {
        var c=MarketSnapshotTest.calendar();
        assertNull(c.next(LocalDate.of(2026,10,20))); assertNull(c.day(LocalDate.of(2026,10,21)));
        var date=LocalDate.of(2026,10,21);
        var context=new BriefingRoundClock.Context("r",date,"morning",BriefingRoundClock.scheduledAt(date,"morning"),null,true,c);
        assertEquals("unknown",context.session()); assertNull(context.expectedCloseDate());
    }
    @Test void closedDateKeepsPreviousCloseDateWithoutCallingItToday() {
        var c=MarketSnapshotTest.calendar(); var date=LocalDate.of(2026,10,18);
        var context=new BriefingRoundClock.Context("r",date,"morning",BriefingRoundClock.scheduledAt(date,"morning"),null,true,c);
        assertEquals("closed",context.session()); assertEquals(LocalDate.of(2026,10,16),context.expectedCloseDate());
        assertTrue(context.json().path("tradingDate").isNull());
    }
    @Test void specialOpeningUsesReviewedHoursRatherThanRoundName() {
        var raw=TradingCalendar.JSON.createObjectNode().put("version","special")
            .put("source","https://example.test/special").put("authority","development_reviewed").put("reviewedAt","2026-10-01T00:00:00Z");
        raw.putArray("days").addObject().put("date","2026-10-15").put("open",true).put("opensAt","10:00").put("closesAt","16:30");
        var c=TradingCalendar.parse(TradingCalendar.JSON.writeValueAsBytes(raw));
        var date=LocalDate.of(2026,10,15);
        var context=new BriefingRoundClock.Context("r",date,"morning",BriefingRoundClock.scheduledAt(date,"morning"),null,true,c);
        assertEquals("before_open",context.session());
    }
    @Test void laterCalendarAndGuessedMissingRoundWindowAreRejected() {
        var c=MarketSnapshotTest.calendar(); var date=LocalDate.of(2026,10,15);
        assertThrows(IllegalArgumentException.class,()->new BriefingRoundClock.Context("r",date,"morning",
            BriefingRoundClock.scheduledAt(date,"morning"),Instant.parse("2026-10-13T08:30:00Z"),false,c));
        assertThrows(IllegalArgumentException.class,()->new BriefingRoundClock.Context("r",date,"morning",
            BriefingRoundClock.scheduledAt(date,"morning"),null,false,c));
    }
    @Test void malformedOrDuplicateCalendarCannotSilentlyChangeTheSession() {
        String start="{\"version\":\"v\",\"authority\":\"development_reviewed\",\"source\":\"https://example.test\",\"reviewedAt\":\"2026-10-01T00:00:00Z\",\"days\":[";
        String row="{\"date\":\"2026-10-15\",\"open\":true,\"opensAt\":\"16:00\",\"closesAt\":\"15:00\"}";
        assertThrows(IllegalArgumentException.class,()->TradingCalendar.parse((start+row+"]}").getBytes()));
        String closed="{\"date\":\"2026-10-15\",\"open\":false}";
        assertThrows(IllegalArgumentException.class,()->TradingCalendar.parse((start+closed+","+closed+"]}").getBytes()));
    }
}
