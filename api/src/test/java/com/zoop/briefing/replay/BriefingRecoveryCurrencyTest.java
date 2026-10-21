package com.zoop.briefing.replay;

import java.util.List;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class BriefingRecoveryCurrencyTest {
    @Test void explicitWonScaleMustMatchTheCitedAmount() {
        assertDoesNotThrow(() -> BriefingGroupedRecoveryRules.validateKrwAmounts("투자액은 4조원입니다.", List.of("It plans to invest 4 trillion won.")));
        assertThrows(IllegalArgumentException.class, () -> BriefingGroupedRecoveryRules.validateKrwAmounts("투자액은 4조원입니다.", List.of("It plans to invest 40 trillion won.")));
        assertDoesNotThrow(() -> BriefingGroupedRecoveryRules.validateKrwAmounts("투자액은 4조2462억원입니다.", List.of("The investment is 4.2462 trillion won.")));
        assertDoesNotThrow(() -> BriefingGroupedRecoveryRules.validateKrwAmounts("투자액은 42,462억원입니다.", List.of("The investment is 4.2462 trillion Korean won.")));
        assertDoesNotThrow(() -> BriefingGroupedRecoveryRules.validateKrwAmounts("투자액은 42억6200만원입니다.", List.of("The investment is 4.262 billion won.")));
    }
    @Test void UnknownCurrenciesRangesAndUnsupportedUnitChainsDoNotClaimAConversion() {
        assertDoesNotThrow(() -> BriefingGroupedRecoveryRules.validateKrwAmounts("투자액은 4조원입니다.", List.of("The investment is $40 trillion.")));
        assertDoesNotThrow(() -> BriefingGroupedRecoveryRules.validateKrwAmounts("투자액은 35조원입니다.", List.of("The investment is 30~40조원.")));
        assertDoesNotThrow(() -> BriefingGroupedRecoveryRules.validateKrwAmounts("투자액은 4억원입니다.", List.of("투자액은 4천억원입니다.")));
        assertDoesNotThrow(() -> BriefingGroupedRecoveryRules.validateKrwAmounts("지분은 40%입니다.", List.of("지분은 40%입니다.")));
    }
}
