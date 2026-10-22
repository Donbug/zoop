package com.zoop.company.market;

import com.zoop.company.market.dto.CompanyPriceResponse.Point;
import java.time.DayOfWeek;
import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.time.temporal.TemporalAdjusters;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.function.Function;

/**
 * Aggregates provider bars into the contract's fixed chart resolution (x-zoop.chartResolution): open of the first bar,
 * high/low over all, close of the last, volume summed. Never splits a bar or fills an empty bucket.
 */
final class PriceBars {
    private PriceBars() { }

    /** A provider bar that starts at {@code start}. */
    record Bar(Instant start, double open, double high, double low, double close, Double volume) { }

    /** 5m/1h buckets: the bar start floored to the bucket size (whole-hour offsets keep this on the local clock). */
    static List<Point> byInterval(List<Bar> bars, long seconds, ZoneId zone) {
        return group(bars, b -> Instant.ofEpochSecond(Math.floorDiv(b.start().getEpochSecond(), seconds) * seconds), zone);
    }

    /** 1wk buckets: weeks starting on Monday of the bar's exchange-local date. */
    static List<Point> byWeek(List<Bar> bars, ZoneId zone) {
        return group(bars, b -> weekStart(b.start(), zone), zone);
    }

    static Instant weekStart(Instant at, ZoneId zone) {
        return at.atZone(zone).toLocalDate().with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
                .atStartOfDay(zone).toInstant();
    }

    static List<Point> asIs(List<Bar> bars, ZoneId zone) {
        return group(bars, Bar::start, zone);
    }

    private static List<Point> group(List<Bar> bars, Function<Bar, Instant> bucket, ZoneId zone) {
        Map<Instant, List<Bar>> buckets = new TreeMap<>();
        for (Bar bar : bars) buckets.computeIfAbsent(bucket.apply(bar), k -> new ArrayList<>()).add(bar);
        List<Point> points = new ArrayList<>();
        buckets.forEach((start, group) -> {
            group.sort(Comparator.comparing(Bar::start));
            double high = group.stream().mapToDouble(Bar::high).max().orElseThrow();
            double low = group.stream().mapToDouble(Bar::low).min().orElseThrow();
            // One unknown volume makes the bucket's volume unknown; it is never counted as zero.
            Double volume = group.stream().anyMatch(b -> b.volume() == null) ? null
                    : group.stream().mapToDouble(Bar::volume).sum();
            points.add(new Point(start.atZone(zone).format(DateTimeFormatter.ISO_OFFSET_DATE_TIME), group.getFirst().open(), high, low,
                    group.getLast().close(), volume));
        });
        return points;
    }
}
