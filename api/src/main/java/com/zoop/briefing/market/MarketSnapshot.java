package com.zoop.briefing.market;

import com.zoop.briefing.input.FileBriefingInputStore;
import java.io.IOException;
import java.nio.file.*;
import java.math.*;
import java.time.*;
import java.util.*;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;
import static com.zoop.briefing.market.PublicMarketProvider.Feed;

/** Private immutable market bundle; official=false never confers production publication/model rights. */
public final class MarketSnapshot {
    private final FileBriefingInputStore.Staged staged;
    private final ObjectNode json;
    private MarketSnapshot(FileBriefingInputStore.Staged staged,ObjectNode json) { this.staged=staged; this.json=json.deepCopy(); }
    public FileBriefingInputStore.Staged staged() { return staged; }
    public ObjectNode json() { return json.deepCopy(); }
    public static MarketSnapshot restore(FileBriefingInputStore.Staged staged) throws IOException {
        if (Files.isSymbolicLink(staged.path()) || !Files.isRegularFile(staged.path(),LinkOption.NOFOLLOW_LINKS)) throw new IOException("Snapshot regular file required");
        byte[] bytes=Files.readAllBytes(staged.path());
        if(bytes.length!=staged.bytes()||!FileBriefingInputStore.sha256(bytes).equals(staged.sha256())) throw new IOException("Market snapshot changed");
        var n=TradingCalendar.JSON.readTree(bytes);
        if (!n.isObject() || !n.path("schema").asString().equals("zoop-briefing-market-v1")) throw new IOException("Market snapshot schema");
        for(var receipt:n.path("receipts")) {
            if(!receipt.has("sha256")) continue;
            String sha=receipt.path("sha256").asString();
            if(!sha.matches("[a-f0-9]{64}")) throw new IOException("Receipt hash");
            Path raw=staged.path().toAbsolutePath().getParent().resolve(sha+".json");
            if(Files.isSymbolicLink(raw)||!Files.isRegularFile(raw,LinkOption.NOFOLLOW_LINKS)) throw new IOException("Raw receipt missing");
            byte[] body=Files.readAllBytes(raw);
            if(body.length!=receipt.path("bytes").asLong()||!FileBriefingInputStore.sha256(body).equals(sha))
                throw new IOException("Raw receipt changed");
        }
        return new MarketSnapshot(staged,(ObjectNode)n);
    }
    public static MarketSnapshot freeze(BriefingRoundClock.Context c,List<PublicMarketProvider.Receipt> receipts,
            Instant frozenAt,FileBriefingInputStore store) throws IOException {
        if (frozenAt.isAfter(c.scheduledAt())||c.calendar().reviewedAt().isAfter(frozenAt))
            throw new IllegalArgumentException("Input/calendar freeze time violates cutoff");
        var byFeed=new EnumMap<Feed,PublicMarketProvider.Receipt>(Feed.class);
        for(var r:receipts) {
            if (byFeed.putIfAbsent(r.feed(),r)!=null || r.collectedAt().isAfter(frozenAt)) throw new IllegalArgumentException("Receipt identity/time");
        }
        var root=TradingCalendar.JSON.createObjectNode().put("schema","zoop-briefing-market-v1")
            .put("inputFrozenAt",frozenAt.toString()).put("productionAuthorized",false);
        root.set("runContext",c.json());
        root.putObject("rights").put("status","unconfirmed").put("scope","development_read")
            .putNull("ownerRef").putNull("checkedAt").putNull("revision").putNull("revokedAt");
        var raw=root.putArray("receipts");
        for(var feed:Feed.values()) {
            var r=byFeed.get(feed);
            var n=raw.addObject().put("feed",feed.name()).put("provider",feed.provider).put("symbol",feed.symbol);
            if(r==null) { n.put("state","not_attempted"); continue; }
            var body=store.put(r.body());
            n.put("collectedAt",r.collectedAt().toString()).put("httpStatus",r.httpStatus())
                .put("sha256",body.sha256()).put("bytes",body.bytes()).put("state",r.failure()==null?"collected_ok":"fetch_failed");
        }
        var mv=root.putObject("marketVariables").put("status","available")
            .put("referenceAt",c.scheduledAt().toString()).put("rateCutoffAt",c.scheduledAt().toString())
            .put("collectedAt",frozenAt.toString());
        var indicators=mv.putArray("indicators");
        indicators.add(index(c,byFeed.get(Feed.KOSPI),Feed.KOSPI,"kospi"));
        indicators.add(index(c,byFeed.get(Feed.KOSDAQ),Feed.KOSDAQ,"kosdaq"));
        indicators.add(fx(c,byFeed.get(Feed.FX),byFeed.get(Feed.FX_HISTORY)));
        var completeness=root.putArray("completeness");
        for(var n:indicators) {
            String status=n.path("status").asString(), reason=n.path("reason").asString("");
            String state=reason.equals("not_attempted")?"not_attempted":reason.equals("collected_ok_empty")?"collected_ok_empty":status.equals("failed")
                ?(n.path("reasonCode").asString().equals("format_changed")?"format_changed":"fetch_failed")
                :status.equals("delayed")?"delayed":"collected_ok";
            // Collection success does not imply a usable value (calendar/baseline may be missing).
            // This flag describes data availability only; rights remain a separate gate.
            boolean valueAvailable=(status.equals("ok")||status.equals("delayed"))&&!n.path("value").isNull();
            completeness.addObject().put("id",n.path("id").asString()).put("state",state).put("indicatorStatus",status)
                .put("valueAvailable",valueAvailable)
                .put("reasonCode",n.path("reasonCode").isNull()?null:n.path("reasonCode").asString()).put("reason",reason.isEmpty()?null:reason);
        }
        var metadata=root.putArray("observationMetadata");
        for(var n:indicators) metadata.addObject().put("id",n.path("id").asString())
            .put("session",n.path("id").asString().equals("usdkrw")?"bank_notice":"regular_close")
            .put("timePrecision",n.path("observedAt").isNull()?"date":"instant")
            .put("normalization","HALF_UP_2_decimals; changeRate=fraction_12_decimals");
        // Freeze and replay expose the same parsed representation as the persisted bytes.
        return restore(store.put(TradingCalendar.JSON.writeValueAsBytes(root)));
    }
    private static ObjectNode index(BriefingRoundClock.Context c,PublicMarketProvider.Receipt r,Feed feed,String id) {
        var out=blank(id,"pt",feed);
        if(!usable(c,r,out)) return out;
        try {
            var response=TradingCalendar.JSON.readTree(r.body()).path("chart");
            if(!response.path("error").isNull()) throw new IllegalArgumentException();
            var results=response.path("result");
            if(!results.isArray()||results.size()!=1) throw new IllegalArgumentException();
            var result=results.get(0); var meta=result.path("meta");
            if(!meta.path("symbol").asString().equals(feed.symbol) || !meta.path("instrumentType").asString().equals("INDEX")
                    || !meta.path("exchangeTimezoneName").asString().equals("Asia/Seoul")) throw new IllegalArgumentException();
            Instant latest=meta.path("regularMarketTime").isIntegralNumber()?Instant.ofEpochSecond(meta.path("regularMarketTime").asLong()):null;
            if(latest!=null&&latest.isAfter(r.collectedAt())) throw new IllegalArgumentException();
            var times=result.path("timestamp"); var values=result.path("indicators").path("quote").get(0).path("close");
            if(!times.isArray()||!values.isArray()||times.size()!=values.size()) throw new IllegalArgumentException();
            if(times.isEmpty()) return unavailable(out,"no_data","collected_ok_empty");
            var closes=new TreeMap<LocalDate,BigDecimal>();
            for(int i=0;i<times.size();i++) {
                if(!times.get(i).isIntegralNumber()) throw new IllegalArgumentException();
                var date=Instant.ofEpochSecond(times.get(i).asLong()).atZone(TradingCalendar.KST).toLocalDate();
                if(values.get(i).isNull()) continue;
                var day=c.calendar().day(date);
                // Yahoo 1d close on an unfinished day is an intraday price, NOT a closing value.
                if(day==null||!day.open()||day.closeInstant().isAfter(c.scheduledAt())||day.closeInstant().isAfter(r.collectedAt())) continue;
                if(latest!=null&&date.equals(latest.atZone(TradingCalendar.KST).toLocalDate())&&latest.isBefore(day.closeInstant())) continue;
                if(closes.putIfAbsent(date,number(values.get(i)))!=null) throw new IllegalArgumentException();
            }
            LocalDate target=c.expectedCloseDate();
            if(target==null) return unavailable(out,"no_data","calendar_unknown");
            var value=closes.floorEntry(target);
            if(value==null) return unavailable(out,"no_data","closed_value_unavailable");
            var baselineDate=c.calendar().previous(value.getKey());
            var baseline=baselineDate==null?null:closes.get(baselineDate);
            if(baseline==null) return unavailable(out,"no_data","previous_close_unavailable");
            boolean delayed=!value.getKey().equals(target);
            fill(out,value.getValue(),value.getKey(),null,"close",baseline,baselineDate,delayed,
                delayed?"expected_close_not_received":null);
            return out;
        } catch(RuntimeException e) { return failed(out,"format_changed","provider_format_changed"); }
    }
    private static ObjectNode fx(BriefingRoundClock.Context c,PublicMarketProvider.Receipt r,PublicMarketProvider.Receipt history) {
        var out=blank("usdkrw","KRW",Feed.FX);
        if(!usable(c,r,out)||!usable(c,history,out)) return out;
        try {
            var n=TradingCalendar.JSON.readTree(r.body()).path("exchangeInfo");
            if(!n.path("reutersCode").asString().equals("FX_USDKRW")||!n.path("unit").asString().equals("KRW")
                    ||!n.path("priceDataType").asString().equals("NOTICE_ROUND")
                    ||!n.path("stockExchangeType").path("code").asString().equals("HANA")) throw new IllegalArgumentException();
            Instant at=OffsetDateTime.parse(TradingCalendar.text(n,"localTradedAt")).toInstant();
            if(at.isAfter(c.scheduledAt())||at.isAfter(r.collectedAt())) return unavailable(out,"no_data","observation_after_cutoff");
            var date=at.atZone(TradingCalendar.KST).toLocalDate();
            var baselineDate=c.calendar().previous(date);
            if(baselineDate==null) return unavailable(out,"no_data","calendar_unknown");
            var rows=TradingCalendar.JSON.readTree(history.body());
            if(!rows.isArray()) throw new IllegalArgumentException();
            if(rows.isEmpty()) return unavailable(out,"no_data","collected_ok_empty");
            BigDecimal baseline=null;
            for(var row:rows) if(LocalDate.parse(TradingCalendar.text(row,"localTradedAt")).equals(baselineDate)) {
                if(baseline!=null) throw new IllegalArgumentException();
                baseline=number(row.path("closePrice"));
            }
            var baselineDay=c.calendar().day(baselineDate);
            // Conservative end-of-date bound for a date-only bank notice; never invent its exact time.
            Instant baselineBound=baselineDate.plusDays(1).atStartOfDay(TradingCalendar.KST).toInstant();
            if(baseline==null||baselineDay==null||!baselineDay.open()||baselineBound.isAfter(history.collectedAt())
                    ||baselineBound.isAfter(c.scheduledAt())) return unavailable(out,"no_data","previous_rate_unavailable");
            boolean delayed=Duration.between(at,c.scheduledAt()).compareTo(Duration.ofMinutes(15))>0;
            fill(out,number(n.path("closePrice")),date,at,"latest",baseline,baselineDate,delayed,delayed?"rate_older_than_15m":null);
            out.withObject("source").put("name","네이버 제공 하나은행 고시 기준환율")
                .put("delayNote","은행 고시 기준환율이며 시장 체결가격/외환시장 종가가 아닙니다. 공개 endpoint의 실시간성은 보장하지 않습니다.");
            return out;
        } catch(RuntimeException e) { return failed(out,"format_changed","provider_format_changed"); }
    }
    private static boolean usable(BriefingRoundClock.Context c,PublicMarketProvider.Receipt r,ObjectNode out) {
        if(r==null) { unavailable(out,"not_connected","not_attempted"); return false; }
        if(r.failure()!=null) { failed(out,r.failure().equals("auth_failed")?"auth_failed":"temporary_failure",r.failure()); return false; }
        if(r.collectedAt().isAfter(c.scheduledAt())) { unavailable(out,"no_data","collected_after_cutoff"); return false; }
        return true;
    }
    private static ObjectNode blank(String id,String unit,Feed feed) {
        var n=TradingCalendar.JSON.createObjectNode().put("id",id).put("label",switch(id){case "kospi"->"KOSPI";case "kosdaq"->"KOSDAQ";default->"원/달러";})
            .put("unit",unit).put("status","unavailable");
        for(var field:List.of("value","valueKind","observedDate","observedAt","baseline","change","changeRate","reasonCode","reason")) n.putNull(field);
        n.putObject("source").put("provider",feed.provider).put("name",feed.provider.equals("yahoo")?"Yahoo Finance 공개 지수":"네이버 공개 환율")
            .put("official",false).put("symbol",feed.symbol).put("delayNote","비공식 키 없는 공개 endpoint이며 지연될 수 있습니다.")
            .put("url",feed.provider.equals("yahoo")?"https://finance.yahoo.com/quote/"+feed.symbol:"https://stock.naver.com/marketindex/exchange/FX_USDKRW");
        return n;
    }
    private static void fill(ObjectNode n,BigDecimal value,LocalDate date,Instant at,String kind,BigDecimal baseline,
            LocalDate baselineDate,boolean delayed,String reason) {
        n.put("status",delayed?"delayed":"ok").put("value",value).put("valueKind",kind).put("observedDate",date.toString())
            .put("observedAt",at==null?null:at.atZone(TradingCalendar.KST).toOffsetDateTime().toString());
        n.putObject("baseline").put("value",baseline).put("date",baselineDate.toString()).putNull("at");
        var change=value.subtract(baseline);
        n.put("change",change).put("changeRate",change.divide(baseline,12,RoundingMode.HALF_UP))
            .putNull("reasonCode").put("reason",reason);
    }
    private static BigDecimal number(JsonNode n) {
        if(!n.isNumber()&&!n.isString()) throw new IllegalArgumentException();
        String text=n.isString()?n.asString():n.toString();
        if(!text.matches("[0-9]+(?:,[0-9]{3})*(?:\\.[0-9]+)?")) throw new IllegalArgumentException();
        var value=new BigDecimal(text.replace(",","")).setScale(2,RoundingMode.HALF_UP);
        if(value.signum()<=0) throw new IllegalArgumentException();
        return value;
    }
    private static ObjectNode unavailable(ObjectNode n,String code,String reason) { return n.put("status","unavailable").put("reasonCode",code).put("reason",reason); }
    private static ObjectNode failed(ObjectNode n,String code,String reason) { return n.put("status","failed").put("reasonCode",code).put("reason",reason); }
}
