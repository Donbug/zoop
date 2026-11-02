package com.zoop.chat.executor;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

import com.zoop.chat.dto.ChatAppliedItem;
import com.zoop.chat.dto.ChatFailure;
import com.zoop.chat.dto.ChatResult;
import com.zoop.chat.repository.ChatJobRow;
import com.zoop.chat.repository.ChatToolCallEnd;
import com.zoop.chat.repository.NewChatToolCall;
import com.zoop.chat.tool.ChatToolRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.support.StaticListableBeanFactory;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.AbstractPlatformTransactionManager;
import org.springframework.transaction.support.DefaultTransactionStatus;
import tools.jackson.databind.ObjectMapper;

import static org.junit.jupiter.api.Assertions.*;

/** D-AI-02: a queued job is claimed, run under its owner token and ends stored; a superseded run changes nothing. */
class ChatJobExecutorTest {
    private static final Instant NOW = Instant.parse("2026-10-21T03:00:00Z");
    private static final String CONTEXT = "{\"items\":[],\"evidenceCount\":0,\"period\":null,\"asOf\":null,\"graphVersion\":null}";
    private static final String SELECTION = "{\"contextIds\":[\"ev-1\"],\"evidenceIds\":[],\"evidencePool\":[\"ev-1\"]}";

    private final ObjectMapper mapper = new ObjectMapper();
    private MemoryChatStore store;
    private MutableClock clock;

    @BeforeEach
    void setUp() {
        store = new MemoryChatStore();
        clock = new MutableClock(NOW);
    }

    @Test
    void withoutAnEngineNothingIsClaimed() {
        store.add(queued("job-00001", null, null, 0, "run"));
        var executor = executor(null);
        assertFalse(executor.hasEngine());
        assertFalse(executor.runOnce());
        assertEquals("queued", store.job("job-00001").row.status());
    }

    @Test
    void aRunReportsPhasesCountsItsModelCallOnceAndStoresTheResult() {
        store.add(queued("job-00001", null, null, 0, "run"));
        var engine = new ScriptedChatEngine((run, control) -> {
            assertTrue(control.owned());
            assertEquals(Duration.ofSeconds(45), control.remaining());
            control.beforeModelCall();
            control.phase("writing");
            control.beforeModelCall();
            control.phase("verifying");
            return ScriptedChatEngine.generalAnswer("HBM은 고대역폭 메모리입니다.");
        });

        assertTrue(executor(engine).runOnce());
        var job = store.job("job-00001");
        assertEquals("completed", job.row.status());
        assertEquals("answered", job.row.outcome());
        assertEquals(1, job.row.runs());
        assertEquals(List.of("writing", "verifying"), job.phases);
        assertEquals("msg-job-00001", job.messageId);
        ChatResult stored = mapper.readValue(job.result, ChatResult.class);
        assertEquals("msg-job-00001", stored.messageId());
        assertEquals("general_knowledge", stored.sections().getFirst().basis());
        assertTrue(job.row.attempts().contains("\"status\":\"succeeded\""), job.row.attempts());
        assertTrue(job.row.attempts().contains("\"modelCalled\":true"));
        assertNull(job.ownerToken);
        assertFalse(executor(engine).runOnce());
    }

    @Test
    void aReplyRunsWithTheWholeClarificationChainInOrder() {
        store.add(withResult(queued("job-00001", null, null, 0, "run", "completed"),
                ScriptedChatEngine.clarification("어느 기업인가요?", "choice-a", "choice-b").result()));
        store.add(queued("job-00002", "job-00001", "choice-a", 1, "run", "completed"));
        store.add(queued("job-00003", "job-00002", null, 2, "run"));
        var engine = new ScriptedChatEngine((run, control) -> ScriptedChatEngine.guidance("대상을 구체적으로 적어 주세요."));

        executor(engine).runOnce();
        var run = engine.runs.getFirst();
        assertEquals("job-00003", run.jobId());
        assertEquals(2, run.clarificationDepth());
        assertEquals(List.of("ev-1"), run.selection().evidencePool());
        // The picked option carries the label the clarification showed, so the next run can read what was chosen.
        assertEquals(List.of(new ChatRun.Turn("job-00001", "질문 job-00001", null, null),
                new ChatRun.Turn("job-00002", "질문 job-00002", "choice-a", "choice-a 선택"),
                new ChatRun.Turn("job-00003", "질문 job-00003", null, null)), run.turns());
        assertEquals("guidance", store.job("job-00003").row.outcome());
    }

