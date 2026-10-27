package com.zoop.briefing.replay;

import com.zoop.common.json.StrictJson;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.node.*;
import static org.junit.jupiter.api.Assertions.*;

class BriefingPriceOutlookRulesTest {
    ObjectNode review() {
        return (ObjectNode) StrictJson.parseObject("""
            {"cutoff":"2026-10-23T00:20:00Z","edition":"morning",
             "sources":{"s":{"publishedAt":"2026-10-21T20:01:00Z"}},
             "companies":[{"companyId":"NASDAQ:META","stance":"watch",
               "judgment":{"text":"발행 조건은 미확정입니다.","evidenceIds":["s"]},
               "takeaway":{"text":"후속 조건을 관찰합니다.","evidenceIds":["s"]},
               "watch":[{"text":"발행 규모를 확인합니다.","evidenceIds":["s"]}]}],
             "marketVariables":{"status":"available","indicators":[
              {"id":"kospi","label":"KOSPI","value":90.5,"unit":"pt","valueKind":"close","observedDate":"2026-10-22","observedAt":null,
                "status":"delayed","source":{"name":"synthetic","url":"https://example.com"},"baseline":{"date":"2026-10-20","value":100}},
              {"id":"usdkrw","label":"원/달러","value":1300,"unit":"KRW","valueKind":"reference","observedDate":"2026-10-22","observedAt":null,
                "status":"delayed","source":{"name":"synthetic","url":"https://example.com"},"baseline":{"date":"2026-10-21","value":1310}}
             ]}}
            """).node();
    }
    ObjectNode context() {
        return (ObjectNode) StrictJson.parseObject("""
            {"companies":[{"companyId":"NASDAQ:META","status":"available","sessionDate":"2026-10-22","completeSession":true,
              "day":{"kind":"provider_daily_bar","baselineDate":"2026-10-21","changeRatePercent":"-6.98"},"summary":"10/22 종가는 648.85 USD, 10/21 대비 -6.98%입니다.",
              "sinceMorning":{"observation":"새 정규장 관측이 없습니다."},
              "news":[{"evidenceId":"s","status":"observed","publishedAt":"2026-10-21T20:01:00Z","changeRatePercent":"-6.98","postNewsBars":78}]}]}
            """).node();
    }
    @Test void joinsPricesIntoTheActualOutlookWithoutChangingBusinessOrStance() {
        var c = context(); var r = StrictJson.Obj.of(review()); BriefingPriceOutlookRules.enrich(c, r);
        var o = c.path("companies").get(0).path("outlook");
        assertEquals(r.objects("companies").getFirst().raw("judgment"), o.path("businessJudgment"));
        assertEquals("watch", o.path("stance").stringValue());
        assertTrue(o.path("text").stringValue().contains("-6.98%"));
        assertTrue(o.path("text").stringValue().contains("뉴스의 효과나 사업 조건 확인을 뜻하지 않습니다"));
        assertTrue(o.path("takeaway").stringValue().contains("2026-10-21 대비"));
        BriefingPriceOutlookRules.validate(StrictJson.Obj.of(c), r);
        BriefingPriceOutlookRules.validate(StrictJson.parseObject(StrictJson.write(c)), r);
    }
    @Test void datedMultiDayIndexChangeIsNotRelabeledPreviousDayOrForeignBenchmark() {
        var c = context(); BriefingPriceOutlookRules.enrich(c, StrictJson.Obj.of(review()));
        var rows = c.path("marketReference").path("indicators");
        assertEquals("-9.50", rows.get(0).path("changeRatePercent").stringValue());
        assertTrue(rows.get(0).path("text").stringValue().contains("2026-10-20 종가 대비"));
        assertFalse(rows.get(0).path("text").stringValue().contains("전일"));
        assertTrue(rows.get(1).path("text").stringValue().contains("일별 고시값"));
        assertTrue(c.path("companies").get(0).path("outlook").path("marketNote").stringValue().contains("직접 비교지수"));
    }
    @Test void morningCannotUseLaterSameDayCloseAndMissingPriceDoesNotChangeJudgment() {
        var r = review(); ((ObjectNode) r.path("marketVariables").path("indicators").get(0)).put("observedDate", "2026-10-23");
        var c = context(); var company = (ObjectNode) c.path("companies").get(0); company.put("status", "unavailable").put("reason", "시세 없음");
        BriefingPriceOutlookRules.enrich(c, StrictJson.Obj.of(r));
        assertEquals(1, c.path("marketReference").path("indicators").size());
        assertTrue(company.path("outlook").path("text").stringValue().contains("시세 없음"));
        assertEquals("watch", company.path("outlook").path("stance").stringValue());
    }
    @Test void afterCloseNoTradeIsNotRenderedAsNewsReactionAndRewriteIsRejected() {
        var c = context(); var news = (ObjectNode) c.path("companies").get(0).path("news").get(0);
        news.put("status", "no_post_news_trade").put("postNewsBars", 0).putNull("changeRatePercent");
        var r = StrictJson.Obj.of(review()); BriefingPriceOutlookRules.enrich(c, r);
        var outlook = (ObjectNode) c.path("companies").get(0).path("outlook");
        assertTrue(outlook.path("text").stringValue().contains("새 소식의 반응으로 판단하지 않습니다"));
        outlook.put("text", "주가 하락은 기사 때문이며 사업 악화입니다.");
        assertThrows(IllegalArgumentException.class, () -> BriefingPriceOutlookRules.validate(StrictJson.Obj.of(c), r));
    }
}
