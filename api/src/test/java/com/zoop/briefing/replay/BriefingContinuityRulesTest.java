package com.zoop.briefing.replay;

import com.zoop.common.json.StrictJson;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.node.ObjectNode;
import static org.junit.jupiter.api.Assertions.*;

class BriefingContinuityRulesTest {
    private StrictJson.Obj round() {
        return StrictJson.parseObject("""
            {"roundId":"test-evening","selectionStatus":"HELD_SOURCE_COVERAGE",
             "identity":{"publicationCompanyIds":["TEST:A"],"mode":"publication_clock_simulation"},
             "window":{"from":"2026-10-21T00:20:00Z","to":"2026-10-21T08:30:00Z"},
             "sourceCoverage":{"partialSourceCoverage":false,"unconfirmedTotal":0,"uniqueInputCount":19}}
            """);
    }
    private ObjectNode issue(String id,String decision) {
        ObjectNode i=StrictJson.newObject().put("issueId",id).put("title","[합성] 기업 계획에 관한 기사 추출 제목");
        i.putObject("freshnessReview").put("decision",decision).putArray("deltaEvidenceIds");
        var m=i.putArray("newMentions").addObject().put("publishedAt","2026-10-21T03:00:00Z");
        m.putArray("evidence").addObject().put("evidenceId",id+"-e").put("documentId",id+"-doc").put("quote","합성 시험 원문. ".repeat(20)).putObject("dateContext").put("publishedAt","2026-10-21T03:00:00Z");
        m.putArray("companies").addObject().put("companyId","TEST:A").put("name","합성기업").putArray("evidenceIds").add(id+"-e");
        return i;
    }
    private List<ObjectNode> references(ObjectNode i,int importance) {
        var request=StrictJson.newObject();request.putArray("issues").add(i);
        var a=StrictJson.newObject();a.putObject("assessments").putObject(i.path("issueId").asString())
                .put("importance",importance).put("priority",60).put("status","HOLD").put("scope","COMPANY").put("reason","낮은 중요도의 합성 전망 자료");
        return BriefingContinuityRules.references(round(),StrictJson.Obj.of(request),StrictJson.Obj.of(a),StrictJson.newArray());
    }
    @Test void gradeOneQuotesAreSeparateReferencesAndOriginalHoldIsPreserved() {
        var refs=references(issue("one","DISTINCT_EVENT"),1);assertEquals(1,refs.size());
        assertEquals("HOLD",refs.getFirst().path("originalAssessmentStatus").asString());
        assertEquals(1,refs.getFirst().path("importance").asInt());assertTrue(refs.getFirst().path("label").asString().contains("확정 결과와 구분"));
    }
    @Test void reprintsAndUncertainFreshnessStayExcludedAtLowerImportance() {
        assertTrue(references(issue("one","REPEAT"),1).isEmpty());assertTrue(references(issue("one","UNCERTAIN"),1).isEmpty());
    }
    @Test void noZeroGradeOrThinEvidenceOrUnregisteredEntityPromotion() {
        assertTrue(references(issue("one","DISTINCT_EVENT"),0).isEmpty());
        var thin=issue("one","DISTINCT_EVENT");((ObjectNode)thin.path("newMentions").get(0).path("evidence").get(0)).put("quote","짧은 문장");assertTrue(references(thin,1).isEmpty());
        var unknown=issue("one","DISTINCT_EVENT");((ObjectNode)unknown.path("newMentions").get(0).path("companies").get(0)).put("companyId","UNKNOWN");assertTrue(references(unknown,1).isEmpty());
    }
    @Test void futureAndLowerBoundaryNewsCannotBecomeReferences() {
        for(String time:List.of("2026-10-21T00:20:00Z","2026-10-21T09:00:00Z")) {
            var i=issue("one","DISTINCT_EVENT");((ObjectNode)i.path("newMentions").get(0)).put("publishedAt",time);assertTrue(references(i,1).isEmpty());
        }
    }
    @Test void materialUpdateStillNeedsCurrentDelta() {
        assertTrue(references(issue("one","MATERIAL_UPDATE"),1).isEmpty());
        var i=issue("one","MATERIAL_UPDATE");i.withObject("freshnessReview").withArray("deltaEvidenceIds").add("one-e");assertEquals(1,references(i,1).size());
    }
    @Test void collectionUncertaintyAndUnavailablePreviousRemainExplicit() {
        var info=BriefingContinuityRules.initial(round());assertEquals("limited",info.path("coverage").path("status").asString());
        assertEquals("unavailable",info.path("recap").path("status").asString());assertEquals(0,info.path("recap").path("items").size());
    }
    @Test void recapPreservesPreviousConditionsWithoutClaimingAnUpdatedForecast() {
        var layer=BriefingContinuityRules.initial(round());var payload=StrictJson.newObject().put("date","2026-10-21").put("edition","morning");
        payload.putArray("items").addObject().put("eventId","old").put("title","합성 과거 계획");
        var snapshot=StrictJson.newObject();snapshot.putObject("companyOutlooks").putArray("companies").addObject().put("companyName","합성기업")
                .putObject("reading").putObject("watch").put("text","합성 계획의 이행 여부 확인");
        BriefingContinuityRules.recap(layer,"previous",Instant.parse("2026-10-21T00:20:00Z"),payload,snapshot);
        assertEquals("not_updated",layer.path("forecast").path("status").asString());assertEquals("available",layer.path("recap").path("status").asString());
        assertEquals("previous_condition",layer.path("watchConditions").get(1).path("kind").asString());
        assertThrows(IllegalArgumentException.class,()->BriefingContinuityRules.recap(layer,"future",Instant.parse("2026-10-22T00:20:00Z"),payload,snapshot));
    }
    @Test void gradesAreNotRelaxedForCoreOrValidationFailure() {
        var core=(ObjectNode)round().node().deepCopy();core.put("selectionStatus","SELECTED");
        assertEquals("core",BriefingContinuityRules.build(StrictJson.Obj.of(core),java.util.Map.of(),java.nio.file.Path.of("/unused"),StrictJson.newArray()).path("mode").asString());
        core.put("selectionStatus","HELD_VALIDATION");
        assertEquals("validation_failed",BriefingContinuityRules.build(StrictJson.Obj.of(core),java.util.Map.of(),java.nio.file.Path.of("/unused"),StrictJson.newArray()).path("mode").asString());
        core.put("selectionStatus","HELD_SOURCE_COVERAGE").putNull("groupedSelectionRequestDigest");
        assertEquals("coverage_limited",BriefingContinuityRules.build(StrictJson.Obj.of(core),java.util.Map.of(),java.nio.file.Path.of("/unused"),StrictJson.newArray()).path("mode").asString());
        core.withObject("sourceCoverage").put("partialSourceCoverage",true);
        assertEquals("insufficient",BriefingContinuityRules.initial(StrictJson.Obj.of(core)).path("coverage").path("status").asString());
    }
    @Test void referencesAreBoundedRankedAndNotRepeatedFromPreviousBriefings() {
        var request=StrictJson.newObject();var issues=request.putArray("issues");var answer=StrictJson.newObject();var assessments=answer.putObject("assessments");
        for(int n=0;n<5;n++) {issues.add(issue("i"+n,"DISTINCT_EVENT"));assessments.putObject("i"+n).put("importance",1).put("priority",n*10).put("status","HOLD").put("scope","COMPANY").put("reason","합성 계획");}
        var history=StrictJson.newArray();history.addObject().put("issueId","i4");
        var result=BriefingContinuityRules.references(round(),StrictJson.Obj.of(request),StrictJson.Obj.of(answer),history);
        assertEquals(3,result.size());assertEquals("i3",result.getFirst().path("issueId").asString());
        assertTrue(result.stream().noneMatch(i->"i4".equals(i.path("issueId").asString())));
        // Two event labels from the same original cannot fill two reference slots.
        ((ObjectNode)issues.get(3).path("newMentions").get(0).path("evidence").get(0)).put("documentId","i2-doc");
        var distinct=BriefingContinuityRules.references(round(),StrictJson.Obj.of(request),StrictJson.Obj.of(answer),history);
        assertTrue(distinct.stream().noneMatch(i->"i2".equals(i.path("issueId").asString())));
    }

}