    @Test
    void aRunCarriesTheLastAnswersTargetsItCanStillSeeAndAReplyCarriesTheSameOnes() {
        store.add(answered(queued("job-00001", null, null, 0, "run", "completed"), """
                {"applied":{"companies":[{"id":"KRX:005930","label":"삼성전자"},{"id":"KRX:000660","label":"SK하이닉스"}],"issues":[],
                "period":{"start":"2026-10-12","end":"2026-10-18","basis":"question","expression":"지난주"}}}"""));
        store.add(withResult(queued("job-00002", null, null, 1, "run", "completed"),
                ScriptedChatEngine.clarification("어느 기업인가요?", "KRX:000660").result()));
        store.add(queued("job-00003", "job-00002", "KRX:000660", 2, "run"));
        var engine = new ScriptedChatEngine((run, control) -> ScriptedChatEngine.guidance("안내"));

        var beans = new StaticListableBeanFactory(Map.of("engine", engine));
        new ChatJobExecutor(store, store, beans.getBeanProvider(ChatEngine.class), mapper, clock, new NoTransactions(),
                (ids, version, asOf, request) -> Optional.of(Set.of("KRX:000660"))).runOnce();

        var prior = engine.runs.getFirst().prior();
        assertEquals(List.of(new ChatAppliedItem("KRX:000660", "SK하이닉스")), prior.companies(),
                "a company no longer visible is no candidate");
        assertEquals("2026-10-12", prior.period().start());
    }

    @Test
    void carriedTargetsThatCannotBeCheckedAreDropped() {
        store.add(answered(queued("job-00001", null, null, 0, "run", "completed"), """
                {"applied":{"companies":[{"id":"KRX:005930","label":"삼성전자"}],"issues":[],"period":null}}"""));
        store.add(queued("job-00002", null, null, 1, "run"));
        var engine = new ScriptedChatEngine((run, control) -> ScriptedChatEngine.guidance("안내"));

        var beans = new StaticListableBeanFactory(Map.of("engine", engine));
        new ChatJobExecutor(store, store, beans.getBeanProvider(ChatEngine.class), mapper, clock, new NoTransactions(),
                (ids, version, asOf, request) -> Optional.empty()).runOnce();

        assertTrue(engine.runs.getFirst().prior().companies().isEmpty());
    }

    @Test
    void aDepthTwoJobNeverStoresAClarification() {
        store.add(queued("job-00001", null, null, 0, "run", "completed"));
        store.add(queued("job-00002", "job-00001", null, 1, "run", "completed"));
        store.add(queued("job-00003", "job-00002", null, 2, "run"));
        executor(new ScriptedChatEngine((run, control) -> ScriptedChatEngine.clarification("어느 회사?", "a"))).runOnce();

        var job = store.job("job-00003");
        assertEquals("failed", job.row.status());
        assertEquals(new ChatFailure("internal", null, job(job).message(), null), job(job));
    }

    @Test
    void aClarificationBelowTheLimitIsStoredWithItsChoices() {
        store.add(queued("job-00001", null, null, 0, "run"));
        executor(new ScriptedChatEngine((run, control) -> ScriptedChatEngine.clarification("어느 삼성?", "a", "b"))).runOnce();
        var stored = mapper.readValue(store.job("job-00001").result, ChatResult.class);
        assertEquals("clarification", stored.outcome());
        assertEquals(2, stored.choices().size());
    }

    @Test
    void retryIsGrantedOnlyForARerunnableTransientFailureWithinThreeRuns() {
        assertFailure(1, new ChatEngineOutcome.Failed("transient", "provider_error", true), "rerun", "failed");
        assertFailure(2, new ChatEngineOutcome.Failed("transient", "tool_timeout", true), null, "failed");
        assertFailure(0, new ChatEngineOutcome.Failed("transient", "response_unknown", false), null, "unknown");
        assertFailure(0, new ChatEngineOutcome.Failed("transient", "response_unknown", true), null, "unknown");
        assertFailure(0, new ChatEngineOutcome.Failed("budget_exceeded", "context_too_large", true), null, "failed");
        assertFailure(0, new ChatEngineOutcome.Failed("validation_failed", null, false), null, "failed");
        assertFailure(0, new ChatEngineOutcome.Failed("save_failed", null, true), null, "failed");
    }

