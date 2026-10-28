package com.zoop.briefing.replay;

import com.zoop.common.json.StrictJson;
import java.time.Instant;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import tools.jackson.databind.node.ObjectNode;

class BriefingReview303Test {
    @Test void explicitSeriesAllowsFourteenButPresentationRemainsFour() {
        var layer=StrictJson.newObject().put("schemaVersion",BriefingCompanyOutlookRules.SCHEMA).put("authorizationRef","test:only");
        var rounds=layer.putArray("rounds");
        for(int i=0;i<14;i++)rounds.addObject().put("roundId","round-"+i).put("cutoff",Instant.EPOCH.plusSeconds(i+1).toString());
        assertEquals(14,BriefingCompanyOutlookRules.rows(StrictJson.Obj.of(layer),14).size());
        assertThrows(IllegalArgumentException.class,()->BriefingCompanyOutlookRules.rows(StrictJson.Obj.of(layer)));
        layer.put("schemaVersion",BriefingCompanyReadingRules.SCHEMA);
        for(var row:rounds)((ObjectNode)row).putObject("frozen").put("schemaVersion",BriefingCompanyReadingRules.SCHEMA);
        assertEquals(14,BriefingCompanyReadingRules.rows(StrictJson.Obj.of(layer),14).size());
        assertThrows(IllegalArgumentException.class,()->BriefingCompanyReadingRules.rows(StrictJson.Obj.of(layer)));
        rounds.addObject().put("roundId","round-15").put("cutoff",Instant.EPOCH.plusSeconds(16).toString());
        assertThrows(IllegalArgumentException.class,()->BriefingCompanyReadingRules.rows(StrictJson.Obj.of(layer),14));
    }
    @Test void changingACompanyOrRoleCannotBorrowAnExistingProof() {
        var m=StrictJson.newObject().put("articleId","article").put("articleVersion","v1").put("bodySha256","a".repeat(64));
        m.putObject("grounding").put("verdict","SUPPORTED");
        m.putArray("evidence").addObject().put("evidenceId","one").put("quote","[합성] 기업A 계약 체결").put("start",0).put("end",10);
        m.putArray("companies").addObject().put("companyId","TEST:A").put("name","기업A").put("role","buyer");
        var proof=new BriefingReferenceSupport.Proof(StrictJson.Obj.of(m.deepCopy()),"a".repeat(64));
        assertTrue(BriefingReferenceSupport.matches(StrictJson.Obj.of(m),proof));
        ((ObjectNode)m.path("companies").get(0)).put("role","seller");
        assertFalse(BriefingReferenceSupport.matches(StrictJson.Obj.of(m),proof));
        ((ObjectNode)m.path("companies").get(0)).put("role","buyer").put("companyId","TEST:B");
        assertFalse(BriefingReferenceSupport.matches(StrictJson.Obj.of(m),proof));
    }
}
