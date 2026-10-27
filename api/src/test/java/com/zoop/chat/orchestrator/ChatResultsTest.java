package com.zoop.chat.orchestrator;

import java.time.Instant;
import java.util.List;

import com.zoop.chat.dto.ChatFrozenContext;
import com.zoop.chat.dto.ChatPeriod;
import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.orchestrator.ChatResults.InsufficientCause;
import com.zoop.chat.service.FrozenSelection;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/** D-AI-02 insufficient-evidence wording: server sentences chosen from the cause and the run's own scope. */
class ChatResultsTest {
    @Test
    void theHintFollowsTheRunsScopeAndANarrowedSelectionComesFirst() {
        var plain = run(null, FrozenSelection.NONE);
        var period = run(new ChatPeriod("2026-10-01", "2026-10-21"), FrozenSelection.NONE);
        var narrowed = run(new ChatPeriod("2026-10-01", "2026-10-21"),
                new FrozenSelection(List.of("KRX:000660"), List.of("ev-1"), List.of("ev-1")));

        assertEquals("조회한 범위에서 관련된 공개 자료를 찾지 못했어요. 다른 기업이나 사건을 지목하거나, 지도에서 대상을 고른 뒤 다시 "
                + "물어봐 주세요.", ChatResults.insufficientReason(plain, InsufficientCause.NOTHING_FOUND));
        assertTrue(ChatResults.insufficientReason(period, InsufficientCause.NOTHING_FOUND).endsWith("기간을 넓히거나 다른 "
                + "기업·사건을 지목해 다시 물어봐 주세요."));
        assertTrue(ChatResults.insufficientReason(period, InsufficientCause.RESULTS_TRUNCATED).endsWith("대상이나 기간을 좁혀 "
                + "다시 물어봐 주세요."), "a cut read asks for less, not more");
        assertTrue(ChatResults.insufficientReason(narrowed, InsufficientCause.RESULTS_TRUNCATED).contains("선택한 근거 안에서만"));
        for (var cause : InsufficientCause.values()) {
            assertTrue(ChatResults.insufficientReason(plain, cause).length() <= 500, cause.name());
        }
    }

    @Test
    void anInsufficientLimitationKeepsItsKindAndSaysWhyWhenKnown() {
        var held = ChatResults.insufficient(InsufficientCause.EVIDENCE_HELD, "요구 r1");
        assertEquals("evidence_insufficient", held.kind());
        assertEquals("이 부분은 답변 내용이 근거와 맞는지 충분히 확인하지 못해 뺐어요.", held.message());
        assertEquals("이 부분은 조회한 범위에서 관련 자료를 찾지 못했어요.",
                ChatResults.insufficient(InsufficientCause.NOTHING_FOUND, "요구 r1").message());
        assertEquals(ChatResults.limitation("evidence_insufficient", "요구 r1"),
                ChatResults.insufficient(InsufficientCause.EVIDENCE_INSUFFICIENT, "요구 r1"));
    }

    private static ChatRun run(ChatPeriod period, FrozenSelection selection) {
        return new ChatRun("job-1", "conv-1", "member-a", 1, "run", List.of(new ChatRun.Turn("job-1", "질문", null, null)),
                new ChatFrozenContext(List.of(), 0, period, null, "v1"), selection, "v1", 0, Instant.EPOCH,
                Instant.EPOCH.plusSeconds(60));
    }
}
