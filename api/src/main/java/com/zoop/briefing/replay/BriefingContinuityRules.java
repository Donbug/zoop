package com.zoop.briefing.replay;

import com.zoop.common.json.StrictJson;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/** Additive quiet-round policy. Importance may fall from 2 to 1; evidence and freshness never do. */
final class BriefingContinuityRules {
    static final String VERSION = "importance-continuity-v2";
    private BriefingContinuityRules() { }

    static ObjectNode build(StrictJson.Obj round, Map<String, JsonNode> receipts, Path output, ArrayNode history, Map<String,BriefingReferenceSupport.Proof> support) {
        ObjectNode out = initial(round);
        String state=round.string("selectionStatus");
        if ("SELECTED".equals(state)) return out.put("mode","core").put("importanceFloor",2)
                .put("message","확인된 새 핵심 이슈를 제공합니다. 참고 소식으로 개수를 채우지 않습니다.");
        if ("HELD_VALIDATION".equals(state) || round.has("groupedUnresolvedPaidRequest"))
            return out.put("mode","validation_failed").put("message","생성·근거 검증이 끝나지 않아 새 소식을 제공하지 않습니다. 중요도 완화로 검증 실패를 우회하지 않습니다.");
        String digest=round.stringOrNull("groupedSelectionRequestDigest");
        if(digest==null || !receipts.containsKey(digest)) return out.put("mode","coverage_limited")
                .put("message","선정 판단을 완료할 수집·검증 기록이 부족합니다. 새 소식이 없었다고 단정하지 않습니다.");
        var record=BriefingGroupedSimulationRules.recording(StrictJson.Obj.of(receipts.get(digest)),output,true);
        var request=record.input(); var answer=record.answer();
        Set<String> ids=new HashSet<>(); request.objects("issues").forEach(i->ids.add(i.string("issueId")));
        answer.object("assessments").exactly(ids);
        if(!answer.objects("selected").isEmpty()) return out.put("mode","validation_failed")
                .put("message","완료되지 않은 선정 결과를 중요도 완화로 대신하지 않습니다.");
        List<ObjectNode> choices=references(round,request,answer,history,support);
        ArrayNode refs=out.withArray("references"); choices.forEach(refs::add);
        if (!choices.isEmpty()) return out.put("mode","reference").put("importanceFloor",1)
                .put("message","확인한 자료에서 핵심 기준을 충족한 새 이슈는 선정되지 않았습니다. 중요도 1의 기업 참고 소식을 별도로 전합니다.");
        if ("insufficient".equals(out.path("coverage").path("status").asString())) return out.put("mode","coverage_limited").put("message","수집·시각 확인이 부족해 새 소식의 유무를 판단하지 않습니다.");
        return out.put("mode","recap").put("message","확인한 자료 범위에서 검증을 통과한 새 핵심·참고 소식이 선정되지 않았습니다. 이전 이슈와 확인할 조건을 복기합니다.");
    }

    static ObjectNode initial(StrictJson.Obj round) {
        var out=StrictJson.newObject().put("schemaVersion",VERSION).put("roundId",round.string("roundId"))
                .put("cutoff",round.object("window").string("to")).putNull("importanceFloor");
        out.putArray("references"); out.putArray("watchConditions");
        out.putObject("recap").put("status","unavailable").putNull("previousRoundId").putNull("dataAsOf")
                .put("message","마감 이전의 검증된 이전 발행본이 없어 과거 이슈나 전망을 임의로 채우지 않습니다.").putArray("items");
        var c=round.object("sourceCoverage");
        boolean insufficient=c.bool("partialSourceCoverage") || c.count("unconfirmedTotal")>0 || c.count("uniqueInputCount")==0;
        boolean retrospective=round.object("identity").has("mode") && "publication_clock_simulation".equals(round.object("identity").string("mode"));
        out.putObject("coverage").put("status",insufficient?"insufficient":retrospective?"limited":"registered_scope")
                .put("confirmedDocuments",c.count("uniqueInputCount"))
                .put("message",insufficient?"수집·발행시각 확인이 부족합니다. 새 소식 부재와 구분합니다.":
                    "확인한 "+c.count("uniqueInputCount")+"건의 자료 범위입니다. 시장 전체의 새 소식 부재를 뜻하지 않습니다."
                    +(retrospective?" 당시 수집본이 없는 과거 시뮬레이션입니다.":""));
        out.putObject("forecast").put("status","unavailable")
                .put("message","새 근거로 기업 전망을 갱신한 결과가 없습니다. 기존 판단을 현재의 확정 전망으로 바꾸지 않습니다.");
        out.withArray("watchConditions").addObject().put("text","관련 기업의 공식 발표와 계획·추정의 확정 또는 변경 여부를 확인하세요.")
                .put("kind","verification_check");
        return out;
    }

