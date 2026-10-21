package com.zoop.chat.dto;

import java.time.Instant;
import java.util.List;

/** OpenAPI {@code ChatFrozenContext}: the selection fixed at the first acceptance of a question. */
public record ChatFrozenContext(List<ChatContextItem> items, int evidenceCount, ChatPeriod period, Instant asOf,
        String graphVersion) {
}
