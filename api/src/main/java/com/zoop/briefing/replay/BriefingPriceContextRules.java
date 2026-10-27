package com.zoop.briefing.replay;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.math.*;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.*;

/** Deterministic source observations. Price movement neither verifies a business condition nor proves causality. */
public final class BriefingPriceContextRules {
    public static final String SCHEMA = "zoop-company-price-context-v1";
    private static final String LIMIT = "기사와 가격의 시간상 전후 관측이며 인과관계·사업 조건 확인·예측 적중을 입증하지 않습니다.";
    private BriefingPriceContextRules() { }
    record Point(Instant at, BigDecimal value, String kind) { }
    record Bar(Instant at, LocalDate date, BigDecimal open, BigDecimal high, BigDecimal low, BigDecimal close, BigDecimal volume) { }

    public static byte[] raw(StrictJson.Obj receipt, Path root) {
        String sha = receipt.string("sha256"); require(sha.matches("[0-9a-f]{64}"), "response_sha");
        try {
            Path p = root.resolve("price-context-responses/" + sha + ".bin");
            require(Files.isRegularFile(p, LinkOption.NOFOLLOW_LINKS) && Files.size(p) <= 2_000_000, "response_file");
            byte[] bytes = Files.readAllBytes(p);
            require(bytes.length == receipt.count("bytes") && Canonical.sha256(bytes).equals(sha), "response_binding");
            return bytes;
        } catch (java.io.IOException e) { throw new IllegalArgumentException("Price context archive unavailable", e); }
    }
    private static StrictJson.Obj response(StrictJson.Obj receipt, String cid, String period, Instant cutoff, Path root) {
        StrictJson.Obj q = receipt.object("request");
        require(cid.equals(q.string("companyId")) && period.equals(q.string("period"))
                && cutoff.equals(Instant.parse(q.string("cutoff"))) && Canonical.digest(q.node()).equals(receipt.string("id")), "request_binding");
        Instant.parse(receipt.string("collectedAt"));
        StrictJson.Obj data = StrictJson.parseObject(raw(receipt, root));
        if (receipt.count("httpStatus") != 200) return null;
        require(cid.equals(data.string("companyId")) && period.equals(data.string("period")), "response_identity");
        if ("unavailable".equals(data.string("status"))) return null;
        require("available".equals(data.string("status")) && "toss".equals(data.object("source").string("provider"))
                && data.object("source").bool("official"), "provider");
        require("1d".equals(period) ? "5m".equals(data.string("interval")) : "1d".equals(data.string("interval")), "resolution");
        return data;
    }
    private static BigDecimal number(JsonNode value, boolean zero) {
        require(value != null && value.isNumber(), "number");
        BigDecimal n = value.decimalValue(); require(zero ? n.signum() >= 0 : n.signum() > 0, "positive_price"); return n;
    }
    private static List<Bar> bars(StrictJson.Obj data, ZoneId zone) {
        List<Bar> out = new ArrayList<>(); Instant previous = null;
        for (StrictJson.Obj b : data.objects("points")) {
            OffsetDateTime time = OffsetDateTime.parse(b.string("time"));
            require(time.getOffset().equals(time.toInstant().atZone(zone).getOffset())
                    && (previous == null || time.toInstant().isAfter(previous)), "bar_order_zone");
            BigDecimal o = number(b.raw("open"), false), h = number(b.raw("high"), false), l = number(b.raw("low"), false), c = number(b.raw("close"), false);
            require(h.compareTo(o.max(c)) >= 0 && l.compareTo(o.min(c)) <= 0 && h.compareTo(l) >= 0, "ohlc");
            out.add(new Bar(time.toInstant(), time.toLocalDate(), o, h, l, c,
                    b.isNull("volume") ? null : number(b.raw("volume"), true))); previous = time.toInstant();
        }
        require(out.size() <= 10000, "bar_limit"); return out;
    }
    private static String decimal(BigDecimal value) { return value.stripTrailingZeros().toPlainString(); }
    private static String percent(BigDecimal a, BigDecimal b) { return a.subtract(b).multiply(BigDecimal.valueOf(100)).divide(b, 2, RoundingMode.HALF_UP).toPlainString(); }
    private static String signed(String s) { return new BigDecimal(s).signum() > 0 ? "+" + s : s; }
    private static ObjectNode point(Point p) { return StrictJson.newObject().put("value", decimal(p.value())).put("observedAt", p.at().toString()).put("kind", p.kind()); }
    private static Point point(StrictJson.Obj p) { return new Point(Instant.parse(p.string("observedAt")), new BigDecimal(p.string("value")), p.string("kind")); }

