package com.zoop.portfolio.repository;

import java.time.Instant;

public record PortfolioConnectionRow(String connectionId, String mockPortfolioId, Instant connectedAt) {
}
