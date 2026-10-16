package com.zoop.briefing.market;

import java.time.*;
import java.util.Objects;
import tools.jackson.databind.node.ObjectNode;

/** Daily product rounds and trading sessions are different calendars. No round/lease is created here. */
public final class BriefingRoundClock {
    public static final LocalTime MORNING=LocalTime.of(9,20), EVENING=LocalTime.of(17,30);
    private BriefingRoundClock() {}
    public static LocalTime time(String edition) {
        return switch(edition) { case "morning"->MORNING; case "evening"->EVENING;
            default->throw new IllegalArgumentException("edition"); };
    }
    public static Instant scheduledAt(LocalDate date,String edition) { return date.atTime(time(edition)).atZone(TradingCalendar.KST).toInstant(); }
    public static Instant previousRound(LocalDate date,String edition) {
        return edition.equals("morning")?scheduledAt(date.minusDays(1),"evening"):scheduledAt(date,"morning");
    }
    public record Context(String roundId,LocalDate date,String edition,Instant scheduledAt,Instant from,
            boolean firstRound,TradingCalendar calendar) {
        public Context {
            if (roundId==null || roundId.isBlank()) throw new IllegalArgumentException("roundId");
            Objects.requireNonNull(calendar); Objects.requireNonNull(date);
            if (!BriefingRoundClock.scheduledAt(date,edition).equals(scheduledAt)
                    || (from==null)!=firstRound || (from!=null && !from.equals(previousRound(date,edition))))
                throw new IllegalArgumentException("Owned round window must match current daily schedule");
            if (calendar.reviewedAt().isAfter(scheduledAt)) throw new IllegalArgumentException("Calendar unavailable at cutoff");
        }
        public LocalDate expectedCloseDate() {
            var d=calendar.day(date);
            if (d==null) return null;
            if (edition.equals("evening") && d.open() && !scheduledAt.isBefore(d.closeInstant())) return date;
            return calendar.previous(date);
        }
        public String session() {
            var d=calendar.day(date);
            if (d==null) return "unknown";
            if (!d.open()) return "closed";
            var at=scheduledAt.atZone(TradingCalendar.KST).toLocalTime();
            if (at.isBefore(d.opensAt())) return "before_open";
            return at.isBefore(d.closesAt())?"regular":"after_regular";
        }
        public ObjectNode json() {
            var n=TradingCalendar.JSON.createObjectNode().put("roundId",roundId).put("date",date.toString())
                .put("edition",edition).put("scheduledAt",scheduledAt.toString()).put("sourceCutoff",scheduledAt.toString())
                .put("windowFrom",from==null?null:from.toString()).put("firstRound",firstRound)
                .put("marketSession",session()).put("calendarVersion",calendar.version()).put("calendarSha256",calendar.sha256())
                .put("calendarSource",calendar.source()).put("calendarAuthority",calendar.authority());
            var prev=calendar.previous(date); var next=calendar.next(date);
            var day=calendar.day(date);
            n.put("tradingDate",day!=null&&day.open()?date.toString():null);
            n.put("previousTradingDate",prev==null?null:prev.toString()).put("nextTradingDate",next==null?null:next.toString());
            n.put("calendarStatus",day==null?"unknown":prev==null||next==null?"partial":"known");
            return n;
        }
    }
}