    @Test
    void anUnexpectedEngineErrorIsAnInternalFailureThatIsNeverRerun() {
        store.add(queued("job-00001", null, null, 0, "run"));
        executor(new ScriptedChatEngine((run, control) -> {
            throw new IllegalStateException("bug");
        })).runOnce();
        var failure = job(store.job("job-00001"));
        assertEquals("internal", failure.kind());
        assertNull(failure.retry());
    }

    @Test
    void aCancelledRunCannotReportProgressOrStoreItsResult() {
        store.add(queued("job-00001", null, null, 0, "run"));
        var engine = new ScriptedChatEngine((run, control) -> {
            store.cancel(run.jobId(), clock.instant());
            assertFalse(control.owned());
            assertThrows(ChatRunSuperseded.class, () -> control.phase("writing"));
            assertThrows(ChatRunSuperseded.class, control::beforeModelCall);
            return ScriptedChatEngine.generalAnswer("늦은 답");
        });
        executor(engine).runOnce();
        var job = store.job("job-00001");
        assertEquals("cancelled", job.row.status());
        assertNull(job.result);
        assertEquals(0, job.row.runs());
    }

    @Test
    void aLateCompletionAfterTheLeaseIsRejectedAndRecoveryEndsTheJob() {
        store.add(queued("job-00001", null, null, 0, "run"));
        store.add(queued("job-00002", null, null, 0, "run"));
        var engine = new ScriptedChatEngine((run, control) -> {
            if (run.jobId().equals("job-00001")) control.beforeModelCall();
            clock.advance(ChatJobExecutor.MAX_DEADLINE.plus(ChatJobExecutor.LEASE_GRACE));
            return ScriptedChatEngine.generalAnswer("너무 늦은 답");
        });
        var executor = executor(engine);
        executor.runOnce();
        executor.runOnce();
        assertEquals("running", store.job("job-00001").row.status());
        assertNull(store.job("job-00001").result);

        assertEquals(2, executor.recoverExpired());
        var called = job(store.job("job-00001"));
        assertEquals(new ChatFailure("transient", "response_unknown", called.message(), null), called);
        assertTrue(store.job("job-00001").row.attempts().contains("\"status\":\"unknown\""));
        var notCalled = job(store.job("job-00002"));
        assertEquals(new ChatFailure("transient", "deadline_guard", notCalled.message(), "rerun"), notCalled);
        assertEquals(0, executor.recoverExpired());
    }

    @Test
    void aVerifiedResultThatCouldNotBeSavedIsSavedAgainWithoutAnyModelCall() {
        store.add(queued("job-00001", null, null, 0, "run"));
        var engine = new ScriptedChatEngine((run, control) -> {
            control.beforeModelCall();
            return ScriptedChatEngine.generalAnswer("저장에 실패할 답");
        });
        store.failingCompletes = 1;
        var executor = executor(engine);
        executor.runOnce();

        var failure = job(store.job("job-00001"));
        assertEquals("save_failed", failure.kind());
        assertEquals("save_only", failure.retry());
        assertEquals(1, store.job("job-00001").row.runs());
        assertTrue(store.verifiedResult("job-00001", 1).isPresent());

        store.jobs.get("job-00001").row = requeuedSaveOnly(store.job("job-00001").row);
        executor.runOnce();

        assertEquals("completed", store.job("job-00001").row.status());
        assertEquals("answered", store.job("job-00001").row.outcome());
        assertEquals(1, store.job("job-00001").row.runs(), "a save is not a run");
        assertEquals(1, engine.runs.size(), "the engine is not called again");
        assertEquals("msg-job-00001", store.job("job-00001").messageId);
        assertTrue(mapper.readValue(store.job("job-00001").result, ChatResult.class).sections().getFirst().text()
                .contains("저장에 실패할 답"));
        assertTrue(store.verifiedResult("job-00001", 1).isEmpty(), "the kept copy goes once it is saved");
    }

