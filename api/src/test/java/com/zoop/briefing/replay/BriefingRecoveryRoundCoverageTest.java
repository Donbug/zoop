package com.zoop.briefing.replay;

import com.zoop.common.json.StrictJson;
import java.util.Set;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

class BriefingRecoveryRoundCoverageTest {
    private StrictJson.Obj series(boolean explicit) {
        var value=StrictJson.newObject(); var rounds=value.putArray("rounds");
        for (int i=0;i<4;i++) rounds.addObject().put("roundId","r"+i);
        if (explicit) { var declared=value.putObject("roundSeries").putArray("rounds"); for (int i=0;i<4;i++) declared.addObject(); }
        return StrictJson.Obj.of(value);
    }
    @Test void explicitSeriesRecoveryKeepsEveryOriginalRoundExactlyOnce() {
        assertThatCode(() -> BriefingGroupedRecoveryRules.roundCoverage(series(true),Set.of("r0","r1","r2","r3"))).doesNotThrowAnyException();
        for (Set<String> ids: Set.of(Set.of("r0","r1","r2"),Set.of("r0","r1","r2","foreign")))
            assertThatThrownBy(() -> BriefingGroupedRecoveryRules.roundCoverage(series(true),ids)).isInstanceOf(IllegalArgumentException.class);
    }
    @Test void fourRoundsWithoutAnExplicitSeriesCannotReplaceTheLegacyFourteen() {
        assertThatThrownBy(() -> BriefingGroupedRecoveryRules.roundCoverage(series(false),Set.of("r0","r1","r2","r3")))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
