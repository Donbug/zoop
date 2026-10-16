package com.zoop.briefing.market;

import com.zoop.briefing.input.*;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import tools.jackson.databind.JsonNode;
import static org.junit.jupiter.api.Assertions.*;
import static com.zoop.briefing.market.PublicMarketProvider.*;

class MarketSnapshotTest {
    @TempDir Path temp;
    static TradingCalendar calendar() {
        var n=TradingCalendar.JSON.createObjectNode().put("version","synthetic-calendar-v1")
            .put("source","https://example.test/reviewed-calendar").put("authority","development_reviewed")
            .put("reviewedAt","2026-10-01T00:00:00Z");
        var days=n.putArray("days");
        for(int d=13;d<=20;d++) {
            var row=days.addObject().put("date","2026-10-"+d).put("open",d!=17&&d!=18);
            if(d!=17&&d!=18) row.put("opensAt","09:00").put("closesAt","15:30");
        }
        return TradingCalendar.parse(TradingCalendar.JSON.writeValueAsBytes(n));
    }
    static BriefingRoundClock.Context context(String id,String edition) {
        var date=LocalDate.of(2026,10,15);
        return new BriefingRoundClock.Context(id,date,edition,BriefingRoundClock.scheduledAt(date,edition),
            BriefingRoundClock.previousRound(date,edition),false,calendar());
    }
    static byte[] chart(String symbol,Instant latest) {
        var root=TradingCalendar.JSON.createObjectNode(); var chart=root.putObject("chart"); chart.putNull("error");
        var result=chart.putArray("result").addObject();
        result.putObject("meta").put("symbol",symbol).put("instrumentType","INDEX")
            .put("exchangeTimezoneName","Asia/Seoul").put("regularMarketTime",latest.getEpochSecond());
        var times=result.putArray("timestamp");
        for(int d=13;d<=15;d++) times.add(LocalDate.of(2026,10,d).atTime(9,0).atZone(TradingCalendar.KST).toEpochSecond());
        result.putObject("indicators").putArray("quote").addObject().putArray("close").add(100).add(102).add(105);
        return TradingCalendar.JSON.writeValueAsBytes(root);
    }
    static List<Receipt> receipts(Instant at,Instant observed) {
        var n=TradingCalendar.JSON.createObjectNode(); var fx=n.putObject("exchangeInfo");
        fx.put("reutersCode","FX_USDKRW").put("unit","KRW").put("priceDataType","NOTICE_ROUND")
            .put("closePrice","1,350.00").put("localTradedAt",observed.atOffset(ZoneOffset.ofHours(9)).toString());
        fx.putObject("stockExchangeType").put("code","HANA");
        var history=TradingCalendar.JSON.createArrayNode();
        history.addObject().put("localTradedAt","2026-10-15").put("closePrice","1,350.00");
        history.addObject().put("localTradedAt","2026-10-14").put("closePrice","1,340.00");
        return List.of(new Receipt(Feed.KOSPI,at,200,chart("^KS11",observed),null),
            new Receipt(Feed.KOSDAQ,at,200,chart("^KQ11",observed),null),
            new Receipt(Feed.FX,at,200,TradingCalendar.JSON.writeValueAsBytes(n),null),
            new Receipt(Feed.FX_HISTORY,at,200,TradingCalendar.JSON.writeValueAsBytes(history),null));
    }
    MarketSnapshot snapshot(String edition,List<Receipt> rs) throws Exception {
        return MarketSnapshot.freeze(context("round",edition),rs,context("round",edition).scheduledAt().minusSeconds(1),
            new FileBriefingInputStore(temp.resolve("private")));
    }
    static JsonNode indicator(MarketSnapshot s,int index) { return s.json().path("marketVariables").path("indicators").get(index); }