    static ObjectNode company(StrictJson.Obj refs, StrictJson.Obj c, StrictJson.Obj review,
            StrictJson.Obj priorCompany, Map<String, StrictJson.Obj> receipts, Path root) {
        String cid = c.string("companyId"), currency = cid.startsWith("KRX:") ? "KRW" : "USD";
        require(cid.matches("KRX:[0-9]{6}|(?:NASDAQ|NYSE|AMEX):[A-Z.]{1,10}"), "company");
        ZoneId zone = ZoneId.of("KRW".equals(currency) ? "Asia/Seoul" : "America/New_York");
        Instant cutoff = Instant.parse(review.string("cutoff"));
        StrictJson.Obj dailyReceipt = receipts.get(refs.string("daily")), minuteReceipt = receipts.get(refs.string("intraday"));
        require(dailyReceipt != null && minuteReceipt != null, "receipt_missing");
        StrictJson.Obj daily = response(dailyReceipt, cid, "1m", cutoff, root), minute = response(minuteReceipt, cid, "1d", cutoff, root);
        ObjectNode out = StrictJson.newObject().put("companyId", cid).put("companyName", c.string("companyName"))
                .put("currency", currency).put("provider", "toss").put("cutoff", cutoff.toString());
        out.putArray("responseSha256s").add(dailyReceipt.string("sha256")).add(minuteReceipt.string("sha256"));
        if (minute == null) return out.put("status", "unavailable").put("reason", "해당 마감 기준 분봉을 제공받지 못해 가격 흐름을 평가하지 않습니다.");
        require(currency.equals(minute.string("currency")) && (daily == null || currency.equals(daily.string("currency"))), "currency");
        StrictJson.Obj range = minute.object("range");
        Instant start = Instant.parse(range.string("from")), end = Instant.parse(range.string("to")); LocalDate session = LocalDate.parse(range.string("sessionDate"));
        require(start.isBefore(end) && !start.isAfter(cutoff) && start.atZone(zone).toLocalDate().equals(session), "session_range");
        List<Bar> eligible = new ArrayList<>();
        for (Bar b : bars(minute, zone)) {
            Instant finish = b.at().plusSeconds(300);
            if (!b.at().isBefore(start) && !finish.isAfter(cutoff) && !finish.isAfter(end)) {
                require(b.date().equals(session), "session_date"); eligible.add(b);
            }
        }
        if (eligible.isEmpty()) return out.put("status", "unavailable").put("reason", "마감 전에 완료된 5분봉이 없어 가격 변화를 평가하지 않습니다.");
        List<Bar> ds = daily == null ? List.of() : bars(daily, zone);
        Bar official = null, baseline = null;
        boolean continuous = eligible.getFirst().at().equals(start);
        Instant next = start;
        for (Bar b : eligible) { continuous &= next.equals(b.at()); next = b.at().plusSeconds(300); }
        boolean complete = end.isBefore(cutoff) && continuous && next.equals(end);
        for (Bar b : ds) {
            if (b.date().isBefore(session)) baseline = b;
            if (complete && b.date().equals(session)) official = b;
        }
        Bar last = eligible.getLast(); Point latest = new Point(last.at().plusSeconds(300), last.close(), "five_minute_close");
        if (official != null) latest = new Point(end, official.close(), "daily_close");
        out.put("status", "available").put("sessionDate", session.toString()).put("exchangeTimezone", zone.getId())
                .put("completeSession", complete).put("barCount", eligible.size()); out.set("latest", point(latest));
        ObjectNode day = out.putObject("day");
        if (baseline != null) day.put("baselineDate", baseline.date().toString()).put("baselineClose", decimal(baseline.close()));
        else day.putNull("baselineDate").putNull("baselineClose");
        BigDecimal current = latest.value();
        if (baseline != null) day.put("changeRatePercent", percent(current, baseline.close())); else day.putNull("changeRatePercent");
        Bar sessionDay = official;
        day.put("kind", sessionDay == null ? "completed_five_minute_bars" : "provider_daily_bar");
        BigDecimal high = sessionDay != null ? sessionDay.high() : eligible.stream().map(Bar::high).max(BigDecimal::compareTo).orElseThrow();
        BigDecimal low = sessionDay != null ? sessionDay.low() : eligible.stream().map(Bar::low).min(BigDecimal::compareTo).orElseThrow();
        day.put("open", decimal(sessionDay == null ? eligible.getFirst().open() : sessionDay.open()))
                .put("high", decimal(high)).put("low", decimal(low)).put("closeOrLast", decimal(current));
        BigDecimal volume = sessionDay != null ? sessionDay.volume() : eligible.stream().anyMatch(b -> b.volume() == null) ? null
                : eligible.stream().map(Bar::volume).reduce(BigDecimal.ZERO, BigDecimal::add);
        if (volume == null) day.putNull("volume"); else day.put("volume", decimal(volume));
        day.put("from", start.toString()).put("to", latest.at().toString());
        String summary = session + ("USD".equals(currency) ? " 미국 정규장" : " 국내 정규장") + (official == null ? " 마감 전 완료 봉 기준 " : " 종가 ")
                + decimal(current) + " " + currency;
        if (baseline != null) summary += ", " + baseline.date() + " 제공 종가 대비 " + signed(percent(current, baseline.close())) + "%입니다.";
        else summary += "입니다. 비교 종가는 미제공입니다.";
        out.put("summary", summary);
        String retreat = percent(current, high);
        out.put("flow", "장중 관측 고점 " + decimal(high) + "·저점 " + decimal(low) + " " + currency + ". "
                + (official != null ? "종가는" : "마지막 완료 봉은") + " 고점 대비 " + signed(retreat) + "%입니다."
                + (complete ? "" : " 전체 장이 아닌 마감 전 확보 구간입니다."));
        ArrayNode reactions = out.putArray("news"); boolean reactionAvailable = false;
        for (String sid : c.object("newInformation").strings("evidenceIds")) {
            StrictJson.Obj source = review.object("sources").object(sid); Instant newsAt = Instant.parse(source.string("publishedAt"));
            require(!newsAt.isAfter(cutoff), "future_news");
            Point pre = null;
            for (Bar b : eligible) if (!b.at().plusSeconds(300).isAfter(newsAt)) pre = new Point(b.at().plusSeconds(300), b.close(), "five_minute_close");
            if (!latest.at().isAfter(newsAt)) pre = latest;
            if (priorCompany != null && "available".equals(priorCompany.string("status"))) {
                Point p = point(priorCompany.object("latest"));
                if (!p.at().isAfter(newsAt) && (pre == null || p.at().isAfter(pre.at()))) pre = p;
            }
            int post = (int) eligible.stream().filter(b -> !b.at().isBefore(newsAt)).count();
            String timing = newsAt.isBefore(start) ? "before_session" : !newsAt.isBefore(end) ? "after_session" : "during_session";
            String state = post == 0 ? "no_post_news_trade" : pre == null ? "event_window_unavailable" : "observed";
            ObjectNode item = reactions.addObject().put("evidenceId", sid).put("publishedAt", newsAt.toString())
                    .put("timing", timing).put("status", state).put("postNewsBars", post);
            if (pre == null) item.putNull("before"); else item.set("before", point(pre));
            if ("observed".equals(state)) {
                String rate = percent(current, pre.value()); item.put("changeRatePercent", rate);
                item.put("observation", "공개 전 마지막 확인 가격 " + decimal(pre.value()) + " → 최근 확인 가격 " + decimal(current) + " " + currency
                        + " (" + signed(rate) + "%). 기사 후 시작·완료한 5분봉 " + post + "개가 있습니다."); reactionAvailable = true;
            } else {
                item.putNull("changeRatePercent");
                item.put("observation", post == 0 ? "기사 공개 후 거래를 보여 주는 완료 봉이 없습니다. 이 회차 가격을 해당 기사 반응으로 평가하지 않습니다."
                        : "최신 거래는 기사 이후지만 공개 직전 가격 구간을 확보하지 못했습니다. 기사 전후 반응의 수치는 유보합니다.");
            }
        }
        ObjectNode am = out.putObject("sinceMorning");
        boolean sameDayMorning = "evening".equals(review.string("edition")) && priorCompany != null;
        if (!sameDayMorning || !"available".equals(priorCompany.string("status"))) {
            am.put("status", "unavailable").put("observation", "같은 날 출근의 해당 기업 가격 관측이 없어 아침 이후 비교를 유보합니다.");
        } else {
            Point p = point(priorCompany.object("latest")); am.set("before", point(p));
            if (latest.at().isAfter(p.at())) am.put("status", "available").put("changeRatePercent", percent(current, p.value()))
                    .put("observation", "출근 가격 " + decimal(p.value()) + " → 회차 기준 " + decimal(current) + " " + currency + " (" + signed(percent(current, p.value())) + "%).");
            else am.put("status", latest.value().compareTo(p.value()) == 0 ? "no_new_session" : "revised_observation")
                    .put("observation", latest.value().compareTo(p.value()) == 0 ? "출근 이후 새 정규장 관측이 없어 가격 변화를 평가하지 않습니다." : "동일 시각의 공급자 값이 달라져 새 거래의 변화로 해석하지 않습니다.");
        }
        out.put("interpretation", reactionAvailable ? "기사 전후의 실제 가격 변화와 사업상 확인 조건을 함께 살펴봅니다. 시장·업종·동시 뉴스와의 비교가 없어 기사 효과나 사업 판단의 적중으로 단정하지 않습니다."
                : "현재 가격은 거래 맥락으로 활용합니다. 기사 후 관측 또는 공개 직전 비교 구간이 부족해, 기존 사업 판단을 주가만으로 강화·약화하지 않습니다.");
        out.put("limitation", LIMIT); return out;
    }

