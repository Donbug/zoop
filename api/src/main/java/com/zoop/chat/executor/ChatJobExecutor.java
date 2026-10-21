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
import com.zoop.chat.service.FrozenSelection;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
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
 * <li>A lease that ran out is recovered as a failure. A run that had announced a model request ends as
 * {@code transient/response_unknown} without retry (the provider may have processed and charged it); one that had not ends
 * as {@code transient/deadline_guard}, which may be rerun.</li>
 * </ul>
 *
 * <p>The run deadline is the policy maximum until the orchestrator plans per-route deadlines (ZOOP-AIG-001 6.3.3); the lease
 * adds a grace period for storing the result.
 */
@Component
public class ChatJobExecutor {
    static final Duration MAX_DEADLINE = Duration.ofSeconds(60);
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
            if (checked instanceof ChatEngineOutcome.Completed completed) {
                attempt.put("status", "succeeded").put("finishedAt", now.toString());
                ChatResult result = withMessageId(completed.result(), messageId(claim.job().id()));
                String route = completed.routeSummary() == null ? null : mapper.writeValueAsString(completed.routeSummary());
                return runs.complete(claim.job().id(), claim.ownerToken(), now, result.outcome(), result.messageId(),
                        mapper.writeValueAsString(result), RESULT_SCHEMA_VERSION, route,
                        route == null ? null : ROUTE_SCHEMA_VERSION, attempts.toString());
            }
            var failed = (ChatEngineOutcome.Failed) checked;
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
            turns.addFirst(new ChatRun.Turn(at.id(), at.question(), at.resolvesChoiceId()));
            if (at.resolvesJobId() == null) break;
            String parent = at.resolvesJobId();
            at = chats.findJob(parent)
                    .orElseThrow(() -> new IllegalStateException("clarification chain is broken at " + parent));
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