    @Test void morningUsesPreviousCloseNotLiveDailyCandleAndComputesFraction() throws Exception {
        var at=Instant.parse("2026-10-15T00:19:30Z");
        var s=snapshot("morning",receipts(at,at.minusSeconds(30))); var k=indicator(s,0);
        assertEquals("ok",k.path("status").asString());
        assertEquals(102,k.path("value").asInt());
        assertEquals("2026-10-14",k.path("observedDate").asString());
        assertTrue(k.path("observedAt").isNull());
        assertEquals("pt",k.path("unit").asString());
        assertEquals(0.02,k.path("changeRate").asDouble(),1e-12);
        assertEquals("regular",s.json().path("runContext").path("marketSession").asString());
        assertFalse(s.json().path("productionAuthorized").asBoolean());
        assertTrue(s.json().path("completeness").get(0).path("valueAvailable").asBoolean());
    }
    @Test void eveningUsesFinalizedSameDayCloseAndPreviousActualTradingDate() throws Exception {
        var at=Instant.parse("2026-10-15T08:29:30Z");
        var k=indicator(snapshot("evening",receipts(at,at.minusSeconds(30))),0);
        assertEquals(105,k.path("value").asInt());
        assertEquals("2026-10-15",k.path("observedDate").asString());
        assertEquals(102,k.path("baseline").path("value").asInt());
        assertEquals("2026-10-14",k.path("baseline").path("date").asString());
    }
    @Test void earlyEveningPrefetchKeepsPriorCloseAsDelayedRatherThanCurrentClose() throws Exception {
        var at=Instant.parse("2026-10-15T02:00:00Z");
        var s=snapshot("evening",receipts(at,at.minusSeconds(30)));
        var k=indicator(s,0);
        assertEquals("delayed",k.path("status").asString()); assertEquals(102,k.path("value").asInt());
        assertEquals("2026-10-14",k.path("observedDate").asString());
        assertTrue(s.json().path("completeness").get(0).path("valueAvailable").asBoolean());
    }
    @Test void rateIsTimestampedBankNoticeAndBaselineIsNotDerivedFromRoundedProviderPercent() throws Exception {
        var at=Instant.parse("2026-10-15T00:19:30Z");
        var fx=indicator(snapshot("morning",receipts(at,at.minusSeconds(30))),2);
        assertEquals("latest",fx.path("valueKind").asString()); assertEquals("KRW",fx.path("unit").asString());
        assertEquals(1340,fx.path("baseline").path("value").asInt());
        assertEquals(10,fx.path("change").asInt()); assertEquals(10.0/1340,fx.path("changeRate").asDouble(),1e-12);
        assertFalse(fx.path("source").path("official").asBoolean());
        assertTrue(fx.path("source").path("name").asString().contains("고시"));
        assertFalse(fx.path("observedAt").isNull());
    }
    @Test void futureObservedRateIsUnavailableAndNeverFilledFromHistory() throws Exception {
        var at=Instant.parse("2026-10-15T00:19:30Z"); var rs=new ArrayList<>(receipts(at,at.minusSeconds(30)));
        var raw=TradingCalendar.JSON.readTree(rs.get(2).body());
        ((tools.jackson.databind.node.ObjectNode)raw.path("exchangeInfo")).put("localTradedAt","2026-10-15T09:21:00+09:00");
        rs.set(2,new Receipt(Feed.FX,at,200,TradingCalendar.JSON.writeValueAsBytes(raw),null));
        var s=snapshot("morning",rs); var n=indicator(s,2);
        assertEquals("unavailable",n.path("status").asString()); assertTrue(n.path("value").isNull());
        assertEquals("observation_after_cutoff",n.path("reason").asString());
        assertFalse(s.json().path("completeness").get(2).path("valueAvailable").asBoolean());
    }
    @Test void partialFailureDoesNotDiscardOtherIndicatorsOrInventZero() throws Exception {
        var at=Instant.parse("2026-10-15T00:19:30Z"); var rs=new ArrayList<>(receipts(at,at.minusSeconds(30)));
        rs.set(2,new Receipt(Feed.FX,at,429,new byte[0],"temporary_failure"));
        var s=snapshot("morning",rs);
        assertEquals("ok",indicator(s,0).path("status").asString());
        assertEquals("ok",indicator(s,1).path("status").asString());
        assertEquals("failed",indicator(s,2).path("status").asString());
        assertTrue(indicator(s,2).path("value").isNull());
        assertEquals("fetch_failed",s.json().path("completeness").get(2).path("state").asString());
        assertFalse(s.json().path("completeness").get(2).path("valueAvailable").asBoolean());
    }
    @Test void wrongSymbolAndBrokenNumericShapeFailClosed() throws Exception {
        var at=Instant.parse("2026-10-15T00:19:30Z"); var rs=new ArrayList<>(receipts(at,at.minusSeconds(30)));
        rs.set(0,new Receipt(Feed.KOSPI,at,200,chart("^OTHER",at),null));
        assertEquals("format_changed",indicator(snapshot("morning",rs),0).path("reasonCode").asString());
    }
    @Test void cutoffViolationAndDuplicateReceiptsAbortBeforeWritingSnapshot() throws Exception {
        var c=context("round","morning"); var store=new FileBriefingInputStore(temp.resolve("private"));
        var rs=receipts(c.scheduledAt().plusSeconds(1),c.scheduledAt());
        assertThrows(IllegalArgumentException.class,()->MarketSnapshot.freeze(c,rs,c.scheduledAt().plusSeconds(2),store));
        var duplicate=new ArrayList<>(receipts(c.scheduledAt().minusSeconds(2),c.scheduledAt().minusSeconds(3)));
        duplicate.add(duplicate.getFirst());
        assertThrows(IllegalArgumentException.class,()->MarketSnapshot.freeze(c,duplicate,c.scheduledAt().minusSeconds(1),store));
        var late=TradingCalendar.JSON.createObjectNode().put("version","late-review").put("source","https://example.test/calendar")
            .put("authority","development_reviewed").put("reviewedAt",c.scheduledAt().minusSeconds(30).toString());
        late.putArray("days").addObject().put("date","2026-10-15").put("open",false);
        var laterCalendar=new BriefingRoundClock.Context("r",c.date(),c.edition(),c.scheduledAt(),null,true,
            TradingCalendar.parse(TradingCalendar.JSON.writeValueAsBytes(late)));
        assertThrows(IllegalArgumentException.class,()->MarketSnapshot.freeze(laterCalendar,List.of(),c.scheduledAt().minusSeconds(60),store));
        try(var files=Files.list(temp.resolve("private"))) { assertEquals(0,files.count()); }
    }
    @Test void rawAndSnapshotTamperingAreDetectedOnRestore() throws Exception {
        var at=Instant.parse("2026-10-15T00:19:30Z"); var s=snapshot("morning",receipts(at,at.minusSeconds(30)));
        assertEquals(s.json(),MarketSnapshot.restore(s.staged()).json());
        var first=s.json().path("receipts").get(0).path("sha256").asString();
        Files.writeString(s.staged().path().getParent().resolve(first+".json"),"{}");
        assertThrows(java.io.IOException.class,()->MarketSnapshot.restore(s.staged()));
    }
    @Test void sameFrozenSnapshotAttachesToActualInputIdempotentlyButOtherRoundIsRejected() throws Exception {
        var at=Instant.parse("2026-10-15T00:19:30Z"); var s=snapshot("morning",receipts(at,at.minusSeconds(30)));
        var preparer=new BriefingInputPreparer(new FileBriefingInputStore(temp.resolve("input")));
        var input=com.zoop.briefing.selection.BriefingCandidateSelectorTest.input();
        var a=preparer.prepareWithMarketSnapshot(input,s,Map.of(),null);
        var b=preparer.prepareWithMarketSnapshot(input,s,Map.of(),null);
        assertEquals(a.staged(),b.staged());
        var tree=TradingCalendar.JSON.readTree(Files.readAllBytes(a.staged().path()));
        assertEquals(s.staged().sha256(),tree.path("marketSnapshotRef").path("sha256").asString());
        assertEquals(3,tree.path("marketSnapshot").path("marketVariables").path("indicators").size());
        var wrong=com.zoop.briefing.selection.BriefingCandidateSelectorTest.context();
        var other=new com.zoop.briefing.selection.SelectionInput(new com.zoop.briefing.selection.SelectionInput.Context(
            "other",wrong.edition(),wrong.scheduledAt(),wrong.from(),false,"g1",2,3),true,List.of());
        assertThrows(IllegalArgumentException.class,()->preparer.prepareWithMarketSnapshot(other,s,Map.of(),null));
    }
    @Test void missingFeedIsNotAttemptedAndDoesNotLookLikeSuccessfulEmptyCollection() throws Exception {
        var at=Instant.parse("2026-10-15T00:19:30Z");
        var s=snapshot("morning",receipts(at,at.minusSeconds(30)).subList(0,2));
        assertEquals("not_attempted",s.json().path("completeness").get(2).path("state").asString());
        assertEquals("unavailable",indicator(s,2).path("status").asString());
        assertFalse(s.json().path("completeness").get(2).path("valueAvailable").asBoolean());
    }
    @Test void collectMakesExactlyOneAttemptPerFeedAndRetainsFailures() throws Exception {
        var calls=new ArrayList<Feed>();
        var receipts=PublicMarketProvider.collect(feed->{calls.add(feed);return new Receipt(feed,Instant.EPOCH,503,new byte[0],"temporary_failure");});
        assertEquals(List.of(Feed.values()),calls); assertEquals(4,receipts.size());
    }
    @Test void successfulEmptySeriesIsDifferentFromFailureAndMissingFeed() throws Exception {
        var at=Instant.parse("2026-10-15T00:19:30Z"); var rs=new ArrayList<>(receipts(at,at.minusSeconds(30)));
        var root=TradingCalendar.JSON.readTree(rs.getFirst().body());
        var result=(tools.jackson.databind.node.ObjectNode)root.path("chart").path("result").get(0);
        result.putArray("timestamp");
        ((tools.jackson.databind.node.ObjectNode)result.path("indicators").path("quote").get(0)).putArray("close");
        rs.set(0,new Receipt(Feed.KOSPI,at,200,TradingCalendar.JSON.writeValueAsBytes(root),null));
        var snapshot=snapshot("morning",rs);
        assertTrue(indicator(snapshot,0).path("value").isNull());
        assertEquals("collected_ok_empty",snapshot.json().path("completeness").get(0).path("state").asString());
        assertFalse(snapshot.json().path("completeness").get(0).path("valueAvailable").asBoolean());
        assertEquals("ok",indicator(snapshot,1).path("status").asString());
    }
    @Test void collectedNonemptyDataWithMissingBaselinesHasNoAvailableValue() throws Exception {
        var at=Instant.parse("2026-10-15T00:19:30Z"); var rs=new ArrayList<>(receipts(at,at.minusSeconds(30)));
        var raw=TradingCalendar.JSON.readTree(rs.getFirst().body());
        var closes=(tools.jackson.databind.node.ArrayNode)raw.path("chart").path("result").get(0)
            .path("indicators").path("quote").get(0).path("close");
        closes.set(0,tools.jackson.databind.node.NullNode.getInstance());
        rs.set(0,new Receipt(Feed.KOSPI,at,200,TradingCalendar.JSON.writeValueAsBytes(raw),null));
        var history=TradingCalendar.JSON.createArrayNode();
        history.addObject().put("localTradedAt","2026-10-15").put("closePrice","1,350.00");
        rs.set(3,new Receipt(Feed.FX_HISTORY,at,200,TradingCalendar.JSON.writeValueAsBytes(history),null));
        var s=snapshot("morning",rs);
        assertEquals("previous_close_unavailable",indicator(s,0).path("reason").asString());
        assertEquals("previous_rate_unavailable",indicator(s,2).path("reason").asString());
        for(int i:List.of(0,2)) {
            var completeness=s.json().path("completeness").get(i);
            assertEquals("collected_ok",completeness.path("state").asString());
            assertEquals("unavailable",completeness.path("indicatorStatus").asString());
            assertTrue(completeness.path("valueAvailable").isBoolean());
            assertFalse(completeness.path("valueAvailable").asBoolean());
            assertTrue(indicator(s,i).path("value").isNull());
        }
        assertTrue(s.json().path("completeness").get(1).path("valueAvailable").asBoolean());
        assertEquals(s.json(),MarketSnapshot.restore(s.staged()).json());
    }
    @Test void successfulCollectionWithUnknownPreviousTradingDayIsNotAnAvailableValue() throws Exception {
        var at=Instant.parse("2026-10-15T00:19:30Z");
        var raw=TradingCalendar.JSON.createObjectNode().put("version","partial-calendar")
            .put("source","https://example.test/calendar").put("authority","development_reviewed")
            .put("reviewedAt","2026-10-01T00:00:00Z");
        raw.putArray("days").addObject().put("date","2026-10-15").put("open",true)
            .put("opensAt","09:00").put("closesAt","15:30");
        var base=context("round","morning");
        var c=new BriefingRoundClock.Context(base.roundId(),base.date(),base.edition(),base.scheduledAt(),
            base.from(),base.firstRound(),TradingCalendar.parse(TradingCalendar.JSON.writeValueAsBytes(raw)));
        var s=MarketSnapshot.freeze(c,receipts(at,at.minusSeconds(30)),at,new FileBriefingInputStore(temp.resolve("private")));
        for(int i=0;i<3;i++) {
            assertEquals("calendar_unknown",indicator(s,i).path("reason").asString());
            var completeness=s.json().path("completeness").get(i);
            assertEquals("collected_ok",completeness.path("state").asString());
            assertEquals("unavailable",completeness.path("indicatorStatus").asString());
            assertTrue(completeness.path("valueAvailable").isBoolean());
            assertFalse(completeness.path("valueAvailable").asBoolean());
        }
    }
    @Test void privateSnapshotFilesKeepPermissionsAndCallerMutationCannotChangeBundle() throws Exception {
        var at=Instant.parse("2026-10-15T00:19:30Z"); var s=snapshot("morning",receipts(at,at.minusSeconds(30)));
        s.json().put("productionAuthorized",true);
        assertFalse(s.json().path("productionAuthorized").asBoolean());
        assertEquals(java.nio.file.attribute.PosixFilePermissions.fromString("rw-------"),Files.getPosixFilePermissions(s.staged().path()));
    }
}
