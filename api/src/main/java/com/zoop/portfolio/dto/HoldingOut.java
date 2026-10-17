package com.zoop.portfolio.dto;

import java.math.BigDecimal;

public record HoldingOut(String companyId, String name, String ticker, BigDecimal quantity,
        BigDecimal avgPrice, String avgPriceCurrency, QuoteState quote,
        BigDecimal marketValue, BigDecimal weight) {
    public sealed interface QuoteState permits Available, Unavailable {
        String status();
    }
    public record Available(String status, BigDecimal price, String currency,
            java.time.Instant asOf, String sourceName) implements QuoteState { }
    public record Unavailable(String status, String reason) implements QuoteState { }
}
