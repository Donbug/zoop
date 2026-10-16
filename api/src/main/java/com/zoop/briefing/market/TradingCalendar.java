package com.zoop.briefing.market;

import com.zoop.briefing.input.FileBriefingInputStore;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.*;
import java.util.*;
import tools.jackson.core.StreamReadFeature;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** Explicit reviewed dates, including closed dates. Missing dates never mean weekdays are open. */
public final class TradingCalendar {
    public static final ZoneId KST = ZoneId.of("Asia/Seoul");
    static final JsonMapper JSON = JsonMapper.builder().enable(StreamReadFeature.STRICT_DUPLICATE_DETECTION)
        .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS).build();
    public record Day(LocalDate date, boolean open, LocalTime opensAt, LocalTime closesAt) {
        public Day {
            Objects.requireNonNull(date);
            if (open ? opensAt == null || closesAt == null || !opensAt.isBefore(closesAt)
                    : opensAt != null || closesAt != null) throw new IllegalArgumentException("Calendar session");
        }
        public Instant closeInstant() { return open ? date.atTime(closesAt).atZone(KST).toInstant() : null; }
    }
    private final String version, sha256, source, authority;
    private final Instant reviewedAt;
    private final NavigableMap<LocalDate, Day> days;

    private TradingCalendar(String version, String sha256, String source, String authority,
            Instant reviewedAt, NavigableMap<LocalDate, Day> days) {
        this.version=version; this.sha256=sha256; this.source=source; this.authority=authority;
        this.reviewedAt=reviewedAt; this.days=Collections.unmodifiableNavigableMap(days);
    }
    public static TradingCalendar read(Path path) throws IOException { return parse(Files.readAllBytes(path)); }
    public static TradingCalendar parse(byte[] bytes) {
        var root=JSON.readTree(bytes);
        String version=text(root,"version"), source=text(root,"source"), authority=text(root,"authority");
        Instant reviewed=Instant.parse(text(root,"reviewedAt"));
        if (!List.of("development_reviewed","owner_reviewed").contains(authority)
                || !source.startsWith("https://")) throw new IllegalArgumentException("Calendar provenance");
        var days=new TreeMap<LocalDate,Day>();
        if (!root.path("days").isArray() || root.path("days").isEmpty()) throw new IllegalArgumentException("Calendar days");
        for (var row:root.path("days")) {
            if (!row.path("open").isBoolean()) throw new IllegalArgumentException("Explicit open flag required");
            boolean open=row.path("open").asBoolean();
            if (!open && ((!row.path("opensAt").isMissingNode()&&!row.path("opensAt").isNull())
                    ||(!row.path("closesAt").isMissingNode()&&!row.path("closesAt").isNull())))
                throw new IllegalArgumentException("Closed date cannot carry trading hours");
            var day=new Day(LocalDate.parse(text(row,"date")),open,
                open?LocalTime.parse(text(row,"opensAt")):null,open?LocalTime.parse(text(row,"closesAt")):null);
            if (days.putIfAbsent(day.date(),day)!=null) throw new IllegalArgumentException("Duplicate calendar date");
        }
        return new TradingCalendar(version,FileBriefingInputStore.sha256(bytes),source,authority,reviewed,days);
    }
    static String text(JsonNode n,String key) {
        if (!n.path(key).isString() || n.path(key).asString().isBlank()) throw new IllegalArgumentException("Missing "+key);
        return n.path(key).asString();
    }
    public Day day(LocalDate date) { return days.get(date); }
    public LocalDate previous(LocalDate date) { return adjacent(date,-1); }
    public LocalDate next(LocalDate date) { return adjacent(date,1); }
    private LocalDate adjacent(LocalDate date,int delta) {
        for (var d=date.plusDays(delta);;d=d.plusDays(delta)) {
            var day=days.get(d);
            if (day==null) return null; // Coverage gap is unknown, not a holiday to skip.
            if (day.open()) return d;
        }
    }
    public String version() { return version; }
    public String sha256() { return sha256; }
    public String source() { return source; }
    public String authority() { return authority; }
    public Instant reviewedAt() { return reviewedAt; }
}
