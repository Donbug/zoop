package com.zoop.telemetry.dto;

import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;

class TelemetryEventRequestTest {
    private final JsonMapper mapper = JsonMapper.builder().build();

    @Test
    void knownEventFieldsDeserializeIntoRequestDto() {
        assertDoesNotThrow(() -> mapper.readValue("""
                {"type":"briefing_issue_open","targetId":"issue-123","roundId":"round-2026-10-21",
                  "viewId":"view-unknown-01"}
                """, TelemetryEventRequest.class));
    }

    @Test
    void unknownFieldsAreRejectedInsteadOfSilentlyDroppingUserText() {
        assertThrows(Exception.class, () -> mapper.readValue("""
                {"type":"ai_question","targetId":null,"viewId":"view-unknown-01",
                  "questionText":"private user input"}
                """, TelemetryEventRequest.class));
    }
}
