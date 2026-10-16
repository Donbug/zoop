package com.zoop.portfolio.dto;

import java.math.BigDecimal;
import com.zoop.portfolio.model.MockHolding;

public record HoldingOut(String companyId, String name, String ticker, BigDecimal quantity,
        BigDecimal avgPrice, String avgPriceCurrency, Unavailable quote,
        BigDecimal marketValue, BigDecimal weight) {
    public static HoldingOut from(MockHolding holding) {
        return new HoldingOut(holding.companyId(), holding.name(), holding.ticker(), holding.quantity(),
                holding.avgPrice(), holding.avgPriceCurrency(),
                new Unavailable("unavailable", "quote_source_not_configured"), null, null);
    }

    public record Unavailable(String status, String reason) { }
}
