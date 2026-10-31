package com.zoop.chat.executor;

import java.time.Instant;
import java.util.List;

import com.zoop.chat.dto.ChatAppliedItem;
import com.zoop.chat.dto.ChatPeriod;
import com.zoop.chat.repository.ChatJobRow;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.jupiter.api.Assertions.*;

/** D-AI-02: what a conversation's last answers carry to its next question. */
class ChatPriorTurnsTest {
    private static final Instant NOW = Instant.parse("2026-10-21T03:00:00Z");
    private final ObjectMapper mapper = JsonMapper.builder().build();

    @Test
    void theNewestAnswerWithTargetsSpeaksForThemAndAConceptAnswerIsSkipped() {
        var prior = ChatPriorTurns.of(List.of(answer("""
                {"answer":"PER은 주가수익비율입니다","applied":{"companies":[],"issues":[],"period":null}}"""), answer("""
                {"applied":{"companies":[{"id":"KRX:005930","label":"삼성전자"}],"issues":[{"id":"iss-1","label":"계약"}],"period":null}}""")),
                mapper);
        assertEquals(List.of(new ChatAppliedItem("KRX:005930", "삼성전자")), prior.companies());
        assertEquals(List.of(new ChatAppliedItem("iss-1", "계약")), prior.issues());
        assertNull(prior.period());
    }

    @Test
    void onlyAPeriodTheMemberAskedForIsCarried() {
        var asked = ChatPriorTurns.of(List.of(answer("""
                {"applied":{"companies":[],"issues":[],"period":{"start":"2026-10-01","end":"2026-10-07","basis":"question","expression":"지난주"}}}""")),
                mapper);
        assertEquals(new ChatPeriod("2026-10-01", "2026-10-07"), asked.period());

        var spanned = ChatPriorTurns.of(List.of(answer("""
                {"applied":{"companies":[],"issues":[],"period":{"start":"2026-10-01","end":"2026-10-07","basis":"evidence","expression":null}}}""")),
                mapper);
        assertNull(spanned.period());
    }

    @Test
    void noEarlierAnswerCarriesNothing() {
        assertEquals(ChatRun.Prior.NONE, ChatPriorTurns.of(List.of(), mapper));
    }

    private static ChatJobRow answer(String result) {
        return new ChatJobRow("job-1", "conv-1", "member-a", 1, "질문", "a".repeat(64), NOW, "{}", "{}", List.of(), null,
                "completed", null, "answered", null, null, 0, result, null, 1, "[]", NOW, NOW, NOW);
    }
}
