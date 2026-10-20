package com.zoop.graph.importer;

import java.time.DateTimeException;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.Year;
import java.time.YearMonth;
import java.time.ZoneOffset;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Exact time handling of the import. A value is written to the snapshot only with the precision the bundle states: an instant
 * stays an instant (normalized to UTC), a calendar date stays a date and is never given a time or a zone, a year or a month
 * stays a year or a month, and an unknown value stays unknown. A form that cannot be written without guessing is
 * {@code temporal_unsupported}; nothing is repaired, widened or invented.
 */
final class HandoffTime {
    private HandoffTime() {
    }

    /** An ISO-8601 date-time with an offset ({@code Z} or {@code +hh:mm}), as the S2-1 ledger and the S3 ledger write it. */
    static Instant instant(String value) {
        try {
            return OffsetDateTime.parse(value).toInstant();
        } catch (DateTimeException | NullPointerException error) {
            throw unsupported();
        }
    }

    /** The same instant in UTC, the form every snapshot time uses. */
    static String instantText(String value) {
        return instant(value).toString();
    }

    /** A calendar date in its one canonical spelling {@code YYYY-MM-DD}. */
    static String day(String value) {
        try {
            LocalDate parsed = LocalDate.parse(value);
            if (!parsed.toString().equals(value) || value.length() != 10) {
                throw unsupported();
            }
            return value;
        } catch (DateTimeException | NullPointerException error) {
            throw unsupported();
        }
    }

    /** A day or an unknown ({@code null}) boundary of a validity window; any other form is unsupported. */
    static String dayOrNull(String value) {
        return value == null ? null : day(value);
    }

    /**
     * The event time exactly as the snapshot stores it for the stated precision: {@code unknown} has no value, a year is
     * {@code YYYY}, a month {@code YYYY-MM}, a day {@code YYYY-MM-DD} and a datetime a UTC instant.
     */
    static String eventTime(String value, String precision) {
        try {
            return switch (precision) {
                case "unknown" -> {
                    if (value != null) {
                        throw unsupported();
                    }
                    yield null;
                }
                case "year" -> {
                    if (value == null || value.length() != 4 || !Year.parse(value).toString().equals(value)) {
                        throw unsupported();
                    }
                    yield value;
                }
                case "month" -> {
                    if (value == null || !YearMonth.parse(value).toString().equals(value)) {
                        throw unsupported();
                    }
                    yield value;
                }
                case "day" -> day(value);
                case "datetime" -> instantText(value);
                default -> throw unsupported();
            };
        } catch (DateTimeException | NullPointerException error) {
            throw unsupported();
        }
    }

    private static final Pattern MENTION_TIME = Pattern.compile(
            "([0-9]{4})(?:-([0-9]{2})(?:-([0-9]{2})(?:T([0-9]{2}):([0-9]{2})(?::([0-9]{2})(?:\\.[0-9]{1,9})?)?(Z|[+-][0-9]{2}:[0-9]{2}))?)?)?");

    /**
     * Checks the {@code eventTime} of an ORIGINAL mention against the precision it states, and never rewrites it. The grammar is the
     * one the producer's {@code mention_time_precision} implements by hand (shared vectors:
     * {@code graph-handoff/mention-time-vectors.json}): ASCII {@code YYYY}, {@code YYYY-MM}, {@code YYYY-MM-DD} and
     * {@code YYYY-MM-DDTHH:MM[:SS[.f{1,9}]](Z|+HH:MM|-HH:MM)} with an uppercase {@code T} and {@code Z} and an offset required. It is the
     * set both sides already accepted: no library parser decides, so a form only one side takes (ISO week, ordinal or compact dates,
     * an offset without a colon, a comma fraction) is {@code temporal_unsupported}. Offset hours stop at 18 (the {@code ZoneOffset}
     * range) and year {@code 0000} is a bare year only (a calendar date needs year 1 or later). A null value is {@code unknown} only.
     *
     * @throws GraphHandoffException {@code temporal_unsupported} for anything else, or when the stated precision is not the one the
     *         format has
     */
    static void mentionEventTime(String value, String precision) {
        if (value == null) {
            if (!"unknown".equals(precision)) {
                throw unsupported();
            }
            return;
        }
        Matcher found = MENTION_TIME.matcher(value);
        if (!found.matches()) {
            throw unsupported();
        }
        if (!mentionPrecision(found).equals(precision)) {
            throw unsupported();
        }
    }

    private static String mentionPrecision(Matcher found) {
        String year = found.group(1);
        if (found.group(2) == null) {
            return "year";
        }
        int month = Integer.parseInt(found.group(2));
        if (year.equals("0000") || month < 1 || month > 12) {
            throw unsupported();
        }
        if (found.group(3) == null) {
            return "month";
        }
        int dayOfMonth = Integer.parseInt(found.group(3));
        if (dayOfMonth < 1 || dayOfMonth > YearMonth.of(Integer.parseInt(year), month).lengthOfMonth()) {
            throw unsupported();
        }
        if (found.group(4) == null) {
            return "day";
        }
        if (Integer.parseInt(found.group(4)) > 23 || Integer.parseInt(found.group(5)) > 59
                || (found.group(6) != null && Integer.parseInt(found.group(6)) > 59)) {
            throw unsupported();
        }
        String offset = found.group(7);
        if (!offset.equals("Z")) {
            int hours = Integer.parseInt(offset.substring(1, 3));
            int minutes = Integer.parseInt(offset.substring(4, 6));
            if (minutes > 59 || hours * 60 + minutes > 18 * 60) {
                throw unsupported();
            }
        }
        return "datetime";
    }

    /**
     * When a published value counts as published, in the one comparable form the snapshot filter uses: an instant counts from
     * itself, a date counts once the last time zone has left that day (UTC-12 midnight of the next day, which is 12:00 UTC).
     */
    static Instant effective(String published) {
        if (published.length() == 10) {
            return LocalDate.parse(published).plusDays(1).atTime(12, 0).toInstant(ZoneOffset.UTC);
        }
        return Instant.parse(published);
    }

    private static GraphHandoffException unsupported() {
        return new GraphHandoffException(GraphHandoffFailure.TEMPORAL_UNSUPPORTED);
    }
}
