package com.zoop.briefing.replay;

import com.zoop.common.json.StrictJson;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.node.ObjectNode;
import static org.junit.jupiter.api.Assertions.*;

class BriefingMarketGroundingRulesTest {
    private static StrictJson.Obj obj(String json) { return StrictJson.parseObject(json.getBytes(StandardCharsets.UTF_8)); }
    private static StrictJson.Obj plan() { return obj("""
        {"facts":[{"text":"시험 기업의 잠정 매출은 약 1원이다.","sourceQuote":"시험 기업의 잠정 매출은 약 1원이다.","evidenceId":"e",
         "subject":"시험 기업","metric":"매출","period":"","qualifiers":["잠정","약"]}]}
        """); }
    private static StrictJson.Obj broad() { return obj("""
        {"documents":[{"sources":[{"evidenceId":"e","quote":"시험 기업의 잠정 매출은 약 1원이다."}]}]}
        """); }
    @Test void exactFactPlanIsBoundToItsOwnSourceAndQualifiers() {
        assertDoesNotThrow(() -> BriefingMarketGroundingRules.validatePlan(plan(), obj("{\"selected\":[]}"), broad()));
        for (String changed : new String[]{"시험 기업의 매출 1원과 영업이익 2원이다.", "시험 기업의 매출은 1원이다."}) {
            ObjectNode value = (ObjectNode) plan().node().deepCopy();
            ((ObjectNode)value.at("/facts/0")).put("text", changed);
            assertThrows(IllegalArgumentException.class, () -> BriefingMarketGroundingRules.validatePlan(StrictJson.Obj.of(value), obj("{\"selected\":[]}"), broad()));
        }
    }
    @Test void analysisCannotRebindFactToAnotherEvidenceOrUnknownFactId() {
        for (String id : new String[]{"fact:1", "fact:0"}) {
            var analysis = StrictJson.newArray(); var claim = StrictJson.newObject().put("kind", "interpretation").put("text", "합성 해석입니다.");
            claim.putArray("basisFactIds").add(id); claim.putArray("evidenceIds").add("other"); claim.putArray("counterFactors"); analysis.add(claim);
            assertThrows(IllegalArgumentException.class, () -> BriefingMarketGroundingRules.project(analysis, plan()));
        }
    }
    @Test void sourceAbsentQuoteIsRejectedEvenWhenItsTextLooksPlausible() {
        ObjectNode value = (ObjectNode) plan().node().deepCopy(); ((ObjectNode)value.at("/facts/0")).put("sourceQuote", "실제 인용에는 없는 확정된 기업 실적이다.");
        assertThrows(IllegalArgumentException.class, () -> BriefingMarketGroundingRules.validatePlan(StrictJson.Obj.of(value), obj("{\"selected\":[]}"), broad()));
    }
    @Test void identicalPriorIdDuplicatesAreAuditedButConflictingValuesAreRejected() {
        var context = obj("{\"previousPublication\":{\"status\":\"available\",\"summary\":{\"forecasts\":[{\"forecastId\":\"f\",\"text\":\"same\"},{\"forecastId\":\"f\",\"text\":\"same\"}]}}}");
        assertEquals(1, BriefingMarketContextRules.priorForecasts(context).size());
        ObjectNode changed = (ObjectNode) context.node().deepCopy(); ((ObjectNode)changed.at("/previousPublication/summary/forecasts/1")).put("text", "conflict");
        assertThrows(IllegalArgumentException.class, () -> BriefingMarketContextRules.priorForecasts(StrictJson.Obj.of(changed)));
    }
    @Test void extractivePlansAcceptOnlyFixedSourceIdsFromOneDocument() {
        var sources = obj("{\"selected\":[{\"sources\":[{\"evidenceId\":\"e\",\"documentId\":\"doc\"},{\"evidenceId\":\"foreign\",\"documentId\":\"other\"}]}]}");
        var plan = obj("{\"facts\":[{\"text\":\"시험 기업의 잠정 매출은 약 1원이다.\",\"sourceIds\":[\"e\"],\"factType\":\"revenue\"}]}");
        var empty = obj("{\"documents\":[]}");
        assertDoesNotThrow(() -> BriefingMarketGroundingRules.validatePlan(plan,sources,empty,true,true));
        var changed = (ObjectNode) plan.node().deepCopy();
        ((tools.jackson.databind.node.ArrayNode)changed.at("/facts/0/sourceIds")).add("foreign");
        final var foreignPlan = changed;
        assertThrows(IllegalArgumentException.class, () -> BriefingMarketGroundingRules.validatePlan(StrictJson.Obj.of(foreignPlan),sources,empty,true,true));
        changed = (ObjectNode) plan.node().deepCopy(); ((ObjectNode)changed.at("/facts/0")).put("sourceQuote", "AI가 만든 인용");
        final var invented = changed;
        assertThrows(StrictJson.Malformed.class, () -> BriefingMarketGroundingRules.validatePlan(StrictJson.Obj.of(invented),sources,empty,true,true));
    }
}