    @Test
    void aLeaseThatRunsOutAfterTheResultWasKeptOffersTheSaveInsteadOfAnUnknownFate() {
        store.add(queued("job-00001", null, null, 0, "run"));
        var executor = executor(new ScriptedChatEngine((run, control) -> ScriptedChatEngine.guidance("안내")));
        var claim = executor.claimNext().orElseThrow();
        store.keepVerified("job-00001", claim.ownerToken(), 1, "{}", null, NOW);
        clock.advance(ChatJobExecutor.MAX_DEADLINE.plus(ChatJobExecutor.LEASE_GRACE));

        assertEquals(1, executor.recoverExpired());

        assertEquals("save_only", job(store.job("job-00001")).retry());
    }

    @Test
    void aResultThatNeverGotSavedAndWasNotKeptEndsByLease() {
        store.add(queued("job-00001", null, null, 0, "run"));
        store.failingCompletes = 1;
        store.refuseKeeping = true;
        var executor = executor(new ScriptedChatEngine((run, control) -> ScriptedChatEngine.generalAnswer("답")));
        executor.runOnce();
        assertEquals("running", store.job("job-00001").row.status());

        clock.advance(ChatJobExecutor.MAX_DEADLINE.plus(ChatJobExecutor.LEASE_GRACE));
        executor.recoverExpired();

        assertEquals("transient", job(store.job("job-00001")).kind());
    }

    @Test
    void aFailedRunForgetsWhatItKept() {
        store.add(queued("job-00001", null, null, 0, "run"));
        var executor = executor(new ScriptedChatEngine((run, control) -> {
            clock.advance(ChatJobExecutor.MAX_DEADLINE.plusSeconds(1));
            control.beforeModelCall();
            return ScriptedChatEngine.generalAnswer("기한 뒤의 답");
        }));
        executor.runOnce();

        assertEquals("response_unknown", job(store.job("job-00001")).reason());
        assertTrue(store.verifiedResult("job-00001", 1).isEmpty());
    }

    private static ChatJobRow requeuedSaveOnly(ChatJobRow r) {
        String attempts = r.attempts().substring(0, r.attempts().length() - 1) + ",{\"n\":2,\"mode\":\"save_only\","
                + "\"requestKey\":\"retry-1\",\"status\":\"queued\",\"sourceAttemptNo\":1}]";
        return new ChatJobRow(r.id(), r.sessionId(), r.memberId(), r.seq(), r.question(), r.requestHash(), r.askedAt(),
                r.frozenContext(), r.frozenSelection(), r.contextCompanyIds(), r.graphVersionId(), "queued", null, null,
                r.resolvesJobId(), r.resolvesChoiceId(), r.clarificationDepth(), null, null, r.runs(), attempts, r.createdAt(),
                r.updatedAt(), null);
    }

    @Test
    void aSaveOnlyAttemptCannotRecoverWithoutAKeptResult() {
        store.add(queued("job-00001", null, null, 0, "save_only"));
        var engine = new ScriptedChatEngine((run, control) -> fail("save_only must not call the engine"));
        executor(engine).runOnce();
        assertEquals("result_lost", job(store.job("job-00001")).kind());
        assertTrue(engine.runs.isEmpty());
    }

    @Test
    void aResultReturnedAfterTheRunDeadlineIsNeverStoredAsCompleted() {
        store.add(queued("job-00001", null, null, 0, "run"));
        store.add(queued("job-00002", null, null, 0, "run"));
        var engine = new ScriptedChatEngine((run, control) -> {
            if (run.jobId().equals("job-00001")) control.beforeModelCall();
            // Past the 45 s deadline, still inside the 15 s lease grace: the write would be accepted by the fence.
            clock.advance(Duration.ofSeconds(50));
            return ScriptedChatEngine.generalAnswer("늦은 답");
        });
        var executor = executor(engine);
        executor.runOnce();
        executor.runOnce();

        var called = job(store.job("job-00001"));
        assertEquals("failed", store.job("job-00001").row.status());
        assertEquals("response_unknown", called.reason());
        assertNull(called.retry());
        var notCalled = job(store.job("job-00002"));
        assertEquals("deadline_guard", notCalled.reason());
        assertEquals("rerun", notCalled.retry());
        assertNull(store.job("job-00002").result);
    }

