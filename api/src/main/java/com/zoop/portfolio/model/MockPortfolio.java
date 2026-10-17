package com.zoop.portfolio.model;

import java.time.Instant;
import java.util.List;

public record MockPortfolio(String id, String label, String accountId, MockCash cash,
        Instant asOf, List<MockHolding> holdings) {
    public MockPortfolio {
        holdings = List.copyOf(holdings);
    }
}
