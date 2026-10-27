package com.zoop.chat.orchestrator;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Instant;
import java.time.LocalDate;
import java.util.Optional;

import org.junit.jupiter.api.Test;

/** Q05 periods written in a question, read in KST against when it was asked (decision of 2026-10-27). */
class ChatPeriodsTest {
    /** Tuesday 2026-10-27, 12:00 KST. */
    private static final Instant ASKED = Instant.parse("2026-10-27T03:00:00Z");

    @Test
    void daysWeeksAndMonthsAreKstCalendarRanges() {
        assertPeriod("2026-10-27", "2026-10-27", "오늘 바뀐 관계");
        assertPeriod("2026-10-26", "2026-10-26", "어제와 비교해");
        assertPeriod("2026-10-25", "2026-10-25", "그저께 지도");
        assertPeriod("2026-10-19", "2026-10-25", "지난주 대비 달라진 관계는?");
        assertPeriod("2026-10-19", "2026-10-25", "저번 주랑 비교");
        assertPeriod("2026-10-26", "2026-10-27", "이번 주에 생긴 사건");
        assertPeriod("2026-09-01", "2026-09-30", "지난달과 비교해 줘");
        assertPeriod("2026-10-01", "2026-10-27", "이번 달 변화");
    }

    @Test
    void relativeAndWrittenDates() {
        assertPeriod("2026-10-24", "2026-10-24", "3일 전 지도와 비교");
        assertPeriod("2026-10-20", "2026-10-20", "일주일 전과 비교");
        assertPeriod("2026-10-13", "2026-10-13", "두 주 전과 비교");
        assertPeriod("2026-09-27", "2026-09-27", "한 달 전이랑 뭐가 달라?");
        assertPeriod("2026-10-21", "2026-10-27", "최근 7일 동안");
        assertPeriod("2026-10-21", "2026-10-27", "최근 일주일 사이");
        assertPeriod("2026-10-01", "2026-10-01", "10월 1일 이후 바뀐 것");
        assertPeriod("2026-10-01", "2026-10-01", "2026-10-01 이후");
        assertPeriod("2025-12-25", "2025-12-25", "12월 25일과 비교", "a month and day later than today is last year's");
    }

    @Test
    void severalExpressionsSpanFromTheEarliestToTheLatest() {
        var both = ChatPeriods.parse("지난주와 이번 주 지도에서 달라진 관계는?", ASKED).orElseThrow();
        assertEquals(LocalDate.parse("2026-10-19"), both.start());
        assertEquals(LocalDate.parse("2026-10-27"), both.end());
        assertEquals("지난주 · 이번 주", both.expression());
        assertEquals(Instant.parse("2026-10-18T15:00:00Z"), both.startInstant(), "KST midnight");
    }

    @Test
    void unknownFutureOrImpossibleWordsAreNoPeriod() {
        assertTrue(ChatPeriods.parse("지도에서 달라진 관계는?", ASKED).isEmpty());
        assertTrue(ChatPeriods.parse("2026-10-30과 비교", ASKED).isEmpty(), "after the question");
        assertTrue(ChatPeriods.parse("2026-02-30과 비교", ASKED).isEmpty(), "no such day");
        assertTrue(ChatPeriods.parse("예전과 비교해", ASKED).isEmpty());
    }

    private static void assertPeriod(String start, String end, String text, String... why) {
        Optional<ChatPeriods.Period> period = ChatPeriods.parse(text, ASKED);
        String message = text + (why.length > 0 ? " (" + why[0] + ")" : "");
        assertTrue(period.isPresent(), message);
        assertEquals(LocalDate.parse(start), period.get().start(), message);
        assertEquals(LocalDate.parse(end), period.get().end(), message);
    }
}