    @Test
    void toolCallsAreReservedInPlanOrderCappedPerAttemptAndClosedWithTheJob() {
        store.add(queued("job-00001", null, null, 0, "run"));
        executor(new ScriptedChatEngine((run, control) -> {
            assertEquals(List.of("tc-0", "tc-1"), control.reserveToolCalls(1,
                    List.of(reservation("company.read"), reservation("issue.read"))));
            control.toolCallStarted("tc-0");
            control.toolCallFinished("tc-0", new ChatToolCallEnd("succeeded", null, "v1", List.of("ev-1"), false, false));
            control.toolCallStarted("tc-1");
            // 2 reserved + 11 would pass the job's cap: nothing of it is reserved.
            assertThrows(IllegalArgumentException.class,
                    () -> control.reserveToolCalls(2, Collections.nCopies(11, reservation("company.read"))));
            assertEquals(List.of("tc-2"), control.reserveToolCalls(2, List.of(reservation("evidence.resolve"))));
            return ScriptedChatEngine.generalAnswer("답");
        })).runOnce();

        var calls = store.toolCalls("job-00001");
        assertEquals(3, calls.size());
        assertEquals(List.of("succeeded", "unknown", "cancelled"), calls.stream().map(c -> c.status).toList(),
                "a call left running ends unknown, a call never started ends cancelled");
        assertEquals(List.of("ev-1"), calls.get(0).end.evidenceIds());
        assertEquals(2, calls.get(2).row.planRevision());
        assertEquals(2, calls.get(2).row.callIndex());
        assertEquals(1, calls.get(2).row.attemptNo());
    }

    @Test
    void aRerunCountsTheCallsItsEarlierAttemptsMadeAgainstTheJobsBudget() {
        // Attempt 1 made four calls and left one reserved call that never ran; attempt 2 is the rerun.
        String attempts = "[{\"n\":1,\"mode\":\"run\",\"requestKey\":\"job-00001\",\"status\":\"failed\"},"
                + "{\"n\":2,\"mode\":\"rerun\",\"requestKey\":\"job-00001-r\",\"status\":\"queued\"}]";
        store.add(withAttempts(queued("job-00001", null, null, 0, "run"), attempts));
        for (int i = 0; i < 5; i++) {
            store.reserveToolCalls(List.of(new NewChatToolCall("row-" + i, "job-00001", 1, 1, i, "tc-" + i,
                    ChatToolRegistry.VERSION, "zoop-core-read", "company.read", "app:company.read", "chat-tool/v1",
                    "0".repeat(64), "{}")), NOW);
        }
        store.toolCalls("job-00001").forEach(c -> c.status = "succeeded");
        store.toolCalls("job-00001").get(4).status = "cancelled";

        executor(new ScriptedChatEngine((run, control) -> {
            assertEquals(2, run.attemptNo());
            assertEquals(ChatRunControl.MAX_TOOL_CALLS - 4, control.toolCallsLeft(), "a reservation that never ran is not a call");
            assertThrows(IllegalArgumentException.class,
                    () -> control.reserveToolCalls(1, Collections.nCopies(3, reservation("company.read"))));
            assertEquals(List.of("tc-0", "tc-1"), control.reserveToolCalls(1,
                    Collections.nCopies(2, reservation("company.read"))), "the rerun numbers its own calls");
            assertEquals(0, control.toolCallsLeft());
            assertThrows(IllegalArgumentException.class,
                    () -> control.reserveToolCalls(2, List.of(reservation("issue.read"))));
            return ScriptedChatEngine.generalAnswer("답");
        })).runOnce();
        assertEquals(7, store.toolCalls("job-00001").size());
    }

