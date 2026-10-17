package com.zoop.portfolio.repository;

import java.time.Instant;

public record PortfolioIdempotencyRow(String mockPortfolioId, String connectionId, Instant connectedAt) {
}
