package com.zoop.chat.service;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.List;

import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.chat.dto.ChatApplied;
import com.zoop.chat.dto.ChatChoice;
import com.zoop.chat.dto.ChatClarificationReply;
import com.zoop.chat.dto.ChatContextItem;
import com.zoop.chat.dto.ChatContextRequest;
import com.zoop.chat.dto.ChatFailure;
import com.zoop.chat.dto.ChatFrozenContext;
import com.zoop.chat.dto.ChatJobRequest;
import com.zoop.chat.dto.ChatResult;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.response.Metadata;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.function.Executable;
import tools.jackson.databind.ObjectMapper;

import static org.junit.jupiter.api.Assertions.*;

/** D-AI-01/01b/02: conversation ownership, idempotent acceptance, one active job, clarification replies, cancel and retry. */
class ChatServiceTest {
    private static final MemberPrincipal MEMBER = new MemberPrincipal("member-a", "session-a");
    private static final MemberPrincipal OTHER = new MemberPrincipal("member-b", "session-b");
    private static final String SESSION = "conv-0001";

    private final ObjectMapper mapper = new ObjectMapper();
    private MemoryChatRepository repository;
    private MutableClock clock;
    private ChatService service;

    @BeforeEach
    void setUp() {
        repository = new MemoryChatRepository();
        clock = new MutableClock(Instant.parse("2026-10-21T03:00:00Z"));
        service = service(true);
        service.createSession(MEMBER, SESSION);
    }

    @Test
    void conversationIsCreatedOnceAndOnlyItsOwnerCanUseIt() {
        var again = service.createSession(MEMBER, SESSION);
        assertFalse(again.created());
        assertEquals(0, again.session().jobs());
        assertTrue(service.createSession(MEMBER, "conv-0002").created());

        assertError(ErrorCode.ACCESS_DENIED, () -> service.createSession(OTHER, SESSION));
        assertError(ErrorCode.ACCESS_DENIED, () -> service.getConversation(OTHER, SESSION));
        assertError(ErrorCode.RESOURCE_NOT_FOUND, () -> service.getConversation(MEMBER, "conv-missing"));
        assertError(ErrorCode.INVALID_REQUEST, () -> service.createSession(MEMBER, "short"));
    }

    @Test
    void currentConversationIsTheLatestOneAndNullWithoutAny() {
        assertNull(service.getCurrentConversation(OTHER).conversation());
        clock.advance(Duration.ofMinutes(1));
        service.createSession(MEMBER, "conv-0002");
        assertEquals("conv-0002", service.getCurrentConversation(MEMBER).conversation().session().id());

        clock.advance(Duration.ofMinutes(1));
        service.submit(MEMBER, SESSION, "job-00001", question("job-00001", "HBM이 뭐야?"));
        var current = service.getCurrentConversation(MEMBER).conversation();
        assertEquals(SESSION, current.session().id());
        assertEquals(1, current.session().jobs());
        assertEquals("job-00001", current.jobs().getFirst().id());
    }

    @Test
    void acceptanceFreezesTheRequestOnceAndTheSameKeyReturnsTheSameJob() {
        var request = new ChatJobRequest("job-00001", "SK하이닉스 최근 이슈는?",
                new ChatContextRequest(List.of("company-sk"), List.of(), null, null, null), null);
        var accepted = service.submit(MEMBER, SESSION, "job-00001", request);
        assertTrue(accepted.accepted());
        var job = accepted.job();
        assertEquals("queued", job.status());
        assertNull(job.phase());
        assertNull(job.outcome());
        assertNull(job.result());
        assertNull(job.failure());
        assertEquals(1, job.seq());
        assertEquals(0, job.runs());
        assertEquals(clock.instant(), job.askedAt());
        assertEquals(List.of(new ChatContextItem("company-sk", "company", "company-sk")), job.context().items());
        assertEquals("gv-1", job.context().graphVersion());
        assertTrue(repository.jobs.get("job-00001").attempts().contains("\"requestKey\":\"job-00001\""));

        clock.advance(Duration.ofSeconds(5));
        var replay = service.submit(MEMBER, SESSION, "job-00001", request);
        assertFalse(replay.accepted());
        assertEquals(job, replay.job());

        assertError(ErrorCode.IDEMPOTENCY_CONFLICT, () -> service.submit(MEMBER, SESSION, "job-00001",
                question("job-00001", "다른 질문")));
        service.createSession(MEMBER, "conv-0002");
        assertError(ErrorCode.IDEMPOTENCY_CONFLICT, () -> service.submit(MEMBER, "conv-0002", "job-00001", request));
        assertError(ErrorCode.INVALID_REQUEST, () -> service.submit(MEMBER, SESSION, "other-key", request));
    }

