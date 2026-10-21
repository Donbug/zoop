package com.zoop.telemetry.dto;

import com.fasterxml.jackson.annotation.JsonAnySetter;
import jakarta.validation.constraints.AssertTrue;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

public record TelemetryEventRequest(
        @NotBlank @Pattern(regexp = "screen_view|graph_node_select|graph_edge_select|briefing_view|briefing_issue_open|ai_question")
        String type,
        @Pattern(regexp = "main|briefing|ai") String screen,
        @Pattern(regexp = "[A-Za-z0-9._:/-]+") String targetId,
        @Size(max = 256) @Pattern(regexp = "[A-Za-z0-9._:/-]+") String roundId,
        @NotBlank @Pattern(regexp = "[A-Za-z0-9-]{8,40}") String viewId) {

    @JsonAnySetter
    public void rejectUnknownField(String name, Object value) {
        throw new IllegalArgumentException("Unknown telemetry event field");
    }

    @AssertTrue(message = "event fields do not match the event type")
    public boolean isShapeValid() {
        if (type == null) return true;
        return switch (type) {
            case "screen_view" -> screen != null && targetId == null && roundId == null;
            case "graph_node_select", "graph_edge_select", "briefing_view" ->
                    screen == null && targetId != null && roundId == null;
            case "briefing_issue_open" -> screen == null && targetId != null && roundId != null;
            case "ai_question" -> screen == null && roundId == null;
            default -> false;
        };
    }
}
