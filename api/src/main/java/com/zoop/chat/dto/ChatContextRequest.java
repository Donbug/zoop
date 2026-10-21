package com.zoop.chat.dto;

import java.time.Instant;
import java.util.List;

/** OpenAPI {@code ChatContextRequest}: what the member had selected when asking. Ids are unique and in request order. */
public record ChatContextRequest(List<String> contextIds, List<String> evidenceIds, ChatPeriod period, Instant asOf,
        String graphVersion) {
    public static final ChatContextRequest EMPTY = new ChatContextRequest(List.of(), List.of(), null, null, null);
}