    @Test
    void aConversationAcceptsOneActiveJobAndOnlyItsOwnerMaySubmit() {
        service.submit(MEMBER, SESSION, "job-00001", question("job-00001", "첫 질문"));
        assertError(ErrorCode.JOB_IN_PROGRESS,
                () -> service.submit(MEMBER, SESSION, "job-00002", question("job-00002", "두 번째 질문")));
        assertError(ErrorCode.ACCESS_DENIED,
                () -> service.submit(OTHER, SESSION, "job-00003", question("job-00003", "남의 대화")));
        assertError(ErrorCode.RESOURCE_NOT_FOUND,
                () -> service.submit(MEMBER, "conv-missing", "job-00004", question("job-00004", "없는 대화")));

        service.cancel(MEMBER, "job-00001", "cancel-1");
        var second = service.submit(MEMBER, SESSION, "job-00002", question("job-00002", "두 번째 질문"));
        assertEquals(2, second.job().seq());
    }

    @Test
    void newWorkIsRefusedWhileQuestionsAreDisabledButStoredJobsStayReadable() {
        service.submit(MEMBER, SESSION, "job-00001", question("job-00001", "첫 질문"));
        var disabled = service(false);

        var replay = disabled.submit(MEMBER, SESSION, "job-00001", question("job-00001", "첫 질문"));
        assertFalse(replay.accepted());
        assertEquals("queued", disabled.getJob(MEMBER, "job-00001").status());

        service.cancel(MEMBER, "job-00001", "cancel-1");
        assertError(ErrorCode.MODEL_UNAVAILABLE,
                () -> disabled.submit(MEMBER, SESSION, "job-00002", question("job-00002", "두 번째 질문")));
        assertFalse(repository.jobs.containsKey("job-00002"));
        repository.finish("job-00001", "failed", null, null, failure("rerun"), 1);
        assertError(ErrorCode.MODEL_UNAVAILABLE, () -> disabled.retry(MEMBER, "job-00001", "retry-1"));
    }

    @Test
    void clarificationReplyCopiesTheFrozenContextAndCountsTheChainDepth() {
        service.submit(MEMBER, SESSION, "job-00001", new ChatJobRequest("job-00001", "삼성 이슈 알려줘",
                new ChatContextRequest(List.of("company-x"), List.of(), null, null, null), null));
        repository.finish("job-00001", "completed", "clarification", clarification("choice-a", "choice-b"), null, 1);

        var reply = service.submit(MEMBER, SESSION, "job-00002", new ChatJobRequest("job-00002", "삼성전자", null,
                new ChatClarificationReply("job-00001", "choice-a"))).job();
        assertEquals(new ChatClarificationReply("job-00001", "choice-a"), reply.resolves());
        assertEquals(service.getJob(MEMBER, "job-00001").context(), reply.context());
        assertEquals(1, repository.jobs.get("job-00002").clarificationDepth());
        assertEquals(List.of("company-x"), repository.jobs.get("job-00002").contextCompanyIds());

        repository.finish("job-00002", "completed", "clarification", clarification("choice-c"), null, 1);
        service.submit(MEMBER, SESSION, "job-00003", new ChatJobRequest("job-00003", "SK하이닉스와 애플", null,
                new ChatClarificationReply("job-00002", null)));
        assertEquals(2, repository.jobs.get("job-00003").clarificationDepth());
    }

