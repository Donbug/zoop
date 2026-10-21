package com.zoop.briefing.replay;

import com.zoop.common.json.StrictJson;
import java.util.List;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;
import static org.junit.jupiter.api.Assertions.*;

/** Authored guard bypasses: a verdict alone must not authorize ambiguous facts/conditions. */
class BriefingMarketQualityTest {
    private ObjectNode claim(String kind) {
        ObjectNode value = StrictJson.newObject().put("kind", kind);
        for (String key : List.of("evidenceIds", "indicatorIds", "previousForecastIds", "previousPublicationIds", "evaluationIds", "conditions")) value.putArray(key);
        return value;
    }
    private void check(ObjectNode claim) {
        ObjectNode news = StrictJson.newObject();
        var sources = news.putArray("selected").addObject().putArray("sources");
        sources.addObject().put("evidenceId", "selected").put("documentId", "doc-one");
        ObjectNode broad = StrictJson.newObject();
        var docs = broad.putArray("documents");
        docs.addObject().put("documentId", "doc-one").putArray("sources").addObject().put("evidenceId", "same-document");
        docs.addObject().put("documentId", "doc-two").putArray("sources").addObject().put("evidenceId", "other-document");
        ObjectNode summary = StrictJson.newObject(); summary.putArray("claims").add(claim);
        BriefingMarketContextRules.qualityClaims(StrictJson.Obj.of(summary), StrictJson.Obj.of(news), StrictJson.Obj.of(broad));
    }
    @Test void sameDocumentSpansAndSingleIndicatorCanPassButIndependentFactsCannotBeCombined() {
        ObjectNode fact = claim("fact"); ((ArrayNode) fact.get("evidenceIds")).add("selected").add("same-document");
        assertDoesNotThrow(() -> check(fact));
        ((ArrayNode) fact.get("evidenceIds")).add("other-document"); assertThrows(IllegalArgumentException.class, () -> check(fact));
        ObjectNode indicators = claim("fact"); ((ArrayNode) indicators.get("indicatorIds")).add("kospi");
        assertDoesNotThrow(() -> check(indicators));
        ((ArrayNode) indicators.get("indicatorIds")).add("kosdaq"); assertThrows(IllegalArgumentException.class, () -> check(indicators));
    }
    @Test void unownedEvidenceAndPriorSummaryCannotBecomeCurrentFact() {
        ObjectNode fact = claim("fact"); ((ArrayNode) fact.get("evidenceIds")).add("unowned");
        assertThrows(IllegalArgumentException.class, () -> check(fact));
        ((ArrayNode) fact.get("evidenceIds")).removeAll().add("selected");
        ((ArrayNode) fact.get("previousPublicationIds")).add("old"); assertThrows(IllegalArgumentException.class, () -> check(fact));
    }
    @Test void unverifiableAndCircularConditionsFailWithoutRemovingBasicOutlook() {
        ObjectNode forecast = claim("forecast"); assertDoesNotThrow(() -> check(forecast));
        for (String condition : List.of("지수가 오르면 상승", "기대가 확산되면")) {
            ((ArrayNode) forecast.get("conditions")).removeAll().add(condition);
            assertThrows(IllegalArgumentException.class, () -> check(forecast));
        }
    }
}
