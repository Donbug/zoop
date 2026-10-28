package com.zoop.briefing.replay;
import static org.assertj.core.api.Assertions.*;
import com.zoop.common.json.StrictJson;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.node.ObjectNode;
class BriefingEditionReviewRulesTest {
    private ObjectNode frozen() {
        var f=StrictJson.newObject().put("cutoff","2026-10-22T17:30:00+09:00");
        f.putObject("previousReview").put("cutoff","2026-10-22T09:20:00+09:00");
        f.putObject("sources").putObject("a").put("publishedAt","2026-10-21T17:00:00+09:00");
        var t=f.putArray("targets").addObject().put("companyId","A");t.putArray("sourceIds").add("a");
        var previous=t.putObject("previous");var c=previous.putArray("watch").addObject().put("text","실제 납품 확인");c.putArray("evidenceIds").add("a");return f;
    }
    private ObjectNode draft() {
        var d=StrictJson.newObject().put("headline","합성 퇴근 검토");
        for(String k: new String[]{"summary","marketInterpretation","comparison","nextSession"})statement(d.putObject(k));
        var c=d.putArray("companies").addObject().put("companyId","A").put("stance","watch");
        for(String k:new String[]{"title","takeaway","newInformation","judgment","positive","negative"})statement(c.putObject(k));
        var watch=c.putArray("watch").addObject();statement(watch);watch.put("text","실제 납품 확인");var check=c.putArray("checks").addObject().put("condition","실제 납품 확인").put("status","not_observed");statement(check.putObject("observation"));return d;
    }
    private void statement(ObjectNode s) {s.put("text","실제 근거를 확인합니다.");s.putArray("evidenceIds").add("a");}
    @Test void unobservedConditionsRemainUnassessableEvenWithPriceGains() {
        var d=draft();assertThatCode(()->BriefingEditionReviewRules.validateDraft(StrictJson.Obj.of(d),StrictJson.Obj.of(frozen()))).doesNotThrowAnyException();
        ((ObjectNode)d.at("/companies/0/checks/0")).put("status","confirmed");
        assertThatThrownBy(()->BriefingEditionReviewRules.validateDraft(StrictJson.Obj.of(d),StrictJson.Obj.of(frozen()))).hasMessageContaining("condition_new_evidence");
    }
    @Test void previousConditionCannotBeReplacedByAnEasierQuestion() {
        var d=draft();((ObjectNode)d.at("/companies/0/checks/0")).put("condition","주가가 올랐는가");
        assertThatThrownBy(()->BriefingEditionReviewRules.validateDraft(StrictJson.Obj.of(d),StrictJson.Obj.of(frozen()))).hasMessageContaining("previous_condition_coverage");
    }
    @Test void droppingMorningCompanyIsRejected() {
        var d=draft();d.putArray("companies");
        assertThatThrownBy(()->BriefingEditionReviewRules.validateDraft(StrictJson.Obj.of(d),StrictJson.Obj.of(frozen()))).hasMessageContaining("company_coverage");
    }
}
