package com.zoop.chat.service;

import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.function.Supplier;

import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.chat.dto.ChatClarificationReply;
import com.zoop.chat.dto.ChatContextRequest;
import com.zoop.chat.dto.ChatConversation;
import com.zoop.chat.dto.ChatCurrentResponse;
import com.zoop.chat.dto.ChatFailure;
import com.zoop.chat.dto.ChatFrozenContext;
import com.zoop.chat.dto.ChatJob;
import com.zoop.chat.dto.ChatJobRequest;
import com.zoop.chat.dto.ChatResult;
import com.zoop.chat.dto.ChatSessionResponse;
import com.zoop.chat.repository.ChatJobRow;
import com.zoop.chat.repository.ChatRepository;
import com.zoop.chat.repository.ChatSessionRow;
import com.zoop.chat.repository.NewChatJob;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * Conversations and question jobs of a member (OpenAPI {@code aiJobs}, ERD v6 sections 22 and 23).
 *
 * <p>The first acceptance fixes the question and its context; the same job id with the same body returns the stored job and
 * with another body is {@code IDEMPOTENCY_CONFLICT}. A conversation has at most one queued or running job: every job write
 * takes the conversation row lock and the partial unique index is the last word. Reading a job or a conversation never starts
 * an execution. Accepting work that needs the executor (a new question or a retry) is refused with
 * {@code MODEL_UNAVAILABLE} while {@code zoop.chat.questions-enabled} is off, so no job waits for an engine that is not
 * deployed.
 */
@Service
public class ChatService {
    /** A clarification chain allows two clarifications from the root question (ZOOP-AIG-001 6.3.4). */
    static final int MAX_CLARIFICATION_DEPTH = 2;
    /** Model-calling executions per job (ZOOP-AIG-001 6.3.3); save_only attempts are not counted. */
    static final int MAX_RUNS = 3;

    private final ChatRepository repository;
    private final ChatContextFreezer freezer;
    private final ObjectMapper mapper;
    private final Clock clock;
    private final TransactionTemplate transaction;
    private final boolean questionsEnabled;

    public ChatService(ChatRepository repository, ChatContextFreezer freezer, ObjectMapper mapper, Clock clock,
            PlatformTransactionManager transactionManager,
            @Value("${zoop.chat.questions-enabled:false}") boolean questionsEnabled) {
        this.repository = repository;
        this.freezer = freezer;
        this.mapper = mapper;
        this.clock = clock;
        this.transaction = new TransactionTemplate(transactionManager);
        this.questionsEnabled = questionsEnabled;
    }

    /** The response and whether this call created the conversation (201) or found the member's own (200). */
    public record SessionResult(ChatSessionResponse session, boolean created) { }

    /** The job and whether this call accepted new work (202) or returned what the key already names (200). */
    public record JobResult(ChatJob job, boolean accepted) { }

