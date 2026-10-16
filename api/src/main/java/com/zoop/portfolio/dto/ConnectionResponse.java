package com.zoop.portfolio.dto;

import java.time.Instant;
import com.zoop.common.response.Metadata;
import com.zoop.portfolio.model.MockCash;

public record ConnectionResponse(String id, String mockPortfolioId, String label, Instant connectedAt,
        String accountId, MockCash cash, String status, int holdingsCount, Metadata metadata) {
}
