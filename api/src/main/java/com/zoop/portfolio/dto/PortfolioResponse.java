package com.zoop.portfolio.dto;

import java.time.Instant;
import java.util.List;
import com.zoop.common.response.Metadata;

public record PortfolioResponse(boolean connected, ConnectionInfo connection, List<HoldingOut> holdings,
        Instant mockAsOf, PortfolioValuation valuation, Metadata metadata) {
}
