package com.zoop.briefing.replay;

import static org.assertj.core.api.Assertions.*;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.nio.file.*;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class BriefingCompanyPriceRulesTest {
    @TempDir Path output;
    private StrictJson.Obj archive(String interval, long[] timestamps, int[] prices) throws Exception {
        var result = StrictJson.newObject();
        result.putObject("meta").put("symbol", "005930.KS").put("currency", "KRW")
                .put("exchangeTimezoneName", "Asia/Seoul").put("regularMarketPrice", 999999999);
        var stamps = result.putArray("timestamp"); for (long stamp : timestamps) stamps.add(stamp);
        var values = result.putObject("indicators").putArray("quote").addObject().putArray("close");
        for (int value : prices) values.add(value);
        var raw = StrictJson.newObject(); var chart = raw.putObject("chart").putNull("error"); chart.putArray("result").add(result);
        byte[] bytes = StrictJson.write(raw); String sha = Canonical.sha256(bytes);
        Files.createDirectories(output.resolve("company-prices")); Files.write(output.resolve("company-prices/" + sha + ".bin"), bytes);
        return StrictJson.Obj.of(StrictJson.newObject().put("companyId", "KRX:005930").put("interval", interval)
                .put("url", "https://query1.finance.yahoo.com/v8/finance/chart/005930.KS?period1=1790812800&period2=1791504000&interval=" + interval + "&includePrePost=false&events=splits%2Cdiv")
                .put("sha256", sha).put("bytes", bytes.length).put("httpStatus", 200).put("collectedAt", "2026-10-21T00:00:00Z"));
    }
    private long epoch(String value) { return Instant.parse(value).getEpochSecond(); }
    private List<StrictJson.Obj> sources() throws Exception {
        return List.of(archive("5m", new long[]{epoch("2026-10-08T00:15:00Z"), epoch("2026-10-08T00:20:00Z"), epoch("2026-10-21T06:00:00Z")},
                        new int[]{268500, 999999, 888888}),
                archive("1d", new long[]{epoch("2026-10-07T00:00:00Z"), epoch("2026-10-08T00:00:00Z")}, new int[]{270000, 262000}));
    }
    @Test void unfinishedBarDailyFutureAndLiveTerminalCannotEnterMorning() throws Exception {
        var points = BriefingCompanyPriceRules.points("KRX:005930", Instant.parse("2026-10-08T00:20:00Z"), sources(), output);
        assertThat(points.getLast().value()).isEqualByComparingTo("268500");
        assertThat(points.getLast().at()).isEqualTo(Instant.parse("2026-10-08T00:20:00Z"));
        assertThat(points).hasSize(2);
    }
    @Test void dailyCloseIsEligibleOnlyAfterTheRegularSessionEnds() throws Exception {
        var refs = sources();
        var before = BriefingCompanyPriceRules.points("KRX:005930", Instant.parse("2026-10-08T06:29:59Z"), refs, output);
        var after = BriefingCompanyPriceRules.points("KRX:005930", Instant.parse("2026-10-08T06:30:00Z"), refs, output);
        assertThat(before.getLast().kind()).isEqualTo("five_minute_close");
        assertThat(after.getLast().kind()).isEqualTo("daily_close");
        assertThat(after.getLast().value()).isEqualByComparingTo("262000");
    }
    @Test void sourceIdentityAndRawTamperingAreRejected() throws Exception {
        var refs = sources();
        assertThatThrownBy(() -> BriefingCompanyPriceRules.points("KRX:000660", Instant.parse("2026-10-08T08:30:00Z"), refs, output)).isInstanceOf(IllegalArgumentException.class);
        Files.writeString(output.resolve("company-prices/" + refs.getFirst().string("sha256") + ".bin"), "changed");
        assertThatThrownBy(() -> BriefingCompanyPriceRules.points("KRX:005930", Instant.parse("2026-10-08T08:30:00Z"), refs, output)).isInstanceOf(IllegalArgumentException.class);
    }
    @Test void providerFailuresCannotBeImportedAsSuccessfulEmptyHistories() throws Exception {
        for (int status : new int[]{200, 503}) {
            var refs = List.of(archive("5m", new long[]{}, new int[]{}), archive("1d", new long[]{}, new int[]{}));
            var price = StrictJson.newObject().put("companyId", "KRX:005930").put("cutoff", "2026-10-08T00:20:00Z")
                    .put("currency", "KRW").put("exchangeTimezone", "Asia/Seoul").put("source", "Yahoo Finance").put("official", false)
                    .put("status", "unavailable").put("reason", status == 200 ? "eligible_price_missing" : "provider_request_failed")
                    .put("comparisonStatus", "unavailable").putNull("latest").putNull("baseline").putNull("change").putNull("changeRate");
            var sources = price.putArray("sources");
            for (var ref : refs) sources.add(((tools.jackson.databind.node.ObjectNode) ref.node().deepCopy()).put("httpStatus", status));
            assertThatCode(() -> BriefingCompanyPriceRules.apply(StrictJson.Obj.of(price), "KRX:005930", Instant.parse("2026-10-08T00:20:00Z"), output)).doesNotThrowAnyException();
            price.put("reason", status == 200 ? "provider_request_failed" : "eligible_price_missing");
            assertThatThrownBy(() -> BriefingCompanyPriceRules.apply(StrictJson.Obj.of(price), "KRX:005930", Instant.parse("2026-10-08T00:20:00Z"), output))
                    .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("missing_projection");
        }
    }
    @Test void laterExplicitRangeDoesNotUseOctoberFixtureRangeOrFutureBars() throws Exception {
        long from = epoch("2026-10-14T00:00:00Z"), to = epoch("2026-10-23T00:00:00Z");
        var rawRefs = List.of(archive("5m", new long[]{epoch("2026-10-22T00:15:00Z"), epoch("2026-10-22T00:20:00Z"), epoch("2026-10-23T00:15:00Z")},
                new int[]{100,999,888}), archive("1d", new long[]{epoch("2026-10-21T00:00:00Z"),epoch("2026-10-22T00:00:00Z")},new int[]{90,110}));
        var refs = rawRefs.stream().map(ref -> {
            var node = (tools.jackson.databind.node.ObjectNode) ref.node().deepCopy();
            node.put("period1",from).put("period2",to).put("url",ref.string("url").replace("1790812800",Long.toString(from)).replace("1791504000",Long.toString(to)));
            return StrictJson.Obj.of(node);
        }).toList();
        var morning = BriefingCompanyPriceRules.points("KRX:005930",Instant.parse("2026-10-22T00:20:00Z"),refs,output);
        assertThat(morning).hasSize(2); assertThat(morning.getLast().value()).isEqualByComparingTo("100");
        var changed = (tools.jackson.databind.node.ObjectNode) refs.getFirst().node().deepCopy(); changed.put("period2",to+86400);
        assertThatThrownBy(() -> BriefingCompanyPriceRules.points("KRX:005930",Instant.parse("2026-10-22T00:20:00Z"),List.of(StrictJson.Obj.of(changed),refs.getLast()),output))
                .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("source_url");
    }
}