    @Test
    void clarificationReplyMustAnswerAnOfferedChoiceOfAClarificationInTheSameConversation() {
        service.submit(MEMBER, SESSION, "job-00001", question("job-00001", "삼성 이슈 알려줘"));
        repository.finish("job-00001", "completed", "answered", answered(), null, 1);
        assertError(ErrorCode.INVALID_REQUEST, () -> reply("job-00009", "job-00001", null));
        repository.finish("job-00001", "completed", "clarification", clarification("choice-a"), null, 1);

        assertError(ErrorCode.INVALID_REQUEST, () -> reply("job-00009", "job-00001", "choice-unknown"));
        assertError(ErrorCode.RESOURCE_NOT_FOUND, () -> reply("job-00009", "job-missing", null));
        service.createSession(MEMBER, "conv-0002");
        assertError(ErrorCode.INVALID_REQUEST, () -> service.submit(MEMBER, "conv-0002", "job-00009",
                new ChatJobRequest("job-00009", "답", null, new ChatClarificationReply("job-00001", null))));

        service.createSession(OTHER, "conv-other");
        assertError(ErrorCode.RESOURCE_NOT_FOUND, () -> service.submit(OTHER, "conv-other", "job-00009",
                new ChatJobRequest("job-00009", "답", null, new ChatClarificationReply("job-00001", null))));

        // The same clarification may be answered again; every answer is its own job.
        reply("job-00010", "job-00001", "choice-a");
        repository.finish("job-00010", "completed", "answered", answered(), null, 1);
        reply("job-00011", "job-00001", null);
        assertEquals(1, repository.jobs.get("job-00011").clarificationDepth());
    }

    @Test
    void cancelStopsAnActiveJobAndLeavesAFinishedJobAsItIs() {
        service.submit(MEMBER, SESSION, "job-00001", question("job-00001", "첫 질문"));
        assertError(ErrorCode.ACCESS_DENIED, () -> service.cancel(OTHER, "job-00001", "cancel-1"));

        clock.advance(Duration.ofSeconds(3));
        var cancelled = service.cancel(MEMBER, "job-00001", "cancel-1");
        assertEquals("cancelled", cancelled.status());
        assertEquals(clock.instant(), cancelled.finishedAt());
        assertTrue(repository.jobs.get("job-00001").attempts().contains("\"status\":\"cancelled\""));
        assertEquals(cancelled, service.cancel(MEMBER, "job-00001", "cancel-2"));

        service.submit(MEMBER, SESSION, "job-00002", question("job-00002", "두 번째 질문"));
        repository.finish("job-00002", "completed", "answered", answered(), null, 1);
        assertEquals("completed", service.cancel(MEMBER, "job-00002", "cancel-3").status());
        assertError(ErrorCode.INVALID_REQUEST, () -> service.cancel(MEMBER, "job-00002", " "));
    }

    @Test
    void retryRequeuesOnlyAnAllowedFailureAndTheSameKeyReturnsTheSameRetry() {
        service.submit(MEMBER, SESSION, "job-00001", question("job-00001", "첫 질문"));
        assertError(ErrorCode.JOB_IN_PROGRESS, () -> service.retry(MEMBER, "job-00001", "retry-0"));
        repository.finish("job-00001", "failed", null, null, failure("rerun"), 1);
        assertEquals("transient", service.getJob(MEMBER, "job-00001").failure().kind());

        var retried = service.retry(MEMBER, "job-00001", "retry-1");
        assertTrue(retried.accepted());
        assertEquals("queued", retried.job().status());
        assertNull(retried.job().failure());
        assertNull(retried.job().finishedAt());
        String attempts = repository.jobs.get("job-00001").attempts();
        assertTrue(attempts.contains("\"n\":2") && attempts.contains("\"mode\":\"rerun\""), attempts);

        var replay = service.retry(MEMBER, "job-00001", "retry-1");
        assertFalse(replay.accepted());
        assertEquals("queued", replay.job().status());

        repository.finish("job-00001", "failed", null, null, failure("rerun"), 3);
        assertError(ErrorCode.JOB_NOT_RETRYABLE, () -> service.retry(MEMBER, "job-00001", "retry-2"));
        repository.finish("job-00001", "failed", null, null, failure(null), 2);
        assertError(ErrorCode.JOB_NOT_RETRYABLE, () -> service.retry(MEMBER, "job-00001", "retry-3"));
        repository.finish("job-00001", "failed", null, null, failure("save_only"), 3);
        assertEquals("queued", service.retry(MEMBER, "job-00001", "retry-4").job().status());

        service.cancel(MEMBER, "job-00001", "cancel-1");
        assertError(ErrorCode.JOB_NOT_RETRYABLE, () -> service.retry(MEMBER, "job-00001", "retry-5"));
        assertError(ErrorCode.ACCESS_DENIED, () -> service.retry(OTHER, "job-00001", "retry-6"));
    }

