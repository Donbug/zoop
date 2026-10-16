package com.zoop.portfolio.model;

import java.math.BigDecimal;

public record MockHolding(String companyId, String name, String ticker, BigDecimal quantity,
        BigDecimal avgPrice, String avgPriceCurrency) {
}