    @Test
    void webSearchesHaveTheirOwnJobBudgetAndTakeTheDaysQuotasAllOrNothing() {
        store.add(queued("job-00001", null, null, 0, "run"));
        // 2026-10-21T03:00Z is 12:00 KST on the 21st.
        String day = "2026-10-21";
        executor(new ScriptedChatEngine((run, control) -> {
            // The internal six are untouched by web searches, and the other way round.
            assertEquals(List.of("tc-0", "tc-1"), control.reserveToolCalls(1, Collections.nCopies(2, web())));
            assertEquals(ChatRunControl.MAX_TOOL_CALLS, control.toolCallsLeft());
            var job = assertThrows(ChatWebBudgetExhausted.class, () -> control.reserveToolCalls(2, List.of(web())));
            assertEquals(ChatWebBudgetExhausted.Budget.JOB, job.budget());
            // A refused plan reserves none of its internal calls either.
            assertThrows(ChatWebBudgetExhausted.class,
                    () -> control.reserveToolCalls(2, List.of(reservation("company.read"), web())));
            assertEquals(2, store.toolCalls("job-00001").size());
            assertEquals(List.of("tc-2"), control.reserveToolCalls(2, List.of(reservation("company.read"))));
            return ScriptedChatEngine.generalAnswer("답");
        })).runOnce();
        assertEquals(2, store.webQuotas.get(day + "/project"));
        assertEquals(2, store.webQuotas.get(day + "/member:member-a"));

        // The member's day is spent: nothing is reserved and the project's quota is not taken.
        store.add(queued("job-00002", null, null, 0, "run"));
        store.webQuotas.put(day + "/member:member-a", ChatRunControl.MEMBER_DAILY_WEB_CALLS - 1);
        executor(new ScriptedChatEngine((run, control) -> {
            var member = assertThrows(ChatWebBudgetExhausted.class,
                    () -> control.reserveToolCalls(1, Collections.nCopies(2, web())));
            assertEquals(ChatWebBudgetExhausted.Budget.MEMBER, member.budget());
            assertEquals(List.of("tc-0"), control.reserveToolCalls(1, List.of(web())), "one is still left");
            return ScriptedChatEngine.generalAnswer("답");
        })).runOnce();
        assertEquals(ChatRunControl.MEMBER_DAILY_WEB_CALLS, store.webQuotas.get(day + "/member:member-a"));
        assertEquals(3, store.webQuotas.get(day + "/project"));

        store.add(queued("job-00003", null, null, 0, "run"));
        store.webQuotas.put(day + "/member:member-a", 0);
        store.webQuotas.put(day + "/project", ChatRunControl.PROJECT_DAILY_WEB_CALLS);
        executor(new ScriptedChatEngine((run, control) -> {
            assertEquals(ChatWebBudgetExhausted.Budget.PROJECT, assertThrows(ChatWebBudgetExhausted.class,
                    () -> control.reserveToolCalls(1, List.of(web()))).budget());
            return ScriptedChatEngine.generalAnswer("답");
        })).runOnce();
        assertEquals(0, store.webQuotas.get(day + "/member:member-a"));
        assertTrue(store.toolCalls("job-00003").isEmpty());
    }

    @Test
    void aRerunDoesNotReopenTheJobsBudgetForWebSearchesThatNeverStarted() {
        String attempts = "[{\"n\":1,\"mode\":\"run\",\"requestKey\":\"job-00001\",\"status\":\"failed\"},"
                + "{\"n\":2,\"mode\":\"rerun\",\"requestKey\":\"job-00001-r\",\"status\":\"queued\"}]";
        store.add(withAttempts(queued("job-00001", null, null, 0, "run"), attempts));
        for (int i = 0; i < ChatRunControl.MAX_WEB_CALLS; i++) {
            store.reserveToolCalls(List.of(new NewChatToolCall("row-" + i, "job-00001", 1, 1, i, "tc-" + i,
                    ChatToolRegistry.VERSION, "web-search", "web.search", "app:web.search", "chat-tool/v1",
                    "1".repeat(64), "{}")), NOW);
        }
        store.toolCalls("job-00001").forEach(c -> c.status = "cancelled");

        executor(new ScriptedChatEngine((run, control) -> {
            assertEquals(2, run.attemptNo());
            var spent = assertThrows(ChatWebBudgetExhausted.class,
                    () -> control.reserveToolCalls(1, List.of(web())));
            assertEquals(ChatWebBudgetExhausted.Budget.JOB, spent.budget());
            assertTrue(store.webQuotas.isEmpty(), "a job-budget refusal takes no daily quota");
            return ScriptedChatEngine.generalAnswer("답");
        })).runOnce();
        assertEquals(ChatRunControl.MAX_WEB_CALLS, store.toolCalls("job-00001").size());
    }

