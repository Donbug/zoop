package com.zoop.chat.dto;

import java.util.List;

import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

import static org.junit.jupiter.api.Assertions.*;

/** D-AI-02: a stored result written before answerStatus and notices existed still reads back whole. */
class ChatResultTest {
    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    void aResultStoredBeforeTheStatusReadsBackWithTheStatusItsOutcomeAndLimitationsGive() {
        ChatResult complete = mapper.readValue(stored("answered", "[]"), ChatResult.class);
        assertEquals("complete", complete.answerStatus());
        assertEquals(List.of(), complete.notices());

        ChatResult partial = mapper.readValue(stored("answered",
                "[{\"kind\":\"evidence_insufficient\",\"label\":\"요구\",\"message\":\"부족\"}]"), ChatResult.class);
        assertEquals("partial", partial.answerStatus());

        for (String outcome : List.of("clarification", "guidance", "insufficient_evidence")) {
            assertEquals("guidance", mapper.readValue(stored(outcome, "[]"), ChatResult.class).answerStatus(), outcome);
        }
    }

    @Test
    void theStatusAndNoticesTheServerDecidedAreKeptAsWritten() {
        var notice = new ChatNotice("mcp_direct_start", List.of(), "안내");
        var written = new ChatResult("answered", "msg-1", "본문", List.of(), "none", null, List.of(), List.of(), List.of(),
                null, List.of(), null, List.of(new ChatLimitation("not_in_member_scope", "요구", "기준점")), null,
                "complete", List.of(notice));
        ChatResult read = mapper.readValue(mapper.writeValueAsString(written), ChatResult.class);
        assertEquals("complete", read.answerStatus(), "a reference-point note leaves the answer complete");
        assertEquals(List.of(notice), read.notices());
    }

    private static String stored(String outcome, String limitations) {
        return """
                {"outcome":"%s","messageId":"msg-1","answer":"","sections":[],"answerBasis":"none","reason":null,
                 "sources":[],"citations":[],"graphTargets":[],"applied":null,"choices":[],"action":null,
                 "limitations":%s,"metadata":null}
                """.formatted(outcome, limitations);
    }
}
