package com.zoop.briefing.replay;
import static org.assertj.core.api.Assertions.*;
import com.zoop.common.json.StrictJson;
import java.util.List;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.node.ObjectNode;
class BriefingJudgmentUpdateRulesTest {
    private ObjectNode frozen() {
        ObjectNode f = StrictJson.newObject(); f.putObject("sources").putObject("a"); f.withObject("sources").putObject("b");
        var t = f.putArray("targets").addObject().put("companyId", "A").put("role", "selected"); t.putNull("previousJudgment"); t.putArray("sourceIds").add("a");
        t = ((tools.jackson.databind.node.ArrayNode) f.path("targets")).addObject().put("companyId", "B").put("role", "watch"); t.putObject("previousJudgment"); t.putArray("sourceIds").add("b");
        return f;
    }
    private ObjectNode draft() {
        ObjectNode d = StrictJson.newObject();
        for (String key : List.of("conclusion", "industryChange", "limits")) statement(d.putObject(key), "a");
        var list = d.putArray("companies");
        for (String cid : List.of("A", "B")) {
            var c = list.addObject().put("companyId", cid).put("decision", cid.equals("A") ? "initial" : "maintained");
            for (String key : BriefingJudgmentUpdateRules.FIELDS) statement(c.putObject(key), cid.toLowerCase());
        }
        return d;
    }
    private void statement(ObjectNode s, String id) { s.put("text", "합성 계획 확인"); s.putArray("evidenceIds").add(id); }
    @Test void separatesNewCompanyJudgmentFromActualPreviousCompanyWatch() {
        assertThatCode(() -> BriefingJudgmentUpdateRules.validateDraft(StrictJson.Obj.of(draft()), StrictJson.Obj.of(frozen()))).doesNotThrowAnyException();
    }
    @Test void cannotInventAPreviousJudgmentOrUpgradeAWatchCompanyWithoutNewEvidence() {
        for (int index : List.of(0, 1)) {
            ObjectNode d = draft(); ((ObjectNode) d.path("companies").get(index)).put("decision", "strengthened");
            assertThatThrownBy(() -> BriefingJudgmentUpdateRules.validateDraft(StrictJson.Obj.of(d), StrictJson.Obj.of(frozen()))).isInstanceOf(IllegalArgumentException.class);
        }
    }
    @Test void companyEvidenceCannotBeBorrowedFromAnotherCompany() {
        ObjectNode d = draft(); ((ObjectNode) d.at("/companies/0/reason")).putArray("evidenceIds").add("b");
        assertThatThrownBy(() -> BriefingJudgmentUpdateRules.validateDraft(StrictJson.Obj.of(d), StrictJson.Obj.of(frozen()))).hasMessageContaining("statement");
    }
    @Test void responseContractRequiresCompletenessAndEditorialCardsAsWellAsFactSupport() {
        var verification = BriefingCompanySchemas.format("judgment_update_", "verification", StrictJson.Obj.of(frozen()));
        assertThat(verification.at("/schema/required").valueStream().map(n -> n.stringValue()).toList()).containsAll(BriefingJudgmentUpdateRules.QUALITY);
        var generation = BriefingCompanySchemas.format("judgment_update_", "generation", StrictJson.Obj.of(frozen()));
        assertThat(generation.at("/schema/properties/companies/items/properties/description/properties/text/maxLength").intValue()).isEqualTo(64);
    }
}