    @Test
    void aShortenedDeadlineHoldsForTheFinalStoreAndForARequestReachingTheRun() {
        store.add(queued("job-00001", null, null, 0, "run"));
        executor(new ScriptedChatEngine((run, control) -> {
            control.shortenDeadline(NOW.plusSeconds(40));
            control.shortenDeadline(NOW.plusSeconds(50));
            assertEquals(Duration.ofSeconds(40), control.remaining(), "a deadline is only ever brought forward");
            var attached = executor(null).attach("job-00001", 1).orElseThrow();
            assertEquals(Duration.ofSeconds(40), attached.control().remaining(), "the MCP endpoint sees it too");
            // Verification ends past the shortened path deadline but inside the job's 45 s: completion is still refused.
            clock.advance(Duration.ofSeconds(42));
            return ScriptedChatEngine.generalAnswer("늦은 답");
        })).runOnce();

        var job = store.job("job-00001");
        assertEquals("failed", job.row.status());
        assertEquals("deadline_guard", job(job).reason());
    }

    @Test
    void aSupersededRunCannotReserveStartOrFinishToolCalls() {
        store.add(queued("job-00001", null, null, 0, "run"));
        executor(new ScriptedChatEngine((run, control) -> {
            control.reserveToolCalls(1, List.of(reservation("company.read"), reservation("issue.read")));
            control.toolCallStarted("tc-0");
            store.cancel("job-00001", clock.instant());
            assertThrows(ChatRunSuperseded.class, () -> control.toolCallFinished("tc-0",
                    new ChatToolCallEnd("succeeded", null, "v1", List.of(), false, false)));
            assertThrows(ChatRunSuperseded.class, () -> control.toolCallStarted("tc-1"));
            assertThrows(ChatRunSuperseded.class, () -> control.reserveToolCalls(2, List.of(reservation("issue.read"))));
            throw new ChatRunSuperseded();
        })).runOnce();

        assertEquals(List.of("unknown", "cancelled"),
                store.toolCalls("job-00001").stream().map(c -> c.status).toList());
    }

    private static ChatToolCallReservation web() {
        return new ChatToolCallReservation(ChatToolRegistry.VERSION, "web-search", "web.search", "app:web.search",
                "chat-tool/v1", "1".repeat(64), "{}");
    }

    private static ChatToolCallReservation reservation(String capability) {
        return new ChatToolCallReservation(ChatToolRegistry.VERSION, "zoop-core-read", capability, "app:" + capability,
                "chat-tool/v1", "0".repeat(64), "{}");
    }

    private void assertFailure(int runsBefore, ChatEngineOutcome.Failed outcome, String retry, String attemptStatus) {
        String id = "job-f" + store.jobs.size() + "000";
        store.add(withRuns(queued(id, null, null, 0, "rerun"), runsBefore));
        executor(new ScriptedChatEngine((run, control) -> {
            if (outcome.reason() != null && !"provider_error".equals(outcome.reason())) control.beforeModelCall();
            return outcome;
        })).runOnce();
        var failure = job(store.job(id));
        String expectedKind = "save_failed".equals(outcome.kind()) ? "internal" : outcome.kind();
        assertEquals(expectedKind, failure.kind(), id);
        assertEquals(retry, failure.retry(), id);
        assertFalse(failure.message().isBlank());
        assertTrue(store.job(id).row.attempts().contains("\"status\":\"" + attemptStatus + "\""), store.job(id).row.attempts());
    }

    private ChatFailure job(MemoryChatStore.Job job) {
        return mapper.readValue(job.failure, ChatFailure.class);
    }

    private ChatJobExecutor executor(ChatEngine engine) {
        var beans = new StaticListableBeanFactory(engine == null ? Map.of() : Map.of("engine", engine));
        return new ChatJobExecutor(store, store, beans.getBeanProvider(ChatEngine.class), mapper, clock,
                new NoTransactions());
    }

