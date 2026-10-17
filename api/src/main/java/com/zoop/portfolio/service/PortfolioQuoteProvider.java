package com.zoop.portfolio.service;

import java.math.BigDecimal;
import java.time.Instant;

import com.zoop.portfolio.model.MockHolding;

public interface PortfolioQuoteProvider {
    QuoteResult quote(MockHolding holding);

    record QuoteResult(boolean available, BigDecimal price, String currency, Instant asOf,
            String sourceName, String unavailableCode) {
        public static QuoteResult available(BigDecimal price, String currency, Instant asOf, String sourceName) {
            return new QuoteResult(true, price, currency, asOf, sourceName, null);
        }

        public static QuoteResult unavailable(String code) {
            return new QuoteResult(false, null, null, null, null, code);
        }
    }
}
