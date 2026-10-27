package com.zoop.chat.orchestrator;

import java.time.DayOfWeek;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.temporal.TemporalAdjusters;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Periods written in a question (decision of 2026-10-27, Q05): a fixed set of Korean expressions, read deterministically in
 * KST against when the question was asked, never by a model. Several expressions make one period from the earliest start to
 * the latest end ("지난주와 이번 주" is last Monday to today). An expression it does not know is not a period; a date
 * after the question is ignored.
 *
 * <ul>
 * <li>Days: {@code 오늘}, {@code 어제}, {@code 그제}/{@code 그저께}, {@code YYYY-MM-DD}, {@code [YYYY년] M월 D일} (a month and
 * day without a year that would be later than the question is last year's).</li>
 * <li>Weeks and months (Monday-based weeks): {@code 이번 주}, {@code 지난주}/{@code 저번 주}, {@code 이번 달},
 * {@code 지난달}/{@code 저번 달}.</li>
 * <li>Relative: {@code N일 전}, {@code N주 전}, {@code 일주일 전}, {@code N달 전}/{@code N개월 전} (that day), and
 * {@code 최근 N일}/{@code 최근 N주}/{@code 최근 일주일}/{@code 최근 N달} (up to today). N is digits or 한·두·세.</li>
 * </ul>
 */
public final class ChatPeriods {
    static final ZoneId KST = ZoneId.of("Asia/Seoul");

    /** Inclusive KST days and the words they came from, as the question wrote them. */
    public record Period(LocalDate start, LocalDate end, String expression) {
        /** The first moment of the period: its first day's KST midnight. */
        public Instant startInstant() {
            return start.atStartOfDay(KST).toInstant();
        }
    }

    /** A count: digits or 한·두·세. */
    private static final String N = "\\d{1,3}|한|두|세";
    private static final Pattern EXPRESSION = Pattern.compile(String.join("|",
            "(?<iso>(?<isoY>\\d{4})-(?<isoM>\\d{2})-(?<isoD>\\d{2}))",
            "(?<md>(?:(?<mdY>\\d{4})\\s*년\\s*)?(?<mdM>\\d{1,2})\\s*월\\s*(?<mdD>\\d{1,2})\\s*일)",
            "(?<recentWeek>최근\\s*일주일)",
            "(?<recent>최근\\s*(?<recentN>" + N + ")\\s*(?<recentU>일|주일|주|달|개월))",
            "(?<weekAgo>일주일\\s*전)",
            "(?<ago>(?<agoN>" + N + ")\\s*(?<agoU>일|주일|주|달|개월)\\s*전)",
            "(?<today>오늘)", "(?<yesterday>어제)", "(?<twoDays>그제|그저께)",
            "(?<thisWeek>이번\\s*주)", "(?<lastWeek>지난\\s*주|저번\\s*주)",
            "(?<thisMonth>이번\\s*달)", "(?<lastMonth>지난\\s*달|저번\\s*달)"));

    private ChatPeriods() {
    }

    /** The period the text writes, read against {@code askedAt}; empty when it writes none this class knows. */
    public static Optional<Period> parse(String text, Instant askedAt) {
        LocalDate today = askedAt.atZone(KST).toLocalDate();
        Matcher m = EXPRESSION.matcher(text);
        LocalDate start = null;
        LocalDate end = null;
        List<String> words = new ArrayList<>();
        while (m.find()) {
            LocalDate[] range = range(m, today);
            if (range == null || range[0].isAfter(today)) continue;
            if (range[1].isAfter(today)) range[1] = today;
            start = start == null || range[0].isBefore(start) ? range[0] : start;
            end = end == null || range[1].isAfter(end) ? range[1] : end;
            words.add(m.group());
        }
        return start == null ? Optional.empty() : Optional.of(new Period(start, end, String.join(" · ", words)));
    }

    private static LocalDate[] range(Matcher m, LocalDate today) {
        if (m.group("iso") != null) {
            return day(date(m.group("isoY"), m.group("isoM"), m.group("isoD"), today));
        }
        if (m.group("md") != null) return day(date(m.group("mdY"), m.group("mdM"), m.group("mdD"), today));
        if (m.group("recentWeek") != null) return new LocalDate[] {today.minusDays(6), today};
        if (m.group("recent") != null) {
            LocalDate from = back(today, number(m.group("recentN")), m.group("recentU"));
            return new LocalDate[] {from.plusDays(1), today};
        }
        if (m.group("weekAgo") != null) return day(today.minusWeeks(1));
        if (m.group("ago") != null) return day(back(today, number(m.group("agoN")), m.group("agoU")));
        if (m.group("today") != null) return day(today);
        if (m.group("yesterday") != null) return day(today.minusDays(1));
        if (m.group("twoDays") != null) return day(today.minusDays(2));
        LocalDate monday = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY));
        if (m.group("thisWeek") != null) return new LocalDate[] {monday, today};
        if (m.group("lastWeek") != null) return new LocalDate[] {monday.minusWeeks(1), monday.minusDays(1)};
        LocalDate first = today.withDayOfMonth(1);
        if (m.group("thisMonth") != null) return new LocalDate[] {first, today};
        return new LocalDate[] {first.minusMonths(1), first.minusDays(1)};
    }

    private static LocalDate[] day(LocalDate date) {
        return date == null ? null : new LocalDate[] {date, date};
    }

    /** A written date; without a year, the latest one not after today. Null for a date that does not exist. */
    private static LocalDate date(String year, String month, String day, LocalDate today) {
        try {
            int m = Integer.parseInt(month);
            int d = Integer.parseInt(day);
            if (year != null) return LocalDate.of(Integer.parseInt(year), m, d);
            LocalDate date = LocalDate.of(today.getYear(), m, d);
            return date.isAfter(today) ? date.minusYears(1) : date;
        } catch (java.time.DateTimeException | NumberFormatException invalid) {
            return null;
        }
    }

    private static LocalDate back(LocalDate today, int n, String unit) {
        return switch (unit) {
            case "일" -> today.minusDays(n);
            case "주", "주일" -> today.minusWeeks(n);
            default -> today.minusMonths(n);
        };
    }

    private static int number(String n) {
        return switch (n) {
            case "한" -> 1;
            case "두" -> 2;
            case "세" -> 3;
            default -> Integer.parseInt(n);
        };
    }
}
