package com.zoop.briefing.replay;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.math.*;
import java.time.*;
import java.util.*;
import tools.jackson.databind.node.*;

/** Source-bound business judgment plus measured prices, without causal or investment-outcome labels. */
public final class BriefingPriceOutlookRules {
    public static final String VERSION = "zoop-company-price-outlook-v1";
    private BriefingPriceOutlookRules() { }
    private static String signed(String s) { return new BigDecimal(s).signum() > 0 ? "+" + s : s; }
    private static String rate(BigDecimal value, BigDecimal base) {
        return value.subtract(base).multiply(BigDecimal.valueOf(100)).divide(base, 2, RoundingMode.HALF_UP).toPlainString();
    }
    private static ObjectNode market(StrictJson.Obj review) {
        var m = review.object("marketVariables");
        if ("available".equals(m.string("status"))) for (var i : m.objects("indicators")) {
            for (String key : List.of("id", "label", "value", "unit", "valueKind", "observedDate", "observedAt", "status", "source", "baseline"))
                if (!i.has(key)) throw new IllegalArgumentException("Price market indicator missing field: " + key);
        }
        var out = StrictJson.newObject().put("status", "unavailable").put("snapshotSha256", Canonical.sha256(Canonical.appBytes(m.node())));
        var rows = out.putArray("indicators"); var cutoff = Instant.parse(review.string("cutoff"));
        if ("available".equals(m.string("status"))) for (var i : m.objects("indicators")) {
            if (!List.of("kospi", "kosdaq", "usdkrw").contains(i.string("id"))
                    || !List.of("ok", "delayed").contains(i.string("status")) || i.isNull("value")) continue;
            var date = LocalDate.parse(i.string("observedDate"));
            if (date.isAfter(cutoff.atZone(ZoneId.of("Asia/Seoul")).toLocalDate())) continue;
            if (!i.isNull("observedAt") && Instant.parse(i.string("observedAt")).isAfter(cutoff)) continue;
            if (i.raw("value").decimalValue().signum() <= 0 || (i.isNull("observedAt")
                    && !"close".equals(i.string("valueKind"))
                    && !date.isBefore(cutoff.atZone(ZoneId.of("Asia/Seoul")).toLocalDate()))) continue;
            // Date-only closes are available only after the Korean regular session, not at 09:20.
            if (i.isNull("observedAt") && "close".equals(i.string("valueKind"))
                    && date.atTime(15, 30).atZone(ZoneId.of("Asia/Seoul")).toInstant().isAfter(cutoff)) continue;
            var row = rows.addObject();
            for (var key : List.of("id", "label", "value", "unit", "valueKind", "observedDate", "observedAt", "status", "source")) row.set(key, i.raw(key).deepCopy());
            String kind = "reference".equals(i.string("valueKind")) ? "일별 고시값" : "close".equals(i.string("valueKind")) ? "종가" : "관측값";
            String text = i.string("label") + " " + date + " " + kind + " " + i.raw("value").decimalValue().stripTrailingZeros().toPlainString() + " " + ("KRW".equals(i.string("unit")) ? "원" : i.string("unit"));
            row.putNull("baselineDate").putNull("changeRatePercent");
            if (!i.isNull("baseline")) {
                var base = i.object("baseline"); var from = LocalDate.parse(base.string("date"));
                if (from.isBefore(date) && !base.isNull("value") && base.raw("value").decimalValue().signum() > 0) {
                    var pct = rate(i.raw("value").decimalValue(), base.raw("value").decimalValue());
                    row.put("baselineDate", from.toString()).put("changeRatePercent", pct);
                    text += ", " + from + " " + kind + " 대비 " + signed(pct) + "%";
                }
            }
            row.put("text", text + ("delayed".equals(i.string("status")) ? " · 지연 자료" : ""));
        }
        if (!rows.isEmpty()) out.put("status", "available");
        out.put("note", "각 지표의 관측일·비교일을 그대로 표시합니다. 거래 구간·통화·상장 시장이 다른 기업과 직접 비교하거나 뉴스 원인으로 사용하지 않습니다.");
        return out;
    }
    static ObjectNode outlook(StrictJson.Obj c, StrictJson.Obj price, StrictJson.Obj review) {
        var out = StrictJson.newObject().put("schemaVersion", VERSION).put("authorship", "source_bound_composition")
                .put("stance", c.string("stance"));
        out.set("businessJudgment", c.raw("judgment").deepCopy());
        var ids = new LinkedHashSet<>(c.object("judgment").strings("evidenceIds"));
        ids.addAll(c.object("takeaway").strings("evidenceIds"));
        String business = c.object("judgment").string("text"), compact = c.object("takeaway").string("text");
        String observation, shortPrice, next;
        if ("available".equals(price.string("status"))) {
            var day = price.object("day");
            shortPrice = price.string("sessionDate") + ("provider_daily_bar".equals(day.string("kind")) ? " 종가" : " 완료 봉")
                    + (day.isNull("changeRatePercent") ? " · 비교값 없음" : " " + signed(day.string("changeRatePercent")) + "% (" + day.string("baselineDate") + " 대비)");
            observation = price.string("summary");
            if ("evening".equals(review.string("edition"))) observation += " " + price.object("sinceMorning").string("observation");
            var news = price.objects("news");
            var observed = news.stream().filter(n -> "observed".equals(n.string("status"))).findFirst();
            if (observed.isPresent()) {
                var n = observed.get(); ids.add(n.string("evidenceId"));
                observation += " " + Instant.parse(n.string("publishedAt")).atZone(ZoneId.of("Asia/Seoul"))
                        .format(java.time.format.DateTimeFormatter.ofPattern("MM/dd HH:mm 'KST'"))
                        + " 기사 공개 전 마지막 확인가 대비 " + signed(n.string("changeRatePercent"))
                        + "%이며, 기사 이후 시작·완료한 봉 " + n.count("postNewsBars") + "개를 확인했습니다.";
                String direction = day.isNull("changeRatePercent") ? "가격 움직임" : new BigDecimal(day.string("changeRatePercent")).signum() < 0 ? "주가 하락" : new BigDecimal(day.string("changeRatePercent")).signum() > 0 ? "주가 상승" : "주가 보합";
                next = direction + "이 관측됐지만, 가격만으로 기존 사업 판단을 높이거나 낮추지 않습니다. 뉴스의 효과나 사업 조건 확인을 뜻하지 않습니다.";
            } else if (!news.isEmpty() && news.stream().allMatch(n -> "no_post_news_trade".equals(n.string("status")))) {
                next = "기사 후 정규장 관측이 없어 이 가격을 새 소식의 반응으로 판단하지 않습니다.";
            } else next = "기사 공개 직전 비교 구간이 부족해 뉴스 전후 가격 반응 평가는 유보합니다.";
        } else {
            observation = price.string("reason"); shortPrice = "회차 기준 가격 흐름 미확보";
            next = "가격 자료가 부족하므로 사업 근거로 확인할 조건을 먼저 추적합니다.";
        }
        if (!c.objects("watch").isEmpty()) {
            var watch = c.objects("watch").getLast(); ids.addAll(watch.strings("evidenceIds"));
            next += " " + ("evening".equals(review.string("edition")) ? "다음 거래일에는 " : "오늘은 ") + watch.string("text");
        }
        out.put("priceObservation", observation).put("nextCheck", next)
                .put("takeaway", compact + " " + shortPrice + ".")
                .put("text", business + " 가격 측면에서는 " + observation + " " + next)
                .put("marketNote", c.string("companyId").startsWith("KRX:")
                        ? "국내 지수는 아래 기간의 시장 참고값입니다. 종목과 관측 구간이 일치하지 않으면 상대 성과를 계산하지 않습니다."
                        : "국내 지수·원/달러는 시장 참고값이며 이 해외기업의 직접 비교지수나 같은 거래 구간의 가격 변화율이 아닙니다.");
        var evidence = out.putArray("evidenceIds"); ids.forEach(evidence::add); return out;
    }
    public static void enrich(ObjectNode context, StrictJson.Obj review) {
        context.put("outlookIntegrationVersion", VERSION);
        try { context.set("marketReference", market(review)); }
        catch (StrictJson.Malformed missing) { throw new IllegalArgumentException("Price outlook market fields are incomplete", missing); }
        var companies = StrictJson.Obj.of(context).objects("companies");
        for (var price : companies) {
            var c = review.objects("companies").stream().filter(x -> price.string("companyId").equals(x.string("companyId"))).findFirst().orElseThrow();
            try { ((ObjectNode) price.node()).set("outlook", outlook(c, price, review)); }
            catch (StrictJson.Malformed missing) { throw new IllegalArgumentException("Price outlook fields are incomplete for " + price.string("companyId"), missing); }
        }
        context.remove("resultVersion"); context.put("resultVersion", "price-context-v1-" + Canonical.sha256(Canonical.appBytes(context)));
    }
    public static void validate(StrictJson.Obj context, StrictJson.Obj review) {
        if (!VERSION.equals(context.string("outlookIntegrationVersion"))) throw new IllegalArgumentException("Unknown price outlook version");
        var expected = (ObjectNode) context.node().deepCopy(); enrich(expected, review);
        if (!expected.equals(context.node())) throw new IllegalArgumentException("Price outlook source binding mismatch");
    }
}
