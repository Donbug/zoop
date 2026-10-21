package com.zoop.briefing.replay;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.time.*;
import java.util.*;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

/** Independently derives prices from archived provider bytes, not from the proposed projection. */
final class BriefingCompanyPriceRules {
    private BriefingCompanyPriceRules() { }
    record Identity(String symbol, String currency, ZoneId zone) { }
    record Point(BigDecimal value, Instant at, LocalDate date, String kind) {
        ObjectNode json() {
            return StrictJson.newObject().put("value", value.toPlainString()).put("observedAt", at.toString())
                    .put("sessionDate", date.toString()).put("kind", kind);
        }
    }
    static Identity identity(String id) {
        if (id.matches("KRX:[0-9]{6}")) return new Identity(id.substring(4) + ".KS", "KRW", ZoneId.of("Asia/Seoul"));
        require(id.matches("(NASDAQ|NYSE):[A-Z]{1,5}"), "company_identity");
        return new Identity(id.substring(id.indexOf(':') + 1), "USD", ZoneId.of("America/New_York"));
    }
    static byte[] raw(StrictJson.Obj source, Path output) {
        String sha = source.string("sha256"); require(sha.matches("[a-f0-9]{64}"), "raw_sha");
        try {
            Path path = output.resolve("company-prices/" + sha + ".bin");
            require(Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) && Files.size(path) <= 1_000_000, "raw_file");
            byte[] bytes = Files.readAllBytes(path);
            require(source.count("bytes") == bytes.length && Canonical.sha256(bytes).equals(sha), "raw_binding");
            Instant.parse(source.string("collectedAt")); return bytes;
        } catch (java.io.IOException error) { throw new IllegalArgumentException("Company price archive unavailable", error); }
    }
    static List<Point> points(String cid, Instant cutoff, List<StrictJson.Obj> sources, Path output) {
        Identity identity = identity(cid); List<Point> out = new ArrayList<>(); Set<String> intervals = new HashSet<>();
        for (StrictJson.Obj source : sources) {
            String interval = source.string("interval");
            require(Set.of("5m", "1d").contains(interval) && intervals.add(interval) && cid.equals(source.string("companyId")), "source_identity");
            String url = "https://query1.finance.yahoo.com/v8/finance/chart/" + identity.symbol()
                    + "?period1=1790812800&period2=1791504000&interval=" + interval + "&includePrePost=false&events=splits%2Cdiv";
            require(url.equals(source.string("url")), "source_url");
            byte[] bytes = raw(source, output); if (source.count("httpStatus") != 200) continue;
            StrictJson.Obj chart = StrictJson.parseObject(bytes).object("chart");
            require(chart.isNull("error") && chart.objects("result").size() == 1, "provider_error");
            StrictJson.Obj result = chart.objects("result").getFirst(), meta = result.object("meta");
            require(identity.symbol().equals(meta.string("symbol")) && identity.currency().equals(meta.string("currency"))
                    && identity.zone().getId().equals(meta.string("exchangeTimezoneName")), "provider_identity");
            if (result.has("events") && result.object("events").has("splits"))
                require(result.object("events").object("splits").node().isEmpty(), "split_adjustment_policy_missing");
            JsonNode stamps = result.array("timestamp"), values = result.object("indicators").objects("quote").getFirst().array("close");
            require(stamps.size() == values.size(), "series_length"); Set<Long> seen = new HashSet<>();
            for (int i = 0; i < stamps.size(); i++) {
                require(stamps.get(i).isIntegralNumber() && seen.add(stamps.get(i).longValue()), "bar_timestamp");
                if (stamps.get(i).longValue() < 1790812800L || stamps.get(i).longValue() >= 1791504000L) continue;
                if (values.get(i).isNull()) continue;
                require(values.get(i).isNumber(), "bar_number");
                BigDecimal price = values.get(i).decimalValue().setScale(2, RoundingMode.HALF_UP);
                require(price.signum() > 0, "bar_price");
                ZonedDateTime start = Instant.ofEpochSecond(stamps.get(i).longValue()).atZone(identity.zone());
                if (start.getDayOfWeek().getValue() >= 6) continue;
                LocalDate date = start.toLocalDate(); boolean kr = "KRW".equals(identity.currency());
                Instant open = date.atTime(kr ? LocalTime.of(9, 0) : LocalTime.of(9, 30)).atZone(identity.zone()).toInstant();
                Instant close = date.atTime(kr ? LocalTime.of(15, 30) : LocalTime.of(16, 0)).atZone(identity.zone()).toInstant();
                boolean daily = "1d".equals(interval); Instant end = daily ? close : start.toInstant().plusSeconds(300);
                if (daily && !start.toInstant().equals(open)) continue; // terminal live points are not daily closes
                if (!daily && (start.toInstant().isBefore(open) || end.isAfter(close))) continue;
                if (end.isAfter(cutoff)) continue; // close belongs to bucket END, never bucket start
                out.add(new Point(price, end, date, daily ? "daily_close" : "five_minute_close"));
            }
        }
        require(intervals.equals(Set.of("5m", "1d")), "interval_coverage");
        out.sort(Comparator.comparing(Point::at).thenComparing(p -> "daily_close".equals(p.kind()))); return out;
    }
    static ObjectNode apply(StrictJson.Obj price, String cid, Instant cutoff, Path output) {
        Identity id = identity(cid);
        require(cid.equals(price.string("companyId")) && cutoff.equals(Instant.parse(price.string("cutoff")))
                && id.currency().equals(price.string("currency")) && id.zone().getId().equals(price.string("exchangeTimezone"))
                && "Yahoo Finance".equals(price.string("source")) && !price.bool("official"), "snapshot_identity");
        List<Point> rows = points(cid, cutoff, price.objects("sources"), output);
        // Preserve the distinction between a successful empty history and failed provider requests.
        if (rows.isEmpty()) {
            boolean failed = price.objects("sources").stream().anyMatch(source -> source.count("httpStatus") != 200);
            require("unavailable".equals(price.string("status")) && price.isNull("latest") && price.isNull("baseline")
                    && price.isNull("change") && price.isNull("changeRate") && "unavailable".equals(price.string("comparisonStatus"))
                    && (failed ? "provider_request_failed" : "eligible_price_missing").equals(price.string("reason")), "missing_projection");
            return (ObjectNode) price.node().deepCopy();
        }
        Point latest = rows.getLast();
        Instant morning = cutoff.atZone(ZoneId.of("Asia/Seoul")).toLocalDate().atTime(9, 20).atZone(ZoneId.of("Asia/Seoul")).toInstant();
        boolean evening = cutoff.isAfter(morning); Point baseline = null;
        for (Point row : rows) if (evening ? !row.at().isAfter(morning) : "daily_close".equals(row.kind()) && row.date().isBefore(latest.date())) baseline = row;
        require("available".equals(price.string("status")) && price.isNull("reason") && latest.json().equals(price.object("latest").node())
                && (evening ? "morning_cutoff" : "previous_close").equals(price.string("baselineKind")), "latest_projection");
        require(baseline == null ? price.isNull("baseline") : baseline.json().equals(price.object("baseline").node()), "baseline_projection");
        String status = baseline == null ? "unavailable" : evening && !latest.at().isAfter(baseline.at()) ? "no_new_session" : "available";
        require(status.equals(price.string("comparisonStatus")), "comparison_status");
        if ("available".equals(status)) {
            BigDecimal delta = latest.value().subtract(baseline.value());
            BigDecimal rate = delta.multiply(BigDecimal.valueOf(100)).divide(baseline.value(), 2, RoundingMode.HALF_UP);
            require(delta.toPlainString().equals(price.string("change")) && rate.toPlainString().equals(price.string("changeRate")), "comparison_arithmetic");
        } else require(price.isNull("change") && price.isNull("changeRate"), "unobserved_comparison");
        return (ObjectNode) price.node().deepCopy();
    }
    private static void require(boolean value, String reason) {
        if (!value) throw new IllegalArgumentException("Company price rejected: " + reason);
    }
}
