package com.zoop.briefing.personal;

import java.util.*;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

/** Projects a member's frozen company scope from shared public business analysis. No provider calls. */
final class PriorityPersonalAssembler {
    static final String VERSION = "priority-business-producer-v1";
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private PriorityPersonalAssembler() { }
    static boolean enabled(JsonNode pool) { return VERSION.equals(pool.path("priorityContract").asString()); }
    static ObjectNode project(JsonNode pool, String round, String cutoff, Set<String> scope,
            List<JsonNode> selected, int minimum, Map<String,JsonNode> views) {
        var out=JSON.createObjectNode().put("schemaVersion","personal-relative-priority-view-v1")
            .put("roundId",round).put("cutoff",cutoff).put("candidateCount",pool.path("candidateCount").asInt())
            .put("minimumIssues",minimum).put("status",selected.isEmpty()?"collection_insufficient":"available");
        var companies=out.putArray("companyIds");scope.stream().sorted().forEach(companies::add);
        var items=out.putArray("items");
        for(var candidate:selected){
            String id=candidate.path("issueId").asString();var stored=views.get(id);
            ObjectNode item;
            if(stored!=null && stored.path("priorityPersonal").isObject()){
                item=(ObjectNode)stored.path("priorityPersonal").deepCopy();
                if(!id.equals(item.path("issueId").asString()) || !round.equals(item.path("originRoundId").asString()))
                    throw new IllegalArgumentException("Mismatched priority analysis");
                var connections=item.putArray("connections");
                for(var c:stored.path("priorityPersonal").path("connections"))if(scope.contains(c.path("companyId").asString()))connections.add(c.deepCopy());
                var analyses=item.putArray("aiAnalyses");
                for(var a:stored.path("priorityPersonal").path("aiAnalyses"))if(scope.contains(a.path("companyId").asString()))analyses.add(a.deepCopy());
            }else{
                item=JSON.createObjectNode().put("issueId",id).put("kind","new_issue").put("title",candidate.path("title").asString())
                    .put("reason",candidate.path("whyImportant").asString()).put("originRoundId",round).put("originCutoff",cutoff)
                    .put("analysisOmittedReason","기업별 사업 영향 분석을 생성·검증 중입니다.").putNull("price");
                item.putArray("priorAnalysis");item.putArray("aiAnalyses");var connections=item.putArray("connections");
                for(var c:PersonalBriefingService.matched(candidate,scope))connections.addObject().put("companyId",c.path("companyId").asString()).put("name",c.path("name").asString()).put("reason",c.path("reason").asString());
                var sources=item.putArray("sources");for(var s:candidate.path("sources")){
                    var source=sources.addObject();for(String k:List.of("evidenceId","quote","url","publishedAt","publishedDate","availableAt","eligibilityBasis"))if(s.has(k))source.set(k,s.path(k).deepCopy());
                }
            }
            items.add(item);
        }
        out.put("resultVersion",VERSION+"-"+com.zoop.common.json.Canonical.sha256(com.zoop.common.json.Canonical.bytes(out)));
        Set<String> evidence=new HashSet<>();
        for(var c:selected)for(var source:c.path("sources"))evidence.add(source.path("evidenceId").asString());
        com.zoop.briefing.query.BriefingPriorityRules.validate(out,round,java.time.Instant.parse(cutoff),true,scope,evidence);
        return out;
    }
}
