package com.zoop.briefing.replay;

import static org.assertj.core.api.Assertions.*;
import com.zoop.common.json.StrictJson;
import java.util.List;
import org.junit.jupiter.api.Test;

class BriefingCompanyOutlookRulesTest {
    @Test void eveningCannotBorrowYesterdaysJudgment() {
        var prior = StrictJson.parseObject("{\"status\":\"PASS\",\"date\":\"2026-10-07\",\"edition\":\"evening\",\"draft\":{\"companies\":[{\"companyId\":\"A\"}]}}");
        var now = StrictJson.parseObject("{\"date\":\"2026-10-08\",\"edition\":\"evening\"}");
        assertThat(BriefingCompanyOutlookRules.previous("A", now, List.of(prior)).path("status").stringValue()).isEqualTo("unavailable");
    }
    @Test void morningUsesOnlySameCompanyAndExactVersion() {
        var prior = StrictJson.parseObject("{\"status\":\"PASS\",\"date\":\"2026-10-07\",\"edition\":\"evening\",\"roundId\":\"r\",\"cutoff\":\"2026-10-07T08:30:00Z\",\"resultVersion\":\"exact\",\"draft\":{\"companies\":[{\"companyId\":\"A\"}]}}");
        var now = StrictJson.parseObject("{\"date\":\"2026-10-08\",\"edition\":\"morning\"}");
        assertThat(BriefingCompanyOutlookRules.previous("A", now, List.of(prior)).path("resultVersion").stringValue()).isEqualTo("exact");
        assertThat(BriefingCompanyOutlookRules.previous("B", now, List.of(prior)).path("status").stringValue()).isEqualTo("unavailable");
    }
    @Test void v3MorningRequiresTheActualPreviousEvening() {
        var prior = StrictJson.parseObject("{\"status\":\"PASS\",\"date\":\"2026-10-22\",\"edition\":\"morning\",\"draft\":{\"companies\":[{\"companyId\":\"A\"}]}}");
        var current = StrictJson.parseObject("{\"date\":\"2026-10-23\",\"edition\":\"morning\",\"frozen\":{\"promptVersion\":\"company-outlook-v3\"}}");
        assertThat(BriefingCompanyOutlookRules.previous("A", current, List.of(prior)).path("status").stringValue()).isEqualTo("unavailable");
    }
    @Test void duplicateOrUnorderedRoundsAreRejected() {
        var layer = StrictJson.parseObject("{\"schemaVersion\":\"zoop-company-outlooks-v1\",\"authorizationRef\":\"user\",\"rounds\":[{\"roundId\":\"a\",\"cutoff\":\"2026-10-08T00:20:00Z\"},{\"roundId\":\"a\",\"cutoff\":\"2026-10-08T00:20:00Z\"}]}");
        assertThatThrownBy(() -> BriefingCompanyOutlookRules.rows(layer)).isInstanceOf(IllegalArgumentException.class);
    }
}
