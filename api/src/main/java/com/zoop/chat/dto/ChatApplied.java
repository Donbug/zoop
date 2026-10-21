package com.zoop.chat.dto;

import java.time.Instant;
import java.util.List;

/** OpenAPI {@code ChatApplied}: what the answer was actually built on. */
public record ChatApplied(List<ChatAppliedItem> companies, List<ChatAppliedItem> issues, ChatAppliedPeriod period,
        String graphVersion, Instant dataAsOf, boolean questionOverrodeContext) {
}
