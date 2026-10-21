package com.zoop.chat.dto;

import java.time.Instant;
import java.util.List;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import tools.jackson.databind.ObjectMapper;

import static org.junit.jupiter.api.Assertions.*;

/** OpenAPI {@code ChatJobRequest}: the request is read strictly and never coerced. */
class ChatJobRequestTest {
    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    void readsAQuestionWithItsSelection() {
        var request = parse("""
                {"jobId":"job-00001","question":"SK하이닉스 최근 이슈는?","context":{"contextIds":["company-sk","issue-1"],
                 "evidenceIds":["ev-1"],"period":{"start":"2026-10-01","end":"2026-10-20"},
                 "asOf":"2026-10-20T09:00:00+09:00","graphVersion":"gv-1"}}
                """);
        assertEquals("job-00001", request.jobId());
        assertEquals(List.of("company-sk", "issue-1"), request.context().contextIds());
        assertEquals(new ChatPeriod("2026-10-01", "2026-10-20"), request.context().period());
        assertEquals(Instant.parse("2026-10-20T00:00:00Z"), request.context().asOf());
        assertNull(request.resolves());
    }

    @Test
    void readsAClarificationReplyWithAChoiceOrFreeText() {
        assertEquals(new ChatClarificationReply("job-00001", "choice-a"),
                parse("{\"jobId\":\"job-00002\",\"question\":\"삼성전자\",\"resolves\":{\"jobId\":\"job-00001\",\"choiceId\":\"choice-a\"}}")
                        .resolves());
        var free = parse("{\"jobId\":\"job-00002\",\"question\":\"반도체 쪽\",\"resolves\":{\"jobId\":\"job-00001\",\"choiceId\":null}}");
        assertNull(free.resolves().choiceId());
        assertNull(free.context());
    }

    @Test
    void absentContextStaysAbsentAndAnEmptyOneIsEmpty() {
        assertNull(parse("{\"jobId\":\"job-00001\",\"question\":\"HBM이 뭐야?\"}").context());
        assertEquals(ChatContextRequest.EMPTY, parse("{\"jobId\":\"job-00001\",\"question\":\"q\",\"context\":{}}").context());
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "{\"jobId\":\"job-00001\"}",
            "{\"jobId\":\"short\",\"question\":\"q\"}",
            "{\"jobId\":\"job-00001\",\"question\":\"   \"}",
            "{\"jobId\":\"job-00001\",\"question\":\"\"}",
            "{\"jobId\":\"job-00001\",\"question\":1}",
            "{\"jobId\":\"job-00001\",\"question\":\"q\",\"extra\":true}",
            "{\"jobId\":\"job-00001\",\"question\":\"q\",\"context\":{},\"resolves\":{\"jobId\":\"job-00000\",\"choiceId\":null}}",
            "{\"jobId\":\"job-00001\",\"question\":\"q\",\"context\":null}",
            "{\"jobId\":\"job-00001\",\"question\":\"q\",\"context\":{\"contextIds\":[\"a\",\"a\"]}}",
            "{\"jobId\":\"job-00001\",\"question\":\"q\",\"context\":{\"contextIds\":[\" \"]}}",
            "{\"jobId\":\"job-00001\",\"question\":\"q\",\"context\":{\"other\":[]}}",
            "{\"jobId\":\"job-00001\",\"question\":\"q\",\"context\":{\"period\":{\"start\":\"2026-10-20\",\"end\":\"2026-10-01\"}}}",
            "{\"jobId\":\"job-00001\",\"question\":\"q\",\"context\":{\"period\":{\"start\":\"2026-02-30\",\"end\":\"2026-03-01\"}}}",
            "{\"jobId\":\"job-00001\",\"question\":\"q\",\"context\":{\"asOf\":\"2026-10-20T09:00:00\"}}",
            "{\"jobId\":\"job-00001\",\"question\":\"q\",\"context\":{\"graphVersion\":\"\"}}",
            "{\"jobId\":\"job-00001\",\"question\":\"q\",\"resolves\":{\"jobId\":\"job-00000\"}}",
            "{\"jobId\":\"job-00001\",\"question\":\"q\",\"resolves\":{\"jobId\":\"job-00000\",\"choiceId\":\"\"}}",
            "{\"jobId\":\"job-00001\",\"question\":\"q\",\"resolves\":null}",
            "[]"
    })
    void refusesAnythingTheContractDoesNotAllow(String body) {
        var error = assertThrows(CustomException.class, () -> parse(body));
        assertEquals(ErrorCode.INVALID_REQUEST, error.getErrorCode());
    }

    @Test
    void boundsTheQuestionInCodePointsAndTheSelectionInIds() {
        String emoji = "😀".repeat(ChatJobRequest.MAX_QUESTION);
        assertEquals(emoji, parse("{\"jobId\":\"job-00001\",\"question\":\"" + emoji + "\"}").question());
        assertThrows(CustomException.class,
                () -> parse("{\"jobId\":\"job-00001\",\"question\":\"" + emoji + "x\"}"));

        String twenty = String.join(",", java.util.stream.IntStream.range(0, 20).mapToObj(i -> "\"id-" + i + "\"").toList());
        assertEquals(20, parse("{\"jobId\":\"job-00001\",\"question\":\"q\",\"context\":{\"contextIds\":[" + twenty + "]}}")
                .context().contextIds().size());
        assertThrows(CustomException.class, () -> parse(
                "{\"jobId\":\"job-00001\",\"question\":\"q\",\"context\":{\"contextIds\":[" + twenty + ",\"id-20\"]}}"));
    }

    private ChatJobRequest parse(String json) {
        return ChatJobRequest.parse(mapper.readTree(json));
    }
}
