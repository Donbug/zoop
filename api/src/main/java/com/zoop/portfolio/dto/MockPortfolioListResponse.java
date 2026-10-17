package com.zoop.portfolio.dto;

import java.util.List;
import com.zoop.common.response.Metadata;

public record MockPortfolioListResponse(List<MockPortfolioOption> items, Metadata metadata, String nextCursor) {
}
