package com.zoop.graph.importer;

import java.time.DateTimeException;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.Year;
import java.time.YearMonth;
import java.time.ZoneOffset;

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