    private static ChatJobRow queued(String id, String resolves, String choice, int depth, String mode) {
        return queued(id, resolves, choice, depth, mode, "queued");
    }

    private static ChatJobRow queued(String id, String resolves, String choice, int depth, String mode, String status) {
        String attempts = "[{\"n\":1,\"mode\":\"" + mode + "\",\"requestKey\":\"" + id + "\",\"status\":\""
                + ("queued".equals(status) ? "queued" : "succeeded") + "\"}]";
        return new ChatJobRow(id, "conv-0001", "member-a", depth + 1, "질문 " + id, "a".repeat(64), NOW, CONTEXT, SELECTION,
                List.of(),
                null, status, null, "completed".equals(status) ? "clarification" : null, resolves, choice, depth, null, null,
                0, attempts, NOW, NOW, null);
    }

    private static ChatJobRow withAttempts(ChatJobRow r, String attempts) {
        return new ChatJobRow(r.id(), r.sessionId(), r.memberId(), r.seq(), r.question(), r.requestHash(), r.askedAt(),
                r.frozenContext(), r.frozenSelection(), r.contextCompanyIds(), r.graphVersionId(), r.status(), r.phase(),
                r.outcome(), r.resolvesJobId(), r.resolvesChoiceId(), r.clarificationDepth(), r.result(), r.failure(),
                r.runs(), attempts, r.createdAt(), r.updatedAt(), r.finishedAt());
    }

    private static ChatJobRow answered(ChatJobRow r, String result) {
        return new ChatJobRow(r.id(), r.sessionId(), r.memberId(), r.seq(), r.question(), r.requestHash(), r.askedAt(),
                r.frozenContext(), r.frozenSelection(), r.contextCompanyIds(), r.graphVersionId(), r.status(), r.phase(),
                "answered", r.resolvesJobId(), r.resolvesChoiceId(), r.clarificationDepth(), result, r.failure(), r.runs(),
                r.attempts(), r.createdAt(), r.updatedAt(), r.finishedAt());
    }

    private ChatJobRow withResult(ChatJobRow r, ChatResult result) {
        return new ChatJobRow(r.id(), r.sessionId(), r.memberId(), r.seq(), r.question(), r.requestHash(), r.askedAt(),
                r.frozenContext(), r.frozenSelection(), r.contextCompanyIds(), r.graphVersionId(), r.status(), r.phase(),
                r.outcome(), r.resolvesJobId(), r.resolvesChoiceId(), r.clarificationDepth(),
                mapper.writeValueAsString(result), r.failure(), r.runs(), r.attempts(), r.createdAt(), r.updatedAt(),
                r.finishedAt());
    }

    private static ChatJobRow withRuns(ChatJobRow r, int runs) {
        return new ChatJobRow(r.id(), r.sessionId(), r.memberId(), r.seq(), r.question(), r.requestHash(), r.askedAt(),
                r.frozenContext(), r.frozenSelection(), r.contextCompanyIds(), r.graphVersionId(), r.status(), r.phase(), r.outcome(),
                r.resolvesJobId(), r.resolvesChoiceId(), r.clarificationDepth(), r.result(), r.failure(), runs, r.attempts(),
                r.createdAt(), r.updatedAt(), r.finishedAt());
    }

    /** The memory store needs no transaction; the template still runs the callback. */
    private static final class NoTransactions extends AbstractPlatformTransactionManager {
        @Override
        protected Object doGetTransaction() {
            return new Object();
        }

        @Override
        protected void doBegin(Object transaction, TransactionDefinition definition) {
        }

        @Override
        protected void doCommit(DefaultTransactionStatus status) {
        }

        @Override
        protected void doRollback(DefaultTransactionStatus status) {
        }
    }

    private static final class MutableClock extends Clock {
        private Instant now;

        MutableClock(Instant now) {
            this.now = now;
        }

        void advance(Duration duration) {
            now = now.plus(duration);
        }

        @Override
        public ZoneId getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(ZoneId zone) {
            return this;
        }

        @Override
        public Instant instant() {
            return now;
        }
    }
}
