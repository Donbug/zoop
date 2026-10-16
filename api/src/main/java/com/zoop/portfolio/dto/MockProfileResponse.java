package com.zoop.portfolio.dto;

import java.time.Instant;
import java.util.List;
import com.zoop.common.response.Metadata;
import com.zoop.portfolio.model.MockCash;

public record MockProfileResponse(String id, String label, String accountId, MockCash cash,
        Instant asOf, List<MockHoldingOut> holdings, Metadata metadata) {
}