    @Test
    void retryWaitsForTheConversationsActiveJob() {
        service.submit(MEMBER, SESSION, "job-00001", question("job-00001", "첫 질문"));
        repository.finish("job-00001", "failed", null, null, failure("rerun"), 1);
        service.submit(MEMBER, SESSION, "job-00002", question("job-00002", "두 번째 질문"));
        assertError(ErrorCode.JOB_IN_PROGRESS, () -> service.retry(MEMBER, "job-00001", "retry-1"));
    }

    @Test
    void readingAJobNeverChangesItAndChecksOwnership() {
        service.submit(MEMBER, SESSION, "job-00001", question("job-00001", "첫 질문"));
        var before = repository.jobs.get("job-00001");
        assertEquals("queued", service.getJob(MEMBER, "job-00001").status());
        assertEquals(before, repository.jobs.get("job-00001"));
        assertError(ErrorCode.ACCESS_DENIED, () -> service.getJob(OTHER, "job-00001"));
        assertError(ErrorCode.RESOURCE_NOT_FOUND, () -> service.getJob(MEMBER, "job-missing"));
        assertError(ErrorCode.INVALID_REQUEST, () -> service.getJob(MEMBER, "bad id!"));
    }

    @Test
    void requestHashSeparatesAnAbsentContextFromAnEmptyOneAndIgnoresNothingElse() {
        var plain = question("job-00001", "질문");
        var empty = new ChatJobRequest("job-00001", "질문", ChatContextRequest.EMPTY, null);
        assertEquals(ChatService.requestHash(SESSION, plain), ChatService.requestHash(SESSION, plain));
        assertNotEquals(ChatService.requestHash(SESSION, plain), ChatService.requestHash(SESSION, empty));
        assertNotEquals(ChatService.requestHash(SESSION, plain), ChatService.requestHash("conv-0002", plain));
        assertNotEquals(ChatService.requestHash(SESSION, empty), ChatService.requestHash(SESSION,
                new ChatJobRequest("job-00001", "질문", new ChatContextRequest(List.of(), List.of(), null,
                        Instant.parse("2026-10-20T00:00:00Z"), null), null)));
    }

    private ChatService service(boolean enabled) {
        return new ChatService(repository, new FixedFreezer(), mapper, clock, enabled);
    }

    private void reply(String jobId, String originalId, String choiceId) {
        service.submit(MEMBER, SESSION, jobId, new ChatJobRequest(jobId, "답", null,
                new ChatClarificationReply(originalId, choiceId)));
    }

    private static ChatJobRequest question(String jobId, String text) {
        return new ChatJobRequest(jobId, text, null, null);
    }

    private String clarification(String... choiceIds) {
        var choices = java.util.Arrays.stream(choiceIds).map(id -> new ChatChoice(id, id, "company")).toList();
        return mapper.writeValueAsString(result("clarification", choices));
    }

    private String answered() {
        return mapper.writeValueAsString(result("answered", List.of()));
    }

    private ChatResult result(String outcome, List<ChatChoice> choices) {
        return new ChatResult(outcome, "message-1", "", List.of(), "none", null, List.of(), List.of(), List.of(),
                new ChatApplied(List.of(), List.of(), null, "gv-1", clock.instant(), false), choices, null, List.of(),
                new Metadata("zoop", clock.instant(), "gv-1", "request-1", false, List.of()));
    }

    private String failure(String retry) {
        return mapper.writeValueAsString(new ChatFailure("transient", "provider_error", "일시적으로 처리하지 못했어요.", retry));
    }

    private static void assertError(ErrorCode expected, Executable call) {
        assertEquals(expected, assertThrows(CustomException.class, call).getErrorCode());
    }

    /** The graph lookup is the public graph read path; here every selected id is a company of version gv-1. */
    private static final class FixedFreezer extends ChatContextFreezer {
        FixedFreezer() {
            super(null, null);
        }

        @Override
        public Frozen freeze(ChatContextRequest request) {
            var ids = request == null ? List.<String>of() : request.contextIds();
            var items = ids.stream().map(id -> new ChatContextItem(id, "company", id)).toList();
            return new Frozen(new ChatFrozenContext(items, 0, request == null ? null : request.period(), null, "gv-1"),
                    ids, "gv-1");
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