    public static ObjectNode apply(StrictJson.Obj row, StrictJson.Obj layer, StrictJson.Obj review, JsonNode previous, Path root) {
        require(SCHEMA.equals(layer.string("schemaVersion")) && row.string("roundId").equals(review.string("roundId"))
                && row.string("reviewVersion").equals(review.string("resultVersion")), "review_binding");
        Map<String, StrictJson.Obj> receipts = new HashMap<>(), refs = new LinkedHashMap<>();
        require(layer.objects("receipts").size() <= 96, "receipt_limit");
        for (StrictJson.Obj r : layer.objects("receipts")) require(receipts.putIfAbsent(r.string("id"), r) == null, "duplicate_receipt");
        for (StrictJson.Obj r : row.objects("companies")) require(refs.putIfAbsent(r.string("companyId"), r) == null, "duplicate_company");
        require(refs.keySet().equals(new HashSet<>(review.objects("companies").stream().map(c -> c.string("companyId")).toList())), "company_coverage");
        Map<String, StrictJson.Obj> prior = new HashMap<>();
        if (previous != null && previous.isObject()) require(Instant.parse(StrictJson.Obj.of(previous).string("cutoff"))
                .isBefore(Instant.parse(review.string("cutoff"))), "future_previous_snapshot");
        if (previous != null && previous.isObject() && "evening".equals(review.string("edition"))) {
            StrictJson.Obj p = StrictJson.Obj.of(previous);
            if (review.string("date").equals(p.string("date")) && "morning".equals(p.string("edition")))
                for (StrictJson.Obj c : p.objects("companies")) prior.put(c.string("companyId"), c);
        }
        // AM also uses the actual immediately previous price snapshot as an event anchor, never a future quote.
        if (previous != null && previous.isObject() && "morning".equals(review.string("edition")))
            for (StrictJson.Obj c : StrictJson.Obj.of(previous).objects("companies")) prior.put(c.string("companyId"), c);
        ObjectNode result = StrictJson.newObject().put("schemaVersion", SCHEMA).put("status", "derived")
                .put("roundId", review.string("roundId")).put("date", review.string("date")).put("edition", review.string("edition"))
                .put("cutoff", review.string("cutoff")).put("reviewVersion", review.string("resultVersion"))
                .put("generatedAt", layer.string("generatedAt")).put("authorship", "deterministic_price_observation")
                .put("scopeNote", "토스 API 보존 응답의 회차 마감 이전 관측으로 재구성했습니다. 사후 수집이며 당시 수집·예측 적중을 입증하지 않습니다.");
        Instant.parse(layer.string("generatedAt")); ArrayNode companies = result.putArray("companies");
        for (StrictJson.Obj c : review.objects("companies")) companies.add(company(refs.get(c.string("companyId")), c, review, prior.get(c.string("companyId")), receipts, root));
        result.put("resultVersion", "price-context-v1-" + Canonical.digest(result));
        if (layer.has("outlookIntegrationVersion")) {
            require(BriefingPriceOutlookRules.VERSION.equals(layer.string("outlookIntegrationVersion")), "outlook_version");
            BriefingPriceOutlookRules.enrich(result, review);
        }
        return result;
    }

