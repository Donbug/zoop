package com.zoop.briefing.replay;

import com.zoop.common.json.*;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import tools.jackson.databind.node.*;
import static org.junit.jupiter.api.Assertions.*;

class BriefingPriceContextRulesTest {
    @TempDir Path root;
    static final String CID = "NASDAQ:AAPL", CUTOFF = "2026-10-22T00:20:00Z";
    Map<String, StrictJson.Obj> receipts;
    ObjectNode refs;

    StrictJson.Obj review(String cutoff, String published) {
        var n = StrictJson.newObject().put("roundId", "round-1").put("date", "2026-10-22")
                .put("edition", "morning").put("cutoff", cutoff).put("resultVersion", "edition-1");
        n.putObject("sources").putObject("s1").put("publishedAt", published);
        n.putArray("companies").addObject().put("companyId", CID).put("companyName", "합성 기업")
                .putObject("newInformation").putArray("evidenceIds").add("s1");
        return StrictJson.Obj.of(n);
    }
    StrictJson.Obj receipt(String period, String cutoff, ObjectNode body) throws Exception {
        var q = StrictJson.newObject().put("companyId", CID).put("period", period).put("cutoff", cutoff);
        byte[] raw = StrictJson.write(body); String sha = Canonical.sha256(raw);
        Files.createDirectories(root.resolve("price-context-responses")); Files.write(root.resolve("price-context-responses/" + sha + ".bin"), raw);
        var r = StrictJson.newObject().put("id", Canonical.digest(q)).put("httpStatus", 200)
                .put("sha256", sha).put("bytes", raw.length).put("collectedAt", "2026-10-24T00:00:00Z"); r.set("request", q);
        return StrictJson.Obj.of(r);
    }
    ObjectNode data(String period) {
        var d = StrictJson.newObject().put("status", "available").put("companyId", CID)
                .put("period", period).put("interval", period.equals("1d") ? "5m" : "1d").put("currency", "USD");
        d.putObject("source").put("provider", "toss").put("official", true); d.putArray("points"); return d;
    }
    void setup(String cutoff) throws Exception {
        ObjectNode minute = data("1d"); minute.putObject("range").put("from", "2026-10-21T09:30:00-04:00")
                .put("to", "2026-10-21T16:00:00-04:00").put("sessionDate", "2026-10-21");
        for (int i = 0; i < 78; i++) ((ArrayNode) minute.path("points")).addObject()
                .put("time", OffsetDateTime.parse("2026-10-21T09:30:00-04:00").plusMinutes(i * 5L).toString())
                .put("open", 100 + i).put("high", 101 + i).put("low", 99 + i).put("close", 100 + i).put("volume", 10);
        ObjectNode daily = data("1m");
        ((ArrayNode) daily.path("points")).addObject().put("time", "2026-10-20T00:00:00-04:00")
                .put("open", 90).put("high", 95).put("low", 80).put("close", 90).put("volume", 5000);
        ((ArrayNode) daily.path("points")).addObject().put("time", "2026-10-21T00:00:00-04:00")
                .put("open", 100).put("high", 200).put("low", 80).put("close", 180).put("volume", 10000);
        var a = receipt("1m", cutoff, daily); var b = receipt("1d", cutoff, minute);
        receipts = Map.of(a.string("id"), a, b.string("id"), b);
        refs = StrictJson.newObject().put("companyId", CID).put("daily", a.string("id")).put("intraday", b.string("id"));
    }
    ObjectNode derive(String cutoff, String published) throws Exception {
        setup(cutoff); var r = review(cutoff, published);
        return BriefingPriceContextRules.company(StrictJson.Obj.of(refs), r.objects("companies").getFirst(), r, null, receipts, root);
    }
    @Test void afterCloseNewsHasNoPostNewsTradeAndUsesDailyCloseNotLastMinute() throws Exception {
        var out = derive(CUTOFF, "2026-10-21T20:01:00Z");
        assertEquals("180", out.path("latest").path("value").stringValue());
        assertEquals("10000", out.path("day").path("volume").stringValue());
        assertEquals("no_post_news_trade", out.path("news").get(0).path("status").stringValue());
        assertEquals(0, out.path("news").get(0).path("postNewsBars").intValue());
    }
    @Test void intradayPublicationExcludesContainingBarFromPostNewsComparison() throws Exception {
        var out = derive(CUTOFF, "2026-10-21T14:35:38Z"); var news = out.path("news").get(0);
        assertEquals(64, news.path("postNewsBars").intValue());
        assertEquals("112", news.path("before").path("value").stringValue());
        assertEquals("observed", news.path("status").stringValue());
        assertEquals("60.71", news.path("changeRatePercent").stringValue());
    }
    @Test void unfinishedCandlesAndFutureDailyOhlcCannotLeakThroughCutoff() throws Exception {
        var out = derive("2026-10-21T14:37:00Z", "2026-10-21T14:35:38Z");
        assertEquals(13, out.path("barCount").intValue());
        assertEquals("112", out.path("latest").path("value").stringValue());
        assertEquals("113", out.path("day").path("high").stringValue());
        assertFalse(out.path("completeSession").booleanValue());
    }
    @Test void futureNewsAndModifiedResponseArchivesAreRejected() throws Exception {
        assertThrows(IllegalArgumentException.class, () -> derive(CUTOFF, "2026-10-23T00:00:00Z"));
        setup(CUTOFF); var receipt = receipts.values().iterator().next();
        Files.writeString(root.resolve("price-context-responses/" + receipt.string("sha256") + ".bin"), "{}");
        assertThrows(IllegalArgumentException.class, () -> BriefingPriceContextRules.raw(receipt, root));
    }
    @Test void missingPreEventWindowIsNotPresentedAsMeasuredReaction() throws Exception {
        var out = derive(CUTOFF, "2026-10-19T00:00:00Z");
        assertEquals("event_window_unavailable", out.path("news").get(0).path("status").stringValue());
        assertTrue(out.path("news").get(0).path("changeRatePercent").isNull());
    }
    @Test void previousConfirmedCloseAnchorsNextSessionWithoutClaimingCausality() throws Exception {
        setup(CUTOFF); var r = review(CUTOFF, "2026-10-20T20:01:00Z");
        var prior = StrictJson.newObject().put("status", "available");
        prior.putObject("latest").put("value", "90").put("observedAt", "2026-10-20T20:00:00Z").put("kind", "daily_close");
        var out = BriefingPriceContextRules.company(StrictJson.Obj.of(refs), r.objects("companies").getFirst(), r,
                StrictJson.Obj.of(prior), receipts, root);
        assertEquals("observed", out.path("news").get(0).path("status").stringValue());
        assertEquals(78, out.path("news").get(0).path("postNewsBars").intValue());
        assertEquals("100.00", out.path("news").get(0).path("changeRatePercent").stringValue());
        assertTrue(out.path("interpretation").stringValue().contains("단정하지 않습니다"));
    }
    @Test void sameTimestampPriceIsNotNewMorningToEveningTrade() throws Exception {
        setup(CUTOFF); var r = (ObjectNode) review(CUTOFF, "2026-10-21T20:01:00Z").node().deepCopy(); r.put("edition", "evening");
        var prior = StrictJson.newObject().put("status", "available");
        var latest = prior.putObject("latest").put("value", "180").put("observedAt", "2026-10-21T20:00:00Z").put("kind", "daily_close");
        var c = StrictJson.Obj.of(r).objects("companies").getFirst();
        var same = BriefingPriceContextRules.company(StrictJson.Obj.of(refs), c, StrictJson.Obj.of(r), StrictJson.Obj.of(prior), receipts, root);
        assertEquals("no_new_session", same.path("sinceMorning").path("status").stringValue());
        latest.put("value", "179");
        var revised = BriefingPriceContextRules.company(StrictJson.Obj.of(refs), c, StrictJson.Obj.of(r), StrictJson.Obj.of(prior), receipts, root);
        assertEquals("revised_observation", revised.path("sinceMorning").path("status").stringValue());
        assertFalse(revised.path("sinceMorning").has("changeRatePercent"));
    }
}
