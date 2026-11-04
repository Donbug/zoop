package com.zoop.briefing.personal;

import java.util.*;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;
import static org.junit.jupiter.api.Assertions.*;

class PriorityPersonalAssemblerTest {
    final JsonMapper json=JsonMapper.builder().build();
    ObjectNode pool(){return json.createObjectNode().put("priorityContract",PriorityPersonalAssembler.VERSION).put("candidateCount",1);}
    ObjectNode candidate(){
        var c=json.createObjectNode().put("issueId","i").put("title","합성 공급 계약").put("whyImportant","공급 이행을 확인합니다.");
        var companies=c.putArray("companies");for(String id:List.of("A","B")){
            var link=companies.addObject().put("companyId",id).put("name",id).put("reason","계약 당사자입니다.").put("directness","direct");link.putArray("evidenceIds").add("e");
        }
        c.putArray("sources").addObject().put("evidenceId","e").put("quote","합성 계약 발표").put("url","https://example.invalid/a").put("publishedAt","2026-11-04T00:00:00Z");return c;
    }
    @Test void pendingRelativeCardPreservesFrozenCompanyScopeAndHasNoFalseAnalysis(){
        var p=pool();var c=candidate();var before=c.deepCopy();var out=PriorityPersonalAssembler.project(p,"r","2026-11-04T00:20:00Z",Set.of("A"),List.of(c),2,Map.of());
        assertEquals(1,out.at("/items/0/connections").size());assertEquals("A",out.at("/items/0/connections/0/companyId").asString());
        assertTrue(out.at("/items/0/aiAnalyses").isEmpty());assertTrue(out.at("/items/0/analysisOmittedReason").isString());assertEquals(before,c);
    }
    @Test void noSelectedCompanyCannotShowAnotherCompanysAnalysis(){
        var c=candidate();var item=json.createObjectNode().put("issueId","i").put("originRoundId","foreign");var stored=json.createObjectNode();stored.set("priorityPersonal",item);
        assertThrows(IllegalArgumentException.class,()->PriorityPersonalAssembler.project(pool(),"r","2026-11-04T00:20:00Z",Set.of("A"),List.of(c),0,Map.of("i",stored)));
        assertFalse(PriorityPersonalAssembler.enabled(json.createObjectNode()));
    }
}