    static List<ObjectNode> references(StrictJson.Obj round, StrictJson.Obj request, StrictJson.Obj answer, ArrayNode history, Map<String,BriefingReferenceSupport.Proof> support) {
        Set<String> registered=Set.copyOf(round.object("identity").strings("publicationCompanyIds"));
        Set<String> old=new HashSet<>(); history.forEach(v->old.add(v.path("issueId").asString()));
        Instant from=Instant.parse(round.object("window").string("from")), cutoff=Instant.parse(round.object("window").string("to"));
        List<ObjectNode> eligible=new ArrayList<>();
        for(var issue:request.objects("issues")) {
            var assessment=answer.object("assessments").object(issue.string("issueId"));
            // Grade-1 plans/forecasts were HOLD under the old grade-2 floor. No fact is upgraded:
            // only exact quotations are displayed, with the original HOLD/reason retained.
            if(assessment.count("importance")!=1 || !Set.of("SELECTABLE","HOLD").contains(assessment.string("status"))
                    || "INSUFFICIENT".equals(assessment.string("scope")) || !issue.has("freshnessReview"))continue;
            var freshness=issue.object("freshnessReview"); String decision=freshness.string("decision");
            if(!Set.of("DISTINCT_EVENT","MATERIAL_UPDATE").contains(decision))continue;
            if(old.contains(issue.string("issueId")) && !"MATERIAL_UPDATE".equals(decision))continue;
            Map<String,StrictJson.Obj> sources=new LinkedHashMap<>(); Map<String,String> companies=new LinkedHashMap<>();
            boolean valid=true;
            for(var mention:issue.objects("newMentions")) {
                if(!BriefingReferenceSupport.matches(mention,support.get(mention.string("mentionId")))){valid=false;break;}
                Instant published=Instant.parse(mention.string("publishedAt"));
                if(!published.isAfter(from)||published.isAfter(cutoff)){valid=false;break;}
                for(var e:mention.objects("evidence"))sources.putIfAbsent(e.string("evidenceId"),e);
                for(var co:mention.objects("companies")) {
                    if(!registered.contains(co.string("companyId")) || co.strings("evidenceIds").stream().noneMatch(sources::containsKey)){valid=false;break;}
                    companies.put(co.string("companyId"),co.string("name"));
                }
            }
            if(!valid||companies.isEmpty()||sources.isEmpty())continue;
            if("MATERIAL_UPDATE".equals(decision) && (freshness.strings("deltaEvidenceIds").isEmpty()
                    || freshness.strings("deltaEvidenceIds").stream().noneMatch(sources::containsKey)))continue;
            var value=StrictJson.newObject().put("issueId",issue.string("issueId"))
                    .put("title",String.join("·",companies.values())+" 참고 소식")
                    .put("importance",1).put("priority",assessment.count("priority"))
                    .put("originalAssessmentStatus",assessment.string("status")).put("assessmentReason",assessment.string("reason"))
                    .put("freshness",decision).put("label","계획·전망을 포함한 참고 자료 · 확정 결과와 구분");
            var cos=value.putArray("companies");companies.forEach((id,name)->cos.addObject().put("id",id).put("name",name));
            value.put("supportPolicy","recorded-supported-event-exact-quote-v1");
            var proofs=value.putArray("supportRequestDigests");issue.objects("newMentions").stream().map(m->support.get(m.string("mentionId")).requestDigest()).distinct().forEach(proofs::add);
            var es=value.putArray("sources");sources.values().forEach(e->{
                ObjectNode copy=StrictJson.newObject();
                for(String key:List.of("evidenceId","documentId","documentVersion","bodySha256","quote","start","end","offsetUnit","url"))
                    if(e.has(key))copy.set(key,e.raw(key).deepCopy());
                copy.putObject("dateContext").put("publishedAt",e.object("dateContext").string("publishedAt"));
                es.add(copy);
            });eligible.add(value);
        }
        eligible.sort(Comparator.<ObjectNode>comparingInt(v->v.path("priority").asInt()).reversed().thenComparing(v->v.path("issueId").asString()));
        Set<String> documents=new HashSet<>();List<ObjectNode> selected=new ArrayList<>();
        for(var value:eligible) {
            Set<String> own=new HashSet<>();value.path("sources").forEach(e->own.add(e.path("documentId").asString()));
            if(own.stream().anyMatch(documents::contains))continue;
            documents.addAll(own);selected.add(value);if(selected.size()==3)break;
        }
        return selected;
    }

    static void recap(ObjectNode layer, String previousId, Instant asOf, ObjectNode payload, ObjectNode snapshot) {
        // The importer passes only a previously validated, earlier publication. Current authority is rechecked on read.
        if(!asOf.isBefore(Instant.parse(layer.path("cutoff").asString())))throw new IllegalArgumentException("continuity_future_recap");
        ObjectNode recap=layer.withObject("recap");recap.put("status","available").put("previousRoundId",previousId)
                .put("dataAsOf",asOf.toString()).put("date",payload.path("date").asString()).put("edition",payload.path("edition").asString()).put("message","이전 발행본 복기입니다. 새 사실·새 전망이나 현재도 유효하다는 재평가가 아닙니다.");
        recap.set("items",payload.path("items").deepCopy());
        ArrayNode conditions=layer.withArray("watchConditions");
        for(JsonNode co:snapshot.path("companyOutlooks").path("companies")) {
            JsonNode text=co.path("reading").path("watch").path("text");
            if(text.isString()&&!text.asString().isBlank())conditions.addObject().put("text",text.asString()).put("kind","previous_condition")
                    .put("companyName",co.path("companyName").asString()).put("previousRoundId",previousId);
        }
        layer.withObject("forecast").put("status","not_updated").put("message","새로운 기업 전망은 생성하지 않았습니다. 이전 판단과 당시 확인 조건을 복기합니다.");
    }
}
