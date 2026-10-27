package com.zoop.chat.service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

import com.zoop.chat.dto.ChatAnswerSection;
import com.zoop.chat.dto.ChatApplied;
import com.zoop.chat.dto.ChatContextItem;
import com.zoop.chat.dto.ChatConversation;
import com.zoop.chat.dto.ChatCurrentResponse;
import com.zoop.chat.dto.ChatFrozenContext;
import com.zoop.chat.dto.ChatJob;
import com.zoop.chat.dto.ChatResult;
import com.zoop.chat.dto.ChatSessionResponse;
import com.zoop.chat.dto.Citation;
import com.zoop.chat.dto.GraphTarget;
import com.zoop.common.response.Metadata;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/** Every returned job is re-checked against current evidence access; what is stored never changes. */
class ChatResponseGuardTest {
    private static final Instant AT = Instant.parse("2026-10-21T03:00:00Z");
    private static final Instant AS_OF = Instant.parse("2026-10-20T00:00:00Z");

    private final List<String> checks = new ArrayList<>();

    @Test
    void readableEvidenceIsReturnedUnchangedAtThePinnedVersion() {
        var job = job(List.of(item("ev-1", "evidence", "보도 제목")), answered("ev-1"));
        assertSame(job, guard(Set.of("ev-1")).job(job, "req-1"));
        assertEquals(List.of("ev-1@gv-1@" + AS_OF), checks);
    }

    @Test
    void aWithdrawnSelectedEvidenceLosesItsTitleButKeepsItsId() {
        var job = job(List.of(item("company-1", "company", "SK하이닉스"), item("ev-1", "evidence", "보도 제목")), null);
        var shown = guard(Set.of()).job(job, "req-1");
        assertEquals(List.of(item("company-1", "company", "SK하이닉스"),
                item("ev-1", "evidence", ChatResponseGuard.WITHHELD_EVIDENCE_LABEL)), shown.context().items());
        assertEquals(job.context().evidenceCount(), shown.context().evidenceCount());
    }

    @Test
    void aResultCitingUnreadableEvidenceReturnsNoProtectedContent() {
        var job = job(List.of(), answered("ev-1", "ev-2"));
        var shown = guard(Set.of("ev-1")).job(job, "req-1").result();
        assertEquals("answered", shown.outcome());
        assertEquals(ChatResponseGuard.WITHHELD_ANSWER, shown.answer());
        assertEquals("none", shown.answerBasis());
        assertTrue(shown.sections().isEmpty() && shown.citations().isEmpty() && shown.sources().isEmpty()
                && shown.graphTargets().isEmpty());
        assertEquals(job.result().messageId(), shown.messageId());
        assertEquals(job.result().limitations(), shown.limitations());
    }

    @Test
    void aSectionEvidenceIdOutsideTheCitationsIsCheckedToo() {
        var result = answered("ev-1");
        var widened = new ChatResult(result.outcome(), result.messageId(), result.answer(),
                List.of(new ChatAnswerSection("evidence_grounded", "본문", List.of("ev-1", "ev-9"))), result.answerBasis(),
                result.reason(), result.sources(), result.citations(), result.graphTargets(), result.applied(),
                result.choices(), result.action(), result.limitations(), result.metadata());
        assertEquals(ChatResponseGuard.WITHHELD_ANSWER, guard(Set.of("ev-1")).job(job(List.of(), widened), "r").result().answer());
    }

    @Test
    void aZoopDocumentCitationIsShownWhileItsVersionIsInEffectAndWithheldOnceReplaced() {
        var job = job(List.of(), documented("zoop_doc"));
        assertSame(job, guard(Set.of("doc-1")).job(job, "r"));
        assertEquals(ChatResponseGuard.WITHHELD_ANSWER, guard(Set.of()).job(job, "r").result().answer());
    }

    @Test
    void aCitationOfAnUnknownKindIsWithheldEvenWhenItsIdReads() {
        assertEquals(ChatResponseGuard.WITHHELD_ANSWER,
                guard(Set.of("doc-1")).job(job(List.of(), documented("help_page")), "r").result().answer());
    }

    private static ChatResult documented(String sourceKind) {
        return new ChatResult("answered", "msg-1", "ZOOP 안내 본문",
                List.of(new ChatAnswerSection("zoop_documented", "ZOOP 안내 본문", List.of("doc-1"))), "zoop_documented",
                null, List.of(), List.of(new Citation(sourceKind, "doc-1", "구간", null, null, "policy.privacy", "v1", 0, 2,
                        "개인정보 처리방침 · 1. 처리 목적과 항목", null, null, null)), List.of(), applied(), List.of(), null,
                List.of(), metadata());
    }

    @Test
    void aConversationChecksEachEvidenceOnceAndTheRestoreIsGuardedToo() {
        var guard = guard(Set.of("ev-1"));
        var first = job(List.of(item("ev-1", "evidence", "제목")), answered("ev-1"));
        var second = job(List.of(), answered("ev-1", "ev-2"));
        var conversation = new ChatConversation(new ChatSessionResponse("conv-0001", AT, 2), List.of(first, second));
        var shown = guard.conversation(conversation, "req-1");
        assertSame(first, shown.jobs().get(0));
        assertEquals(ChatResponseGuard.WITHHELD_ANSWER, shown.jobs().get(1).result().answer());
        assertEquals(2, checks.size());

        var restored = guard.current(new ChatCurrentResponse(conversation), "req-2");
        assertEquals(ChatResponseGuard.WITHHELD_ANSWER, restored.conversation().jobs().get(1).result().answer());
        assertNull(guard.current(new ChatCurrentResponse(null), "req-3").conversation());
    }

    private ChatResponseGuard guard(Set<String> readable) {
        return new ChatResponseGuard((id, version, asOf, requestId) -> {
            checks.add(id + "@" + version + "@" + asOf);
            return readable.contains(id);
        });
    }

    private static ChatJob job(List<ChatContextItem> items, ChatResult result) {
        return new ChatJob("job-00001", "conv-0001", 1, "질문", result == null ? "queued" : "completed", null,
                result == null ? null : result.outcome(), AT, new ChatFrozenContext(items, 1, null, AS_OF, "gv-1"), null,
                null, result, 1, AT, AT, result == null ? null : AT);
    }

    private static ChatContextItem item(String id, String kind, String label) {
        return new ChatContextItem(id, kind, label);
    }

    private static ChatResult answered(String... evidenceIds) {
        List<Citation> citations = new ArrayList<>();
        for (String id : evidenceIds) {
            citations.add(new Citation("article", id, "인용", "art-1", "v1", null, null, 0, 2, "보도", "언론사", AT,
                    "https://example.invalid/a"));
        }
        return new ChatResult("answered", "msg-job-00001", "근거 본문",
                List.of(new ChatAnswerSection("evidence_grounded", "근거 본문", List.of(evidenceIds))), "evidence_grounded",
                null, List.of("art-1"), citations, List.of(new GraphTarget("company-1", "company")), applied(), List.of(),
                null, List.of(), metadata());
    }

    private static ChatApplied applied() {
        return new ChatApplied(List.of(), List.of(), null, "gv-1", AT, false);
    }

    private static Metadata metadata() {
        return new Metadata("zoop", AT, "gv-1", "req-0", false, List.of());
    }
}
