package com.zoop.portfolio.dto;

import java.time.Instant;
import java.math.BigDecimal;

public record PortfolioValuation(Instant calculatedAt, String currency, BigDecimal totalMarketValue,
        String weightStatus, String weightUnavailableCode, String weightUnavailableReason) {
}
