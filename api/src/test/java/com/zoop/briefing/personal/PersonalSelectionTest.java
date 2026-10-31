package com.zoop.briefing.personal;
import com.zoop.briefing.storage.BriefingRound;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;
import java.time.Instant;
import java.time.LocalDate;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class PersonalSelectionTest {
    final JsonMapper j=JsonMapper.builder().build();
    ObjectNode candidate(String id,String event,int importance,String company,String quote) {
        var c=j.createObjectNode().put("issueId",id).put("eventKey",event).put("importance",importance)
            .put("informationChange","new_event").put("verified",true);
        c.putArray("companies").addObject().put("companyId",company).put("directness","direct").put("reason","[합성] 직접 계약 당사자")
            .putArray("evidenceIds").add("e");
        c.putArray("sources").addObject().put("documentId","d").put("bodySha256","a".repeat(64)).put("quote",quote)
            .put("publishedAt","2026-10-22T00:00:00Z").put("quoteVerified",true);
        return c;
    }
    @Test void usesWholePoolAndAllowsThreeIndependentEventsOfSameCompany() {
        var unrelated=candidate("common","common",3,"other","unrelated");
        var a=candidate("a","contract",3,"mine","contract"); var b=candidate("b","factory",2,"mine","factory");var c=candidate("c","capital",2,"mine","capital");
        var related=List.<JsonNode>of(unrelated,a,b,c).stream().filter(x->!PersonalBriefingService.matched(x,Set.of("mine")).isEmpty()).toList();
        assertEquals(List.of(a,b,c),PersonalBriefingService.select(related,Set.of("mine")));
    }
    @Test void duplicatesDoNotFillThreeOrRaiseRankAndMissingPriceIsNotZero() {
        var a=candidate("a","contract",3,"mine","contract");
        var duplicate=candidate("b","contract",3,"mine","another language");
        var exact=candidate("c","different-extraction",3,"mine","contract");
        assertEquals(List.of(a),PersonalBriefingService.select(List.of(a,duplicate,exact),Set.of("mine")));
        assertFalse(a.has("price"));
    }
    @Test void rejectsUnconfirmedConnection() {
        var a=candidate("a","a",3,"mine","fact");
        ((ObjectNode)a.path("companies").get(0)).put("directness","unconfirmed");
        assertTrue(PersonalBriefingService.matched(a,Set.of("mine")).isEmpty());
    }
    @Test void keepsImportanceVerificationAndCutoffGates() {
        var good=candidate("a","a",2,"mine","fact");var weak=candidate("b","b",1,"mine","weak");
        var repeated=candidate("c","c",3,"mine","repeat").put("informationChange","repeat");
        var bad=candidate("d","d",3,"mine","bad").put("verified",false);
        var future=candidate("e","e",3,"mine","future");((ObjectNode)future.path("sources").get(0)).put("publishedAt","2026-10-22T01:00:01Z");
        var round=new BriefingRound("r",LocalDate.of(2026,10,22),"morning",Instant.parse("2026-10-22T01:00:00Z"),Instant.parse("2026-10-21T08:30:00Z"),Instant.parse("2026-10-22T01:00:00Z"),false,"published",Instant.now(),Instant.now(),null,null,null,null);
        var pool=j.createObjectNode();pool.set("candidates",j.valueToTree(List.of(good,weak,repeated,bad,future)));
        assertEquals(List.of(good),PersonalBriefingService.eligible(pool,round));
    }
}
