package com.zoop.briefing.replay;

import com.zoop.common.json.StrictJson;
import java.util.Map;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.node.ObjectNode;
import static org.junit.jupiter.api.Assertions.*;

class BriefingCoreEvidenceRulesTest {
    ObjectNode candidate(String quote) {
        var c = StrictJson.newObject().put("issueId", "authored-issue").put("evidencePolicy", BriefingCoreEvidenceRules.POLICY);
        c.putObject("semanticSupport").put("authored-mention", "a".repeat(64));
        var m = c.putArray("newMentions").addObject().put("mentionId", "authored-mention").put("articleId", "authored-doc")
                .put("articleVersion", "v1").put("bodySha256", "b".repeat(64));
        m.putArray("evidence").addObject().put("evidenceId", "authored-evidence").put("quote", quote).put("start", 0).put("end", quote.length());
        m.putArray("companies");
        return c;
    }
    Map<String, BriefingReferenceSupport.Proof> support(ObjectNode c) {
        var m = (ObjectNode)c.path("newMentions").get(0).deepCopy(); m.putObject("grounding").put("verdict", "SUPPORTED");
        return Map.of("authored-mention", new BriefingReferenceSupport.Proof(StrictJson.Obj.of(m), "a".repeat(64)));
    }
    @Test void shortSupportedQuoteQualifiesAndFrozenReceiptIsBound() {
        var c = candidate("[합성] 계약 체결"); var proofs = support(c);
        assertTrue(BriefingCoreEvidenceRules.eligible(StrictJson.Obj.of(c), proofs));
        assertDoesNotThrow(() -> BriefingCoreEvidenceRules.frozen(StrictJson.Obj.of(c), proofs));
    }
    @Test void longQuoteCannotReplaceMissingSemanticVerification() {
        var c = candidate("[합성] 원문 ".repeat(100));
        assertFalse(BriefingCoreEvidenceRules.eligible(StrictJson.Obj.of(c), Map.of()));
        assertThrows(IllegalArgumentException.class, () -> BriefingCoreEvidenceRules.frozen(StrictJson.Obj.of(c), Map.of()));
    }
    @Test void sourceAndSpanMutationCannotReuseCompletedSupport() {
        var c = candidate("[합성] 계획"); var proofs = support(c);
        ((ObjectNode)c.path("newMentions").get(0).path("evidence").get(0)).put("quote", "[합성] 확정");
        assertFalse(BriefingCoreEvidenceRules.eligible(StrictJson.Obj.of(c), proofs));
        var changed = candidate("[합성] 계획"); ((ObjectNode)changed.path("newMentions").get(0)).put("bodySha256", "c".repeat(64));
        assertFalse(BriefingCoreEvidenceRules.eligible(StrictJson.Obj.of(changed), proofs));
    }
    @Test void forgedReceiptPointerOrUnknownPolicyIsRejected() {
        var c = candidate("[합성] 계약"); var proofs = support(c);
        ((ObjectNode)c.path("semanticSupport")).put("authored-mention", "c".repeat(64));
        assertThrows(IllegalArgumentException.class, () -> BriefingCoreEvidenceRules.frozen(StrictJson.Obj.of(c), proofs));
        c.put("evidencePolicy", "unknown");
        assertThrows(IllegalArgumentException.class, () -> BriefingCoreEvidenceRules.frozen(StrictJson.Obj.of(c), proofs));
    }
}
