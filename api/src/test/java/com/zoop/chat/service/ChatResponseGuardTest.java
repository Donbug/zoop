package com.zoop.chat.service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.Set;

import com.zoop.chat.dto.ChatAnswerSection;
import com.zoop.chat.dto.ChatApplied;
import com.zoop.chat.dto.ChatAppliedItem;
import com.zoop.chat.dto.ChatContextItem;
import com.zoop.chat.dto.ChatConversation;
import com.zoop.chat.dto.ChatCurrentResponse;
import com.zoop.chat.dto.ChatFrozenContext;
import com.zoop.chat.dto.ChatJob;
import com.zoop.chat.dto.ChatResult;
import com.zoop.chat.dto.ChatSessionResponse;
import com.zoop.chat.dto.ChatUiAction;
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
    private final List<String> targetChecks = new ArrayList<>();

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
        assertEquals("complete", job.result().answerStatus());
        assertEquals("guidance", shown.answerStatus(), "only the fixed sentence is shown");
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
    void aSyntheticWebCitationIsShownAgainAndAnyOtherProvidersIsWithheld() {
        // Until a real provider's redisplay rights are decided (web search design 7), only the synthetic one is shown again.
        var job = job(List.of(), web("synthetic"));
        assertSame(job, guard(Set.of()).job(job, "r"), "no evidence record is read for a web hit");
        assertEquals(ChatResponseGuard.WITHHELD_ANSWER, guard(Set.of()).job(job(List.of(), web("other")), "r").result()
                .answer());
    }

    private static ChatResult web(String provider) {
        String hit = "web-" + "b".repeat(32);
        var citation = new Citation("web_result", hit, "[합성] snippet", null, null, provider, null, 0, 12, "[합성] 제목",
                "news.example.com", AT, "https://news.example.com/a");
        return new ChatResult("answered", "msg-job-00001", "웹 본문",
                List.of(new ChatAnswerSection("web_reported", "웹 본문", List.of(hit))), "web_reported", null, List.of(),
                List.of(citation), List.of(), applied(), List.of(), null, List.of(), metadata());
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

    @Test
    void anAppliedTargetHiddenSinceTheRunIsLeftOutOfAnInsufficientResultWithoutChangingTheStoredOne() {
        var job = job(List.of(), insufficient());
        var shown = guard(Set.of(), Optional.of(Set.of("KRX:000660"))).job(job, "req-1").result();
        assertEquals(List.of(new ChatAppliedItem("KRX:000660", "SK하이닉스")), shown.applied().companies());
        assertEquals(List.of(), shown.applied().issues(), "an issue excluded since the run is not named again");
        assertEquals(job.result().reason(), shown.reason());
        assertEquals(2,job.result().applied().companies().size() + job.result().applied().issues().size(),
                "what is stored never changes");
        assertEquals(List.of("KRX:000660,iss-1@gv-1@" + AS_OF), targetChecks);

        var unchecked = guard(Set.of(), Optional.empty()).job(job, "req-2").result();
        assertTrue(unchecked.applied().companies().isEmpty() && unchecked.applied().issues().isEmpty(),
                "visibility that cannot be checked shows nothing");

        var visible = guard(Set.of(), Optional.of(Set.of("KRX:000660", "iss-1")));
        assertSame(job, visible.job(job, "req-3"));
    }

    @Test
    void anAnsweredResultKeepsOnlyVisibleAppliedTargetsAndAConversationChecksEachOnce() {
        var result = answered("ev-1");
        var withTargets = new ChatResult(result.outcome(), result.messageId(), result.answer(), result.sections(),
                result.answerBasis(), result.reason(), result.sources(), result.citations(), result.graphTargets(),
                new ChatApplied(List.of(new ChatAppliedItem("KRX:000660", "SK하이닉스")),
                        List.of(new ChatAppliedItem("iss-1", "HBM 공급 확대")), null, "gv-1", AT, false),
                result.choices(), result.action(), result.limitations(), result.metadata());
        var guard = guard(Set.of("ev-1"), Optional.of(Set.of("KRX:000660")));
        var conversation = new ChatConversation(new ChatSessionResponse("conv-0001", AT, 2),
                List.of(job(List.of(), withTargets), job(List.of(), withTargets)));
        var shown = guard.conversation(conversation, "req-1");
        for (var job : shown.jobs()) {
            assertEquals("근거 본문", job.result().answer(), "readable citations keep the answer");
            assertEquals(List.of("KRX:000660"), job.result().applied().companies().stream().map(ChatAppliedItem::id).toList());
            assertTrue(job.result().applied().issues().isEmpty());
        }
        assertEquals(1, targetChecks.size(), "each target is checked once per conversation");
    }

    @Test
    void anActionOnASinceHiddenCompanyIsLeftOutWhileARoundStaysForItsScreenToCheck() {
        var result = answered("ev-1");
        var open = new ChatUiAction("action-1", ChatUiAction.OPEN_COMPANY, "기업 상세 · 숨은 기업", List.of("r1"),
                ChatUiAction.Target.company("KRX:hidden"));
        var path = new ChatUiAction("action-2", ChatUiAction.FOCUS_PATH, "경로 보기", List.of("r1"),
                ChatUiAction.Target.path("KRX:000660", "KRX:hidden", "gv-1", null));
        var round = new ChatUiAction("action-3", ChatUiAction.OPEN_BRIEFING, "브리핑 열기", List.of("r1"),
                ChatUiAction.Target.briefing("2026-10-30", "morning"));
        var offered = new ChatResult(result.outcome(), result.messageId(), result.answer(), result.sections(),
                result.answerBasis(), result.reason(), result.sources(), result.citations(), result.graphTargets(),
                result.applied(), result.choices(), result.action(), result.limitations(), result.metadata(),
                result.answerStatus(), result.notices(), List.of(open, path, round));

        var shown = guard(Set.of("ev-1"), Optional.of(Set.of("KRX:000660"))).job(job(List.of(), offered), "req-1").result();
        assertEquals(List.of(round), shown.uiActions());

        var withheld = guard(Set.of()).job(job(List.of(), offered), "req-2").result();
        assertTrue(withheld.uiActions().isEmpty(), "a withheld answer offers nothing");
    }

    @Test
    void aMapTargetExcludedSinceTheRunIsLeftOutWhileItsSharedEvidenceKeepsTheAnswer() {
        var result = answered("ev-shared");
        var mapped = new ChatResult(result.outcome(), result.messageId(), result.answer(), result.sections(),
                result.answerBasis(), result.reason(), result.sources(), result.citations(),
                List.of(new GraphTarget("KRX:000660", "company"), new GraphTarget("iss-excluded", "issue")), result.applied(),
                result.choices(), result.action(), result.limitations(), result.metadata());
        var job = job(List.of(), mapped);

        // The issue was excluded, but the evidence is still readable through a public relation that cites it too.
        var shown = guard(Set.of("ev-shared"), Optional.of(Set.of("KRX:000660"))).job(job, "req-1").result();
        assertEquals("근거 본문", shown.answer(), "the citation still reads, so the answer stays");
        assertEquals(result.citations(), shown.citations());
        assertEquals(List.of(new GraphTarget("KRX:000660", "company")), shown.graphTargets(),
                "the excluded issue is no longer a place the map moves to");
        assertEquals(2, job.result().graphTargets().size(), "what is stored never changes");

        var unchecked = guard(Set.of("ev-shared"), Optional.empty()).job(job, "req-2").result();
        assertTrue(unchecked.graphTargets().isEmpty(), "visibility that cannot be checked shows no map target");
        assertEquals("근거 본문", unchecked.answer());
    }

    /** Every applied or map target is visible. */
    private ChatResponseGuard guard(Set<String> readable) {
        return guard(readable, null);
    }

    private ChatResponseGuard guard(Set<String> readable, Optional<Set<String>> visible) {
        return new ChatResponseGuard((id, version, asOf, requestId) -> {
            checks.add(id + "@" + version + "@" + asOf);
            return readable.contains(id);
        }, (ids, version, asOf, requestId) -> {
            targetChecks.add(String.join(",", ids.stream().sorted().toList()) + "@" + version + "@" + asOf);
            if (visible == null) return Optional.of(ids);
            return visible.map(v -> Set.copyOf(ids.stream().filter(v::contains).toList()));
        });
    }

    private static ChatResult insufficient() {
        return new ChatResult("insufficient_evidence", "msg-job-00001", "", List.of(), "none",
                "관련 항목은 찾았지만 답에 쓸 수 있는 공개 근거가 부족했어요.", List.of(), List.of(), List.of(),
                new ChatApplied(List.of(new ChatAppliedItem("KRX:000660", "SK하이닉스")),
                        List.of(new ChatAppliedItem("iss-1", "HBM 공급 확대")), null, "gv-1", AT, false),
                List.of(), null, List.of(), metadata());
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
