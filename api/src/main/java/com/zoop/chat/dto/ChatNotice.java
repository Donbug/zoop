package com.zoop.chat.dto;

import java.util.List;

/**
 * OpenAPI {@code ChatNotice}: a fault or detour beside a result that did not leave a requirement unanswered (MCP actions
 * contract 3.5). {@code labels} name the requirements it concerns in the member's words; empty when it concerns the whole run.
 */
public record ChatNotice(String code, List<String> labels, String message) {
    public ChatNotice {
        labels = List.copyOf(labels);
    }
}
