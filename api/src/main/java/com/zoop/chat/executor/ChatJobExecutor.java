package com.zoop.chat.executor;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;

import com.zoop.chat.dto.ChatFailure;
import com.zoop.chat.dto.ChatFrozenContext;
import com.zoop.chat.dto.ChatResult;
import com.zoop.chat.repository.ChatExecutionRepository;
import com.zoop.chat.repository.ChatJobRow;
import com.zoop.chat.repository.ChatRepository;
import com.zoop.chat.repository.ChatRunningJob;
import com.zoop.chat.repository.ChatToolCallEnd;
import com.zoop.chat.repository.NewChatToolCall;
import com.zoop.chat.service.FrozenSelection;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionException;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * Runs queued chat jobs (AI chatbot implementation plan, stage 1 executor and stage 2 skeleton): claims a job under a fresh
 * owner token and lease, lets the {@link ChatEngine} answer it, and stores the verified result or the failure.
 *
 * <ul>
 * <li>Claiming is {@code SKIP LOCKED}: several executors never run the same job.</li>
 * <li>Every write of a run is fenced by its owner token and unexpired lease. A cancel, an expired lease or a newer run makes
 * the old run's phase, model-call record and completion fail; its result is discarded, never stored late.</li>
 * <li>{@code runs} counts model-calling runs only: it is raised when an engine announces its first model request.</li>
 * <li>A result returned after the run deadline is never stored as completed: it ends as on lease recovery.</li>
 * <li>A lease that ran out is recovered as a failure. A run that had announced a model request ends as
 * {@code transient/response_unknown} without retry (the provider may have processed and charged it); one that had not ends
 * as {@code transient/deadline_guard}, which may be rerun.</li>
 * <li>A run's tool calls ({@code chat_tool_calls}) are reserved, started and finished under the same fence, at most
 * {@link ChatRunControl#MAX_TOOL_CALLS} per attempt. When the job ends, its calls still reserved are closed as
 * {@code cancelled} and those still running as {@code unknown}.</li>
 * </ul>
 *
 * <p>The run deadline is the policy maximum until the orchestrator plans per-route deadlines (ZOOP-AIG-001 6.3.3); the lease
 * adds a grace period for storing the result.
 */
@Component
public class ChatJobExecutor {
    /** The run deadline of every job; the agent path keeps to its own 45 s inside it (OrchestratedChatEngine.AGENT_JOB). */
    public static final Duration MAX_DEADLINE = Duration.ofSeconds(60);
    static final Duration LEASE_GRACE = Duration.ofSeconds(15);
    static final String RESULT_SCHEMA_VERSION = "chat-result/v1";
    static final String ROUTE_SCHEMA_VERSION = "chat-route/v1";
    private static final Set<String> PHASES = Set.of("planning", "retrieving", "writing", "verifying");
    private static final Set<String> OUTCOMES = Set.of("answered", "clarification", "guidance", "insufficient_evidence");
    private static final int MAX_CHOICES = 6;
    private static final int RECOVERY_BATCH = 50;
    private static final Logger log = LoggerFactory.getLogger(ChatJobExecutor.class);

    private final ChatRepository chats;
    private final ChatExecutionRepository runs;
    private final ObjectProvider<ChatEngine> engines;
    private final ObjectMapper mapper;
    private final Clock clock;
    private final TransactionTemplate transaction;

    public ChatJobExecutor(ChatRepository chats, ChatExecutionRepository runs, ObjectProvider<ChatEngine> engines,
            ObjectMapper mapper, Clock clock, PlatformTransactionManager transactionManager) {
        this.chats = chats;
        this.runs = runs;
        this.engines = engines;
        this.mapper = mapper;
        this.clock = clock;
        this.transaction = new TransactionTemplate(transactionManager);
    }

    /** A job this executor started: the run's identity within the job. */
    public record Claim(ChatJobRow job, String ownerToken, int attemptNo, String mode, Instant deadline) { }

    public boolean hasEngine() {
        return engines.getIfAvailable() != null;
    }

    /** Claims and runs the oldest queued job in the calling thread; false when there was none (or no engine). */
    public boolean runOnce() {
        Optional<Claim> claim = claimNext();
        claim.ifPresent(this::execute);
        return claim.isPresent();
    }

    /** queued → running for the oldest unclaimed job, with a new owner token, deadline and lease. */
    public Optional<Claim> claimNext() {
        if (!hasEngine()) return Optional.empty();
        return transaction.execute(status -> {
            Optional<ChatJobRow> next = runs.lockNextQueued();
            if (next.isEmpty()) return Optional.<Claim>empty();
            ChatJobRow job = next.get();
            Instant now = clock.instant();
            String token = UUID.randomUUID().toString();
            Instant deadline = now.plus(MAX_DEADLINE);
            ArrayNode attempts = attempts(job.attempts());
            ObjectNode attempt = current(attempts, "queued")
                    .orElseThrow(() -> new IllegalStateException("queued chat job without a queued attempt: " + job.id()));
            attempt.put("status", "running").put("ownerToken", token).put("startedAt", now.toString());
            if (!runs.start(job.id(), token, deadline, deadline.plus(LEASE_GRACE), attempts.toString(), now)) {
                return Optional.<Claim>empty();
            }
            return Optional.of(new Claim(job, token, attempt.path("n").asInt(), attempt.path("mode").asString(), deadline));
        });
    }

    /** Runs a claimed job to its stored end; a superseded run ends silently and changes nothing. */
    public void execute(Claim claim) {
        ChatEngine engine = engines.getIfAvailable();
        ChatEngineOutcome outcome;
        if (engine == null || "save_only".equals(claim.mode())) {
            // No recovery artifact store exists yet, so a kept verified result cannot be saved again.
            outcome = engine == null ? new ChatEngineOutcome.Failed("internal", null, false)
                    : new ChatEngineOutcome.Failed("result_lost", null, false);
        } else {
            try {
                outcome = engine.answer(run(claim), new Control(claim));
            } catch (ChatRunSuperseded superseded) {
                return;
            } catch (RuntimeException unexpected) {
                log.warn("chat engine failed for job {}", claim.job().id(), unexpected);
                outcome = new ChatEngineOutcome.Failed("internal", null, false);
            }
        }
        if (!store(claim, outcome)) {
            log.info("chat run of job {} no longer owns it; its outcome was discarded", claim.job().id());
        }
    }

    /** A run reached from outside its own thread: its frozen request and its fenced control. */
    public record Attached(ChatRun run, ChatRunControl control) { }

    /**
     * The run of a job that is running {@code attemptNo} now under an unexpired lease, for a tool request that arrives
     * outside the run's thread (the chat MCP endpoint). Empty once the job ended, was cancelled, its lease ran out or a newer
     * attempt runs. The control writes through the same owner-token fences as the run's own, so a run that ends meanwhile
     * refuses every write with {@link ChatRunSuperseded}.
     */
    public Optional<Attached> attach(String jobId, int attemptNo) {
        Optional<ChatRunningJob> running = runs.findRunning(jobId, clock.instant());
        if (running.isEmpty()) return Optional.empty();
        ChatJobRow job = running.get().job();
        Optional<ObjectNode> attempt = current(attempts(job.attempts()), "running")
                .filter(a -> a.path("n").asInt() == attemptNo
                        && running.get().ownerToken().equals(a.path("ownerToken").asString(null)));
        if (attempt.isEmpty()) return Optional.empty();
        Claim claim = new Claim(job, running.get().ownerToken(), attemptNo, attempt.get().path("mode").asString(),
                running.get().deadline());
        return Optional.of(new Attached(run(claim), new Control(claim)));
    }

    /**
     * The attempt's call still reserved for exactly this capability and input digest: a call the server approved and
     * reserved ahead (an approved MCP call) that has not started yet.
     */
    public Optional<String> reservedToolCall(String jobId, int attemptNo, String capabilityId, String inputDigest) {
        return runs.findReservedToolCall(jobId, attemptNo, capabilityId, inputDigest);
    }

    /** Ends running jobs whose lease ran out; returns how many it ended. */
    public int recoverExpired() {
        int ended = 0;
        for (String jobId : runs.expired(clock.instant(), RECOVERY_BATCH)) {
            Boolean done = transaction.execute(status -> {
                Instant now = clock.instant();
                Optional<ChatJobRow> locked = runs.lockExpired(jobId, now);
                if (locked.isEmpty()) return false;
                ChatJobRow job = locked.get();
                ArrayNode attempts = attempts(job.attempts());
                Optional<ObjectNode> attempt = current(attempts, "running");
                boolean modelCalled = attempt.map(a -> a.path("modelCalled").asBoolean(false)).orElse(true);
                ChatFailure failure = modelCalled ? ChatFailures.of("transient", "response_unknown", false, job.runs())
                        : ChatFailures.of("transient", "deadline_guard", true, job.runs());
                attempt.ifPresent(a -> a.put("status", modelCalled ? "unknown" : "failed")
                        .put("finishedAt", now.toString()));
                return runs.failExpired(jobId, now, mapper.writeValueAsString(failure), attempts.toString());
            });
            if (Boolean.TRUE.equals(done)) ended++;
        }
        return ended;
    }

    private boolean store(Claim claim, ChatEngineOutcome outcome) {
        ChatEngineOutcome checked = outcome instanceof ChatEngineOutcome.Completed completed
                ? acceptable(claim, completed.result()) ? completed : new ChatEngineOutcome.Failed("internal", null, false)
                : outcome;
        Boolean stored = transaction.execute(status -> {
            Instant now = clock.instant();
            Optional<ChatJobRow> locked = runs.lockOwned(claim.job().id(), claim.ownerToken(), now);
            if (locked.isEmpty()) return false;
            ArrayNode attempts = attempts(locked.get().attempts());
            ObjectNode attempt = attempt(attempts, claim.attemptNo());
            ChatEngineOutcome ending = late(checked, attempt, now, claim.deadline());
            if (ending instanceof ChatEngineOutcome.Completed completed) {
                attempt.put("status", "succeeded").put("finishedAt", now.toString());
                ChatResult result = withMessageId(completed.result(), messageId(claim.job().id()));
                String route = completed.routeSummary() == null ? null : mapper.writeValueAsString(completed.routeSummary());
                return runs.complete(claim.job().id(), claim.ownerToken(), now, result.outcome(), result.messageId(),
                        mapper.writeValueAsString(result), RESULT_SCHEMA_VERSION, route,
                        route == null ? null : ROUTE_SCHEMA_VERSION, attempts.toString());
            }
            var failed = (ChatEngineOutcome.Failed) ending;
            String kind = ChatFailures.ENGINE_KINDS.contains(failed.kind()) || "result_lost".equals(failed.kind())
                    ? failed.kind() : "internal";
            ChatFailure failure = ChatFailures.of(kind, failed.reason(), failed.rerunnable(), locked.get().runs());
            attempt.put("status", "response_unknown".equals(failed.reason()) ? "unknown" : "failed")
                    .put("finishedAt", now.toString());
            attempt.set("failure", mapper.valueToTree(failure));
            return runs.fail(claim.job().id(), claim.ownerToken(), now, mapper.writeValueAsString(failure),
                    attempts.toString());
        });
        return Boolean.TRUE.equals(stored);
    }

    /**
     * A result that comes back after the run deadline is not stored as completed (the deadline covers verification and
     * saving): the run ends as it would on recovery, {@code response_unknown} once a model was called, otherwise
     * {@code deadline_guard}.
     */
    private static ChatEngineOutcome late(ChatEngineOutcome outcome, ObjectNode attempt, Instant now, Instant deadline) {
        if (!(outcome instanceof ChatEngineOutcome.Completed) || !now.isAfter(deadline)) return outcome;
        return attempt.path("modelCalled").asBoolean(false)
                ? new ChatEngineOutcome.Failed("transient", "response_unknown", false)
                : new ChatEngineOutcome.Failed("transient", "deadline_guard", true);
    }

    /**
     * The structural minimum of a stored result; the content checks (citations, coverage, numbers) belong to the
     * orchestrator's output validation. A depth-2 job never stores a clarification (ZOOP-AIG-001 6.3.4).
     */
    private boolean acceptable(Claim claim, ChatResult result) {
        if (result == null || !OUTCOMES.contains(result.outcome())) return false;
        boolean clarification = "clarification".equals(result.outcome());
        boolean answered = "answered".equals(result.outcome());
        if (clarification && claim.job().clarificationDepth() >= 2) return false;
        boolean hasChoices = result.choices() != null && !result.choices().isEmpty();
        if ((!clarification && hasChoices) || (hasChoices && result.choices().size() > MAX_CHOICES)) return false;
        if (!answered && ((result.sections() != null && !result.sections().isEmpty())
                || (result.limitations() != null && !result.limitations().isEmpty()))) return false;
        return !answered || (result.sections() != null && !result.sections().isEmpty());
    }

    private ChatRun run(Claim claim) {
        ChatJobRow job = claim.job();
        List<ChatRun.Turn> turns = new ArrayList<>();
        ChatJobRow at = job;
        while (true) {
            if (at.resolvesJobId() == null) {
                turns.addFirst(new ChatRun.Turn(at.id(), at.question(), null, null));
                break;
            }
            String parentId = at.resolvesJobId();
            ChatJobRow parent = chats.findJob(parentId)
                    .orElseThrow(() -> new IllegalStateException("clarification chain is broken at " + parentId));
            turns.addFirst(new ChatRun.Turn(at.id(), at.question(), at.resolvesChoiceId(),
                    choiceLabel(parent, at.resolvesChoiceId())));
            at = parent;
        }
        return new ChatRun(job.id(), job.sessionId(), job.memberId(), claim.attemptNo(), claim.mode(), List.copyOf(turns),
                mapper.readValue(job.frozenContext(), ChatFrozenContext.class),
                mapper.readValue(job.frozenSelection(), FrozenSelection.class), job.graphVersionId(),
                job.clarificationDepth(), job.askedAt(), claim.deadline());
    }

    /** The fenced control an engine uses; every call checks that this run still owns the job. */
    private final class Control implements ChatRunControl {
        private final Claim claim;

        Control(Claim claim) {
            this.claim = claim;
        }

        @Override
        public void phase(String phase) {
            if (!PHASES.contains(phase)) throw new IllegalArgumentException("unknown chat phase: " + phase);
            if (!runs.phase(claim.job().id(), claim.ownerToken(), phase, clock.instant())) throw new ChatRunSuperseded();
        }

        @Override
        public void beforeModelCall() {
            Boolean recorded = transaction.execute(status -> {
                Instant now = clock.instant();
                Optional<ChatJobRow> locked = runs.lockOwned(claim.job().id(), claim.ownerToken(), now);
                if (locked.isEmpty()) return false;
                ArrayNode attempts = attempts(locked.get().attempts());
                ObjectNode attempt = attempt(attempts, claim.attemptNo());
                if (attempt.path("modelCalled").asBoolean(false)) return true;
                int counted = locked.get().runs() + 1;
                if (counted > ChatFailures.MAX_RUNS) throw new IllegalStateException("chat job ran out of model runs");
                attempt.put("modelCalled", true).put("modelCalledAt", now.toString());
                runs.recordModelCall(claim.job().id(), counted, attempts.toString(), now);
                return true;
            });
            if (!Boolean.TRUE.equals(recorded)) throw new ChatRunSuperseded();
        }

        @Override
        public Duration remaining() {
            return Duration.between(clock.instant(), claim.deadline());
        }

        @Override
        public boolean owned() {
            return Boolean.TRUE.equals(transaction.execute(status ->
                    runs.lockOwned(claim.job().id(), claim.ownerToken(), clock.instant()).isPresent()));
        }

        @Override
        public List<String> reserveToolCalls(int planRevision, List<ChatToolCallReservation> calls) {
            if (planRevision < 1 || calls.isEmpty()) throw new IllegalArgumentException("an empty or unnumbered tool plan");
            List<String> reserved = recorded(() -> transaction.execute(status -> {
                runs.limitWait(waitBudget());
                Instant now = clock.instant();
                if (runs.lockOwned(claim.job().id(), claim.ownerToken(), now).isEmpty()) return null;
                int first = runs.countToolCalls(claim.job().id(), claim.attemptNo());
                if (first + calls.size() > MAX_TOOL_CALLS) {
                    throw new IllegalArgumentException("tool plan exceeds " + MAX_TOOL_CALLS + " calls per attempt");
                }
                List<NewChatToolCall> rows = new ArrayList<>();
                for (int i = 0; i < calls.size(); i++) {
                    ChatToolCallReservation call = calls.get(i);
                    int index = first + i;
                    rows.add(new NewChatToolCall(UUID.randomUUID().toString(), claim.job().id(), claim.attemptNo(),
                            planRevision, index, "tc-" + index, call.registryVersion(), call.registryGroup(),
                            call.capabilityId(), call.toolId(), call.schemaVersion(), call.inputDigest(),
                            call.requestMeta()));
                }
                runs.reserveToolCalls(rows, now);
                return rows.stream().map(NewChatToolCall::toolCallId).toList();
            }));
            if (reserved == null) throw new ChatRunSuperseded();
            return reserved;
        }

        @Override
        public void toolCallStarted(String toolCallId) {
            Boolean started = recorded(() -> transaction.execute(status -> {
                runs.limitWait(waitBudget());
                return runs.startToolCall(claim.job().id(), claim.ownerToken(), claim.attemptNo(), toolCallId,
                        clock.instant());
            }));
            if (!Boolean.TRUE.equals(started)) throw new ChatRunSuperseded();
        }

        @Override
        public void toolCallFinished(String toolCallId, ChatToolCallEnd end) {
            Boolean finished = recorded(() -> transaction.execute(status -> {
                runs.limitWait(waitBudget());
                return runs.finishToolCall(claim.job().id(), claim.ownerToken(), claim.attemptNo(), toolCallId, end,
                        clock.instant());
            }));
            if (!Boolean.TRUE.equals(finished)) throw new ChatRunSuperseded();
        }

        /**
         * How long a tool-call record may wait for locks and the database: until the run's deadline. Past it, the run
         * records nothing more and ends through lease recovery.
         */
        private Duration waitBudget() {
            Duration left = Duration.between(clock.instant(), claim.deadline());
            if (left.toMillis() < 1) throw new ChatRunSuperseded();
            return left;
        }

        /** A record the database could not make in time is not made: the run cannot go on as if it were. */
        private <T> T recorded(java.util.function.Supplier<T> write) {
            try {
                return write.get();
            } catch (DataAccessException | TransactionException unrecorded) {
                log.warn("chat tool call record of job {} failed; the run stops", claim.job().id(), unrecorded);
                throw new ChatRunSuperseded();
            }
        }
    }

    /** The label the clarification showed for the picked option; null for a free-text answer. */
    private String choiceLabel(ChatJobRow clarification, String choiceId) {
        if (choiceId == null || clarification.result() == null) return null;
        ChatResult result = mapper.readValue(clarification.result(), ChatResult.class);
        return result.choices() == null ? null : result.choices().stream().filter(c -> choiceId.equals(c.id()))
                .map(c -> c.label()).findFirst().orElse(null);
    }

    static String messageId(String jobId) {
        return "msg-" + jobId;
    }

    private static ChatResult withMessageId(ChatResult r, String messageId) {
        return new ChatResult(r.outcome(), messageId, r.answer(), r.sections(), r.answerBasis(), r.reason(), r.sources(),
                r.citations(), r.graphTargets(), r.applied(), r.choices(), r.action(), r.limitations(), r.metadata());
    }

    private ArrayNode attempts(String json) {
        JsonNode node = mapper.readTree(json);
        if (!(node instanceof ArrayNode array)) throw new IllegalStateException("chat_jobs.attempts is not an array");
        return array;
    }

    /** The newest attempt, when it has the given status. */
    private static Optional<ObjectNode> current(ArrayNode attempts, String status) {
        if (attempts.isEmpty()) return Optional.empty();
        JsonNode last = attempts.get(attempts.size() - 1);
        return last instanceof ObjectNode object && status.equals(object.path("status").asString(""))
                ? Optional.of(object) : Optional.empty();
    }

    private static ObjectNode attempt(ArrayNode attempts, int n) {
        for (JsonNode attempt : attempts.values()) {
            if (attempt.path("n").asInt() == n && attempt instanceof ObjectNode object) return object;
        }
        throw new IllegalStateException("chat job attempt " + n + " is missing");
    }
}