    @Transactional
    public SessionResult createSession(MemberPrincipal member, String sessionId) {
        ChatJobRequest.id(sessionId);
        return data(() -> {
            Instant now = clock.instant();
            if (repository.insertSession(new ChatSessionRow(sessionId, member.memberId(), now, now))) {
                return new SessionResult(new ChatSessionResponse(sessionId, now, 0), true);
            }
            ChatSessionRow existing = owned(repository.findSession(sessionId)
                    .orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND)), member);
            return new SessionResult(sessionResponse(existing), false);
        });
    }

    @Transactional(readOnly = true)
    public ChatConversation getConversation(MemberPrincipal member, String sessionId) {
        ChatJobRequest.id(sessionId);
        return data(() -> conversation(owned(repository.findSession(sessionId)
                .orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND)), member)));
    }

    @Transactional(readOnly = true)
    public ChatCurrentResponse getCurrentConversation(MemberPrincipal member) {
        return data(() -> new ChatCurrentResponse(repository.latestSession(member.memberId())
                .map(this::conversation).orElse(null)));
    }

    /**
     * Accepts a question in three steps so that freezing, whose evidence read has its own transaction, never runs inside the
     * conversation lock: (1) ownership and an idempotent resend are answered from what is stored, without freezing again;
     * (2) a new question's context is frozen; (3) under the conversation lock the resend and the single active job are checked
     * again and the job is stored.
     */
    public JobResult submit(MemberPrincipal member, String sessionId, String idempotencyKey, ChatJobRequest request,
            String requestId) {
        ChatJobRequest.id(sessionId);
        if (!request.jobId().equals(idempotencyKey)) throw new CustomException(ErrorCode.INVALID_REQUEST);
        String requestHash = requestHash(sessionId, request);
        JobResult resent = data(() -> transaction.execute(status -> {
            owned(repository.findSession(sessionId).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND)),
                    member);
            return repository.findJob(request.jobId())
                    .map(existing -> new JobResult(view(same(existing, member, sessionId, requestHash)), false)).orElse(null);
        }));
        if (resent != null) return resent;
        if (!questionsEnabled) throw new CustomException(ErrorCode.MODEL_UNAVAILABLE);
        var frozen = request.resolves() == null ? data(() -> freezer.freeze(request.context(), requestId)) : null;

        return data(() -> transaction.execute(status -> {
            owned(repository.lockSession(sessionId).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND)),
                    member);
            var existing = repository.findJob(request.jobId());
            if (existing.isPresent()) return new JobResult(view(same(existing.get(), member, sessionId, requestHash)), false);
            if (repository.activeJob(sessionId).isPresent()) throw new CustomException(ErrorCode.JOB_IN_PROGRESS);

            String frozenContext;
            String frozenSelection;
            List<String> companyIds;
            String graphVersionId;
            int depth = 0;
            if (request.resolves() != null) {
                ChatJobRow original = clarified(member, sessionId, request.resolves());
                frozenContext = original.frozenContext();
                frozenSelection = original.frozenSelection();
                companyIds = original.contextCompanyIds();
                graphVersionId = original.graphVersionId();
                depth = original.clarificationDepth() + 1;
            } else {
                frozenContext = mapper.writeValueAsString(frozen.context());
                frozenSelection = mapper.writeValueAsString(frozen.selection());
                companyIds = frozen.companyIds();
                graphVersionId = frozen.graphVersionId();
            }

            Instant askedAt = clock.instant();
            ArrayNode attempts = StrictJson.newArray().add(attempt(1, "run", request.jobId(), askedAt));
            var job = new NewChatJob(request.jobId(), sessionId, repository.nextSeq(sessionId), request.question(),
                    requestHash, askedAt, frozenContext, frozenSelection, companyIds, graphVersionId,
                    request.resolves() == null ? null : request.resolves().jobId(),
                    request.resolves() == null ? null : request.resolves().choiceId(), depth, attempts.toString());
            if (!repository.insertJob(job)) {
                // Under the conversation lock only another conversation can have taken this id meanwhile.
                var raced = repository.findJob(request.jobId());
                if (raced.isPresent()) return new JobResult(view(same(raced.get(), member, sessionId, requestHash)), false);
                throw new CustomException(ErrorCode.JOB_IN_PROGRESS);
            }
            repository.touchSession(sessionId, askedAt);
            return new JobResult(view(repository.findJob(request.jobId()).orElseThrow()), true);
        }));
    }

    @Transactional(readOnly = true)
    public ChatJob getJob(MemberPrincipal member, String jobId) {
        ChatJobRequest.id(jobId);
        return data(() -> view(ownedJob(member, jobId)));
    }

    /** Cancels a queued or running job; a finished job is returned as it is, never shown as cancelled. */
    @Transactional
    public ChatJob cancel(MemberPrincipal member, String jobId, String idempotencyKey) {
        ChatJobRequest.id(jobId);
        requireKey(idempotencyKey);
        return data(() -> {
            ChatJobRow job = lockedJob(member, jobId);
            if (job.active()) {
                Instant now = clock.instant();
                ArrayNode attempts = attempts(job);
                for (JsonNode attempt : attempts.values()) {
                    String status = attempt.path("status").asString("");
                    if (status.equals("queued") || status.equals("running")) {
                        ((ObjectNode) attempt).put("status", "cancelled").put("finishedAt", now.toString());
                    }
                }
                if (!repository.cancel(jobId, now, attempts.toString())) throw new IllegalStateException("locked job moved");
            }
            return view(repository.findJob(jobId).orElseThrow());
        });
    }

    /** Requeues a failed job when its failure allows it ({@code ChatFailure.retry}); the same key returns the same retry. */
    @Transactional
    public JobResult retry(MemberPrincipal member, String jobId, String idempotencyKey) {
        ChatJobRequest.id(jobId);
        requireKey(idempotencyKey);
        return data(() -> {
            ChatJobRow job = lockedJob(member, jobId);
            ArrayNode attempts = attempts(job);
            for (JsonNode attempt : attempts.values()) {
                if (idempotencyKey.equals(attempt.path("requestKey").asString(null))) return new JobResult(view(job), false);
            }
            if (!questionsEnabled) throw new CustomException(ErrorCode.MODEL_UNAVAILABLE);
            if (job.active()) throw new CustomException(ErrorCode.JOB_IN_PROGRESS);
            ChatFailure failure = "failed".equals(job.status()) ? read(job.failure(), ChatFailure.class) : null;
            String mode = failure == null ? null : failure.retry();
            if (mode == null || ("rerun".equals(mode) && job.runs() >= MAX_RUNS)) {
                throw new CustomException(ErrorCode.JOB_NOT_RETRYABLE);
            }
            if (repository.activeJob(job.sessionId()).isPresent()) throw new CustomException(ErrorCode.JOB_IN_PROGRESS);

            Instant now = clock.instant();
            ObjectNode next = attempt(attempts.size() + 1, mode, idempotencyKey, now);
            if ("save_only".equals(mode)) {
                // The attempt that verified the result, also when an earlier save_only attempt failed in turn.
                JsonNode last = attempts.get(attempts.size() - 1);
                next.put("sourceAttemptNo", last.path("sourceAttemptNo").asInt(last.path("n").asInt()));
            }
            attempts.add(next);
            if (!repository.requeue(jobId, now, attempts.toString())) throw new IllegalStateException("locked job moved");
            repository.touchSession(job.sessionId(), now);
            return new JobResult(view(repository.findJob(jobId).orElseThrow()), true);
        });
    }

    /** The clarification a reply answers: same conversation, completed with outcome clarification, offering the choice. */
    private ChatJobRow clarified(MemberPrincipal member, String sessionId, ChatClarificationReply reply) {
        ChatJobRow original = repository.findJob(reply.jobId())
                .filter(job -> job.memberId().equals(member.memberId()))
                .orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
        if (!original.sessionId().equals(sessionId) || !"completed".equals(original.status())
                || !"clarification".equals(original.outcome())
                || original.clarificationDepth() + 1 > MAX_CLARIFICATION_DEPTH) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        if (reply.choiceId() != null) {
            ChatResult result = read(original.result(), ChatResult.class);
            boolean offered = result.choices() != null
                    && result.choices().stream().anyMatch(choice -> reply.choiceId().equals(choice.id()));
            if (!offered) throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        return original;
    }

    private static ChatJobRow same(ChatJobRow job, MemberPrincipal member, String sessionId, String requestHash) {
        if (!job.memberId().equals(member.memberId()) || !job.sessionId().equals(sessionId)
                || !job.requestHash().equals(requestHash)) {
            throw new CustomException(ErrorCode.IDEMPOTENCY_CONFLICT);
        }
        return job;
    }

    private ChatJobRow ownedJob(MemberPrincipal member, String jobId) {
        ChatJobRow job = repository.findJob(jobId).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
        if (!job.memberId().equals(member.memberId())) throw new CustomException(ErrorCode.ACCESS_DENIED);
        return job;
    }

    /** The job read again under its conversation lock, so its state cannot move before this transaction ends. */
    private ChatJobRow lockedJob(MemberPrincipal member, String jobId) {
        ChatJobRow job = ownedJob(member, jobId);
        repository.lockSession(job.sessionId()).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
        return repository.findJob(jobId).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
    }

    private static ChatSessionRow owned(ChatSessionRow session, MemberPrincipal member) {
        if (!session.memberId().equals(member.memberId())) throw new CustomException(ErrorCode.ACCESS_DENIED);
        return session;
    }

    private ChatConversation conversation(ChatSessionRow session) {
        List<ChatJob> jobs = repository.jobs(session.id()).stream().map(this::view).toList();
        return new ChatConversation(new ChatSessionResponse(session.id(), session.createdAt(), jobs.size()), jobs);
    }

    private ChatSessionResponse sessionResponse(ChatSessionRow session) {
        return new ChatSessionResponse(session.id(), session.createdAt(), repository.countJobs(session.id()));
    }

    private ChatJob view(ChatJobRow job) {
        return new ChatJob(job.id(), job.sessionId(), job.seq(), job.question(), job.status(), job.phase(), job.outcome(),
                job.askedAt(), read(job.frozenContext(), ChatFrozenContext.class),
                job.resolvesJobId() == null ? null : new ChatClarificationReply(job.resolvesJobId(), job.resolvesChoiceId()),
                "failed".equals(job.status()) ? read(job.failure(), ChatFailure.class) : null,
                "completed".equals(job.status()) ? read(job.result(), ChatResult.class) : null,
                job.runs(), job.createdAt(), job.updatedAt(), job.finishedAt());
    }

    private static ObjectNode attempt(int n, String mode, String requestKey, Instant queuedAt) {
        return StrictJson.newObject().put("n", n).put("mode", mode).put("requestKey", requestKey).put("status", "queued")
                .put("queuedAt", queuedAt.toString());
    }

    private ArrayNode attempts(ChatJobRow job) {
        JsonNode attempts = mapper.readTree(job.attempts());
        if (!(attempts instanceof ArrayNode array)) throw new IllegalStateException("chat_jobs.attempts is not an array");
        return array;
    }

    private <T> T read(String json, Class<T> type) {
        try {
            return mapper.readValue(Objects.requireNonNull(json, type.getSimpleName()), type);
        } catch (JacksonException stored) {
            throw new IllegalStateException("stored " + type.getSimpleName() + " cannot be read", stored);
        }
    }

    /** SHA-256 of the canonical request: what makes a resent job id "the same request" (ERD {@code request_hash}). */
    public static String requestHash(String sessionId, ChatJobRequest request) {
        ObjectNode body = StrictJson.newObject().put("sessionId", sessionId).put("question", request.question());
        ChatContextRequest context = request.context();
        if (context == null) {
            body.putNull("context");
        } else {
            ObjectNode node = body.putObject("context");
            context.contextIds().forEach(node.putArray("contextIds")::add);
            context.evidenceIds().forEach(node.putArray("evidenceIds")::add);
            if (context.period() == null) node.putNull("period");
            else node.putObject("period").put("start", context.period().start()).put("end", context.period().end());
            node.put("asOf", context.asOf() == null ? null : context.asOf().toString());
            node.put("graphVersion", context.graphVersion());
        }
        if (request.resolves() == null) body.putNull("resolves");
        else body.putObject("resolves").put("jobId", request.resolves().jobId()).put("choiceId", request.resolves().choiceId());
        return Canonical.digest(body);
    }

    private static void requireKey(String idempotencyKey) {
        if (idempotencyKey == null || idempotencyKey.isBlank()) throw new CustomException(ErrorCode.INVALID_REQUEST);
    }

    private static <T> T data(Supplier<T> work) {
        try {
            return work.get();
        } catch (DataAccessException unavailable) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, unavailable);
        }
    }
}