    public static void validateProjection(StrictJson.Obj context, StrictJson.Obj review) {
        require(SCHEMA.equals(context.string("schemaVersion")) && "derived".equals(context.string("status"))
                && "deterministic_price_observation".equals(context.string("authorship"))
                && context.string("roundId").equals(review.string("roundId")) && context.string("cutoff").equals(review.string("cutoff"))
                && context.string("date").equals(review.string("date")) && context.string("edition").equals(review.string("edition"))
                && context.string("reviewVersion").equals(review.string("resultVersion")), "projection_binding");
        ObjectNode copy = (ObjectNode) context.node().deepCopy(); copy.remove("resultVersion");
        require(("price-context-v1-" + (context.has("outlookIntegrationVersion")
                ? Canonical.sha256(Canonical.appBytes(copy)) : Canonical.digest(copy))).equals(context.string("resultVersion")), "projection_version");
        require(context.objects("companies").stream().map(c -> c.string("companyId")).toList().equals(review.objects("companies").stream().map(c -> c.string("companyId")).toList()), "projection_companies");
        for (StrictJson.Obj c : context.objects("companies")) if ("available".equals(c.string("status"))) {
            require(!Instant.parse(c.object("latest").string("observedAt")).isAfter(Instant.parse(context.string("cutoff"))), "future_price");
            for (StrictJson.Obj news : c.objects("news")) require(review.object("sources").has(news.string("evidenceId"))
                    && Instant.parse(news.string("publishedAt")).equals(Instant.parse(review.object("sources").object(news.string("evidenceId")).string("publishedAt"))), "news_binding");
        }
        if (context.has("outlookIntegrationVersion")) BriefingPriceOutlookRules.validate(context, review);
    }
    private static void require(boolean ok, String why) { if (!ok) throw new IllegalArgumentException("Price context rejected: " + why); }
}
