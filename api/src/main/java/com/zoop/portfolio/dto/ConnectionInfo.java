package com.zoop.portfolio.dto;

import java.time.Instant;
import com.zoop.portfolio.model.MockCash;

public record ConnectionInfo(String id, String mockPortfolioId, String label, Instant connectedAt,
        String accountId, MockCash cash, String status) {
}
