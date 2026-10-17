package com.zoop.portfolio.dto;

import java.math.BigDecimal;
import com.zoop.portfolio.model.MockHolding;

public record MockHoldingOut(String companyId, String name, BigDecimal quantity,
        BigDecimal avgPrice, String avgPriceCurrency) {
    public static MockHoldingOut from(MockHolding holding) {
        return new MockHoldingOut(holding.companyId(), holding.name(), holding.quantity(),
                holding.avgPrice(), holding.avgPriceCurrency());
    }
}
