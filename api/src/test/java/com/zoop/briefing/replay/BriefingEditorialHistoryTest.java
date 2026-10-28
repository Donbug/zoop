package com.zoop.briefing.replay;

import com.zoop.common.json.StrictJson;
import java.util.Map;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.node.ObjectNode;
import static org.assertj.core.api.Assertions.*;

class BriefingEditorialHistoryTest {
    private StrictJson.Obj input() {
        return StrictJson.parseObject("""
          {"window":{"from":"2026-10-22T00:20:00Z","to":"2026-10-22T08:30:00Z"},"reports":[],
           "issues":[{"issueId":"i","priorReportIds":[],"newEvidence":[{"evidenceId":"e","quote":"고정 원문"}]}]}
          """);
    }
    @Test void historicalAccountingCannotChangeCurrentEvidenceOrOmitAnIssue() {
        assertThatCode(() -> BriefingEditorialRules.historicalInput(input(),input(),Map.of())).doesNotThrowAnyException();
        ObjectNode changed=(ObjectNode)input().node().deepCopy(); ((ObjectNode)changed.at("/issues/0/newEvidence/0")).put("quote","변경 원문");
        var changedQuote=changed;
        assertThatThrownBy(() -> BriefingEditorialRules.historicalInput(StrictJson.Obj.of(changedQuote),input(),Map.of())).isInstanceOf(IllegalArgumentException.class);
        changed=(ObjectNode)input().node().deepCopy();changed.putArray("issues");var missing=changed;
        assertThatThrownBy(() -> BriefingEditorialRules.historicalInput(StrictJson.Obj.of(missing),input(),Map.of())).isInstanceOf(IllegalArgumentException.class);
    }
    @Test void historicalReportMustStillBelongToReviewedHistoryAndPrecedeWindow() {
        ObjectNode old=(ObjectNode)input().node().deepCopy(); var report=StrictJson.newObject().put("reportId","r").put("availableBefore","2026-10-23T00:00:00Z");
        old.withArray("reports").add(report);
        assertThatThrownBy(() -> BriefingEditorialRules.historicalInput(StrictJson.Obj.of(old),input(),Map.of())).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> BriefingEditorialRules.historicalInput(StrictJson.Obj.of(old),input(),Map.of("r",StrictJson.Obj.of(report)))).isInstanceOf(IllegalArgumentException.class);
    }
}
