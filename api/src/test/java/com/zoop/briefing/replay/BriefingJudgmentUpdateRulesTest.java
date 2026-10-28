package com.zoop.briefing.replay;
import static org.assertj.core.api.Assertions.*;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.Canonical;
import java.nio.file.Path;
import java.util.Map;
import java.util.Set;
import java.util.List;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.node.ObjectNode;
class BriefingJudgmentUpdateRulesTest {
    @Test void passImportRejectsEachOrBothMissingProviderDigestsBeforeTrustingQualityFlags() {
        String body="Authored company plan.",sha=Canonical.sha256(body);
        ObjectNode current=StrictJson.newObject().put("roundId","now").put("status","PASS").put("date","2026-10-23")
            .put("edition","morning").put("cutoff","2026-10-23T00:20:00Z").put("resultVersion","now-version");
        ObjectNode previous=current.deepCopy().put("roundId","before").put("date","2026-10-22")
            .put("edition","evening").put("cutoff","2026-10-22T08:30:00Z").put("resultVersion","before-version");
        for(ObjectNode c:List.of(current,previous)) {
            c.putObject("draft").putArray("companies").addObject().put("companyId","A");
            var f=c.putObject("frozen");
            f.putArray("targets").addObject().put("companyId","A").put("companyName","Company").putArray("sourceIds").add("e");
            f.putObject("sources").putObject("e").put("documentId","doc").put("bodySha256",sha).put("quote",body)
                .put("publishedAt","2026-10-21T08:00:00Z");
        }
        var evidence=Map.of("e",new BriefingPresentationRules.Evidence("e","doc","version",sha,body,body,0,body.length(),"Source",
            "Authored","https://example.test/source","2026-10-21T08:00:00Z","news"));
        var frozen=BriefingJudgmentUpdateRules.freeze(StrictJson.Obj.of(current),StrictJson.Obj.of(previous),evidence);
        for(String missing:List.of("generation","verification","both")) {
            ObjectNode row=StrictJson.newObject().put("roundId","now").put("status","PASS").put("generatedAt","2026-10-23T01:00:00Z");
            row.set("frozen",frozen);var attempt=row.putArray("attempts").addObject();
            attempt.set("draft",draft());var verification=attempt.putObject("verification");
            BriefingJudgmentUpdateRules.QUALITY.forEach(k->verification.put(k,true));
            if(missing.equals("generation"))attempt.put("verificationRequestDigest","b".repeat(64));
            if(missing.equals("verification"))attempt.put("generationRequestDigest","a".repeat(64));
            row.set("draft",draft());row.put("resultVersion","judgment-v1-"+Canonical.digest(row));
            assertThatThrownBy(()->BriefingJudgmentUpdateRules.apply(StrictJson.Obj.of(row),StrictJson.Obj.of(current),
                StrictJson.Obj.of(previous),evidence,Map.of(),Path.of("."),Set.of()))
                .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("pass_call_digests_required");
        }
    }
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
