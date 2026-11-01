package com.zoop.graph.round;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;

import com.zoop.ai.AiClientException;
import com.zoop.ai.AiServiceRejectionException;
import com.zoop.ai.AiTransportException;
import com.zoop.ai.round.RoundHandoffClient;
import com.zoop.ai.round.RoundHandoffClient.RoundHandoff;
import com.zoop.ai.round.RoundRunClient;
import com.zoop.ai.round.RoundRunClient.RoundRun;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.document.bindings.DocumentBindingsException;
import com.zoop.document.bindings.DocumentBindingsFailure;
import com.zoop.graph.round.GraphRoundClock.Slot;
import com.zoop.graph.round.GraphRoundEvent.Outcome;
import com.zoop.graph.round.RoundAnalysisQueue.JobStatus;
import com.zoop.graph.round.RoundAnalysisQueue.Queued;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.JsonNodeFactory;
import tools.jackson.databind.node.ObjectNode;

/**
 * One pass of the periodic round (design {@code plan-55-round-scheduler.md} §2, #387 contract of 2026-10-30): open the slots
 * that came due, then take every open round oldest first and move it as far as it goes without waiting. Each stage is one
 * attempt against an external party, recorded on the row and its timeline; the row is the only state (a restart continues from
 * it) and every write is fenced on the lease this pass claimed.
 * <ul>
 * <li>R1 {@code scheduled} → {@code POST round-runs} → {@code run_requested} (a freeze-only slot goes to {@code analysis_done}
 *     at once, code {@code freeze_only})</li>
 * <li>R2 {@code run_requested} → {@code GET round-runs/{id}}: {@code ready} → {@code plan_ready} with the plan and the AI
 *     ingestion round; {@code no_new_material} → {@code analysis_done} (a carry-only freeze still follows, #407 app change
 *     2); {@code failed} → {@code failed(run_failed:<code>)}</li>
 * <li>R3 {@code plan_ready} → the analyze_plan job under the system actor → {@code analysis_queued}; a queue that stays
 *     unavailable past the attempt bound fails with {@code analysis_queue_timeout} (resuming here)</li>
 * <li>R4 {@code analysis_queued} → the job's state: succeeded → {@code analysis_done}; failed/cancelled/missing →
 *     {@code failed(analysis_failed:<code>)} resuming at {@code plan_ready} (a retry queues the job's retry, never reads the
 *     finished job again); the wait is bounded by {@code analysis-wait-deadline} and its {@code analysis_timeout} resumes
 *     here</li>
 * <li>R5 {@code analysis_done} → {@code POST round-handoffs} with the plan (if any), the ingestion round (if any) and the app's
 *     bindings (every registered version) → {@code freeze_requested}</li>
 * <li>R6 {@code freeze_requested} → {@code GET round-handoffs/{id}}: {@code ready} → {@code handoff_ready} with the pins;
 *     {@code no_public_material} → {@code skipped}; {@code analysis_incomplete} → wait; {@code failed} →
 *     {@code failed(freeze_failed:<code>)}</li>
 * <li>R7 {@code handoff_ready} → {@link GraphRoundImportBridge#importRound}</li>
 * </ul>
 * A 409 {@code round_busy} and every 5xx or transport failure make the round wait ({@code wait-retry-after}, or the service's
 * {@code Retry-After} up to {@code busy-retry-after}); past {@code max-attempts-per-stage} the round fails with
 * {@code <stage>_timeout}. Every other 4xx is a refusal that ends the round ({@code run_refused:<code>},
 * {@code plan_rejected:<code>}, {@code freeze_refused:<code>}). A failure event carries {@code failedAt}, the stage the retry
 * resumes at. Nothing here decides, approves or publishes: the AI side chooses the window, the importer verifies, the
 * auto-activation publishes.
 */
public final class GraphRoundWorker {
    private static final Logger log = LoggerFactory.getLogger(GraphRoundWorker.class);
    public static final String SYSTEM = "system:scheduler";
    static final String FREEZE_ONLY = "freeze_only";
    static final String NO_NEW_MATERIAL = "no_new_material";
    static final String NO_PUBLIC_MATERIAL = "no_public_material";
    /** How many stage changes one pass makes on one round before the next round gets its turn. */
    static final int MAX_STEPS_PER_PASS = 8;

    private final GraphRoundRepository rounds;
    private final GraphRoundClock calendar;
    private final RoundRunClient runs;
    private final RoundHandoffClient handoffs;
    private final RoundAnalysisQueue analysis;
    private final RoundBindingsSource bindings;
    private final GraphRoundImportBridge bridge;
    private final GraphRoundProperties properties;
    private final Clock clock;
    private final String owner;
    private final JsonNodeFactory nodes = JsonNodeFactory.instance;
    private volatile Instant opened;
    private volatile Instant lastTick;

    public GraphRoundWorker(GraphRoundRepository rounds, GraphRoundClock calendar, RoundRunClient runs,
            RoundHandoffClient handoffs, RoundAnalysisQueue analysis, RoundBindingsSource bindings, GraphRoundImportBridge bridge,
            GraphRoundProperties properties, Clock clock, String owner) {
        this.rounds = rounds;
        this.calendar = calendar;
        this.runs = runs;
        this.handoffs = handoffs;
        this.analysis = analysis;
        this.bindings = bindings;
        this.bridge = bridge;
        this.properties = properties;
        this.clock = clock;
        this.owner = owner;
    }

    public Optional<Instant> lastTick() {
        return Optional.ofNullable(lastTick);
    }

    /** One pass; never throws, so the fixed-delay schedule keeps going. */
    public void runOnce() {
        Instant now = clock.instant();
        lastTick = now;
        try {
            openSlots(now);
        } catch (RuntimeException unavailable) {
            log.warn("graph round: could not open the due slots ({})", unavailable.getClass().getSimpleName());
        }
        List<GraphRound> due;
        try {
            due = rounds.due(now, properties.maxOpenRounds());
        } catch (RuntimeException unavailable) {
            log.warn("graph round: could not read the due rounds ({})", unavailable.getClass().getSimpleName());
            return;
        }
        for (GraphRound round : due) {
            Optional<GraphRound> claimed;
            try {
                claimed = rounds.claim(round.roundId(), owner, properties.lease(), clock.instant());
            } catch (RuntimeException unavailable) {
                log.warn("graph round {}: could not claim ({})", round.roundId(), unavailable.getClass().getSimpleName());
                continue;
            }
            claimed.ifPresent(this::progress);
        }
    }

    /** Rows for the slots that came due since the last pass (or within {@code lookback} at the first one). */
    void openSlots(Instant now) {
        Instant from = opened != null ? opened : now.minus(properties.lookback());
        for (Slot slot : calendar.slotsBetween(from, now)) {
            if (rounds.findBySlot(slot.slotAt()).isEmpty()) {
                rounds.create(slot.roundId(), slot.slotAt(), SYSTEM, now);
                log.info("graph round {} opened (slot {}{})", slot.roundId(), slot.slotAt(), slot.freezeOnly() ? ", freeze only" : "");
            }
        }
        opened = now;
    }

    /** Moves one claimed round until it waits or ends. The row returned by each step is the row the next step works on. */
    void progress(GraphRound claimed) {
        GraphRound round = claimed;
        for (int steps = 0; steps < MAX_STEPS_PER_PASS && round.open(); steps++) {
            if (round.lease().isEmpty() || !owner.equals(round.lease().get().owner())) return; // taken over meanwhile
            GraphRound next;
            try {
                next = step(round);
            } catch (RuntimeException unexpected) {
                // Nothing of the row is lost: the stage was not changed, and the next pass tries the same step again.
                log.warn("graph round {} at {}: step interrupted by {}", round.roundId(), round.stage().wire(),
                        unexpected.getClass().getSimpleName());
                return;
            }
            boolean moved = next.stage() != round.stage();
            round = next;
            if (!moved) return;
        }
    }

    GraphRound step(GraphRound round) {
        return switch (round.stage()) {
            case SCHEDULED -> calendar.freezeOnly(round.slotAt())
                    ? record(round, GraphRoundPatch.advanceTo(GraphRoundStage.ANALYSIS_DONE), Outcome.ADVANCED, FREEZE_ONLY, null)
                    : requestRun(round);
            case RUN_REQUESTED -> readRun(round);
            case PLAN_READY -> queueAnalysis(round);
            case ANALYSIS_QUEUED -> readAnalysis(round);
            case ANALYSIS_DONE -> requestFreeze(round);
            case FREEZE_REQUESTED -> readFreeze(round);
            case HANDOFF_READY -> renew(round).map(bridge::importRound).orElseGet(() -> current(round));
            case IMPORTED, SKIPPED, FAILED -> round;
        };
    }

    // ------------------------------------------------------------------------------------------------ R1 · R2

    private GraphRound requestRun(GraphRound round) {
        try {
            return applyRun(round, runs.request(round.roundId()));
        } catch (AiClientException failure) {
            return aiFailure(round, failure, "run_refused", "run_timeout");
        }
    }

    private GraphRound readRun(GraphRound round) {
        try {
            return applyRun(round, runs.runStatus(round.roundId()));
        } catch (AiClientException failure) {
            return aiFailure(round, failure, "run_refused", "run_timeout");
        }
    }

    private GraphRound applyRun(GraphRound round, RoundRun run) {
        ObjectNode detail = nodes.objectNode();
        run.ingestionRoundId().ifPresent(id -> detail.put("ingestionRoundId", id));
        run.code().ifPresent(code -> detail.put("code", code));
        return switch (run.state()) {
            case RUNNING -> round.stage() == GraphRoundStage.SCHEDULED
                    ? record(round, GraphRoundPatch.advanceTo(GraphRoundStage.RUN_REQUESTED), Outcome.ADVANCED, null, detail)
                    : wait(round, "run_running", detail, properties.waitRetryAfter(), "run_timeout");
            case READY -> {
                detail.put("planId", run.planId().orElseThrow());
                detail.put("planDigest", run.planDigest().orElseThrow());
                yield record(round, GraphRoundPatch.advanceTo(GraphRoundStage.PLAN_READY)
                        .plan(run.planId().orElseThrow(), run.planDigest().orElseThrow())
                        .ingestionRound(run.ingestionRoundId().orElseThrow()), Outcome.ADVANCED, "plan_ready", detail);
            }
            case NO_NEW_MATERIAL -> record(round, GraphRoundPatch.advanceTo(GraphRoundStage.ANALYSIS_DONE)
                    .ingestionRound(run.ingestionRoundId().orElse(null)), Outcome.ADVANCED, NO_NEW_MATERIAL, detail);
            case FAILED -> fail(round, "run_failed:" + run.code().orElse("unknown"), detail);
        };
    }

    // ------------------------------------------------------------------------------------------------ R3 · R4

    private GraphRound queueAnalysis(GraphRound round) {
        String planId = round.planId().orElseThrow(() -> new IllegalStateException("plan_ready without a plan"));
        String planDigest = round.planDigest().orElseThrow();
        ObjectNode detail = nodes.objectNode();
        detail.put("planId", planId);
        try {
            Queued queued = analysis.queue(planId, planDigest, round.roundId(), round.roundId());
            detail.put("jobId", queued.jobId());
            return record(round, GraphRoundPatch.advanceTo(GraphRoundStage.ANALYSIS_QUEUED).analysisJob(queued.jobId()),
                    Outcome.ADVANCED, queued.reused() ? "analysis_job_reused" : "analysis_queued", detail);
        } catch (CustomException refused) {
            ErrorCode code = refused.getErrorCode();
            if (code == ErrorCode.SOURCE_UNAVAILABLE || code == ErrorCode.MODEL_UNAVAILABLE) {
                return wait(round, "analysis_queue_unavailable", detail, properties.waitRetryAfter(), "analysis_queue_timeout");
            }
            return fail(round, "plan_rejected:" + code.name().toLowerCase(Locale.ROOT), detail);
        } catch (RuntimeException unexpected) {
            // Counted like any other wait, so a repeatable error ends in analysis_queue_timeout instead of a silent loop. The
            // code differs from R4's analysis_timeout: this round has no job yet, so a retry resumes here, at plan_ready.
            detail.put("error", unexpected.getClass().getSimpleName());
            return wait(round, "analysis_queue_error", detail, properties.waitRetryAfter(), "analysis_queue_timeout");
        }
    }

    private GraphRound readAnalysis(GraphRound round) {
        String jobId = round.analysisJobId().orElseThrow(() -> new IllegalStateException("analysis_queued without a job"));
        ObjectNode detail = nodes.objectNode();
        detail.put("jobId", jobId);
        JobStatus status;
        try {
            status = analysis.status(jobId);
        } catch (RuntimeException unavailable) {
            return waitBounded(round, "analysis_status_unavailable", detail, properties.waitRetryAfter(), "analysis_timeout",
                    analysisAttempts());
        }
        status.code().ifPresent(code -> detail.put("code", code));
        return switch (status.state()) {
            case SUCCEEDED -> record(round, GraphRoundPatch.advanceTo(GraphRoundStage.ANALYSIS_DONE), Outcome.ADVANCED,
                    "analysis_done", detail);
            // A finished or vanished job is not read again: a retry resumes at plan_ready, where queueAnalysis follows the job's
            // retry chain (or opens a new job) under the system actor. Only the wait for a still-running job resumes here.
            case FAILED, CANCELLED -> fail(round, "analysis_failed" + status.code().map(code -> ":" + code).orElse(""), detail,
                    GraphRoundStage.PLAN_READY);
            case MISSING -> fail(round, "analysis_failed:job_missing", detail, GraphRoundStage.PLAN_READY);
            case QUEUED, RUNNING -> waitBounded(round, "analysis_running", detail, properties.waitRetryAfter(), "analysis_timeout",
                    analysisAttempts());
        };
    }

    /** The R4 bound in attempts: the deadline divided by the wait, at least one. */
    int analysisAttempts() {
        long attempts = properties.analysisWaitDeadline().toMillis() / Math.max(1, properties.waitRetryAfter().toMillis());
        return (int) Math.max(1, Math.min(Integer.MAX_VALUE, attempts));
    }

    // ------------------------------------------------------------------------------------------------ R5 · R6

    private GraphRound requestFreeze(GraphRound round) {
        ObjectNode detail = nodes.objectNode();
        round.planId().ifPresent(id -> detail.put("planId", id));
        round.ingestionRoundId().ifPresent(id -> detail.put("ingestionRoundId", id));
        byte[] exported;
        try {
            exported = bindings.export();
        } catch (DocumentBindingsException failure) {
            detail.put("bindings", failure.failure().code());
            if (failure.failure() == DocumentBindingsFailure.DATABASE_UNAVAILABLE) {
                return wait(round, "bindings_unavailable", detail, properties.waitRetryAfter(), "freeze_timeout");
            }
            return fail(round, "bindings_failed:" + failure.failure().code(), detail);
        } catch (RuntimeException unexpected) {
            detail.put("error", unexpected.getClass().getSimpleName());
            return wait(round, "bindings_error", detail, properties.waitRetryAfter(), "freeze_timeout");
        }
        detail.put("bindingsBytes", exported.length);
        try {
            return applyHandoff(round, handoffs.request(new RoundHandoffClient.Request(round.roundId(), round.ingestionRoundId(),
                    round.planId(), exported)), detail);
        } catch (AiClientException failure) {
            return aiFailure(round, failure, "freeze_refused", "freeze_timeout");
        }
    }

    private GraphRound readFreeze(GraphRound round) {
        try {
            return applyHandoff(round, handoffs.handoffStatus(round.roundId()), nodes.objectNode());
        } catch (AiClientException failure) {
            return aiFailure(round, failure, "freeze_refused", "freeze_timeout");
        }
    }

    private GraphRound applyHandoff(GraphRound round, RoundHandoff handoff, ObjectNode detail) {
        handoff.code().ifPresent(code -> detail.put("code", code));
        return switch (handoff.state()) {
            case RUNNING -> round.stage() == GraphRoundStage.ANALYSIS_DONE
                    ? record(round, GraphRoundPatch.advanceTo(GraphRoundStage.FREEZE_REQUESTED), Outcome.ADVANCED, null, detail)
                    : wait(round, "freeze_running", detail, properties.waitRetryAfter(), "freeze_timeout");
            case READY -> {
                handoff.selection().ifPresent(selection -> detail.set("selection", selectionCounts(selection)));
                detail.put("handoffId", handoff.handoffId().orElseThrow());
                yield record(round, GraphRoundPatch.advanceTo(GraphRoundStage.HANDOFF_READY).handoff(handoff.handoffId().orElseThrow(),
                        handoff.manifestDigest().orElseThrow(), handoff.bundleDigest().orElseThrow()), Outcome.ADVANCED,
                        "handoff_ready", detail);
            }
            case ANALYSIS_INCOMPLETE -> wait(round, "analysis_incomplete", detail, properties.waitRetryAfter(), "freeze_timeout");
            case NO_PUBLIC_MATERIAL -> record(round, GraphRoundPatch.advanceTo(GraphRoundStage.SKIPPED), Outcome.SKIPPED,
                    NO_PUBLIC_MATERIAL, detail);
            case FAILED -> fail(round, "freeze_failed:" + handoff.code().orElse("unknown"), detail);
        };
    }

    /** The producer's selection report reduced to how many jobs each status holds; the report itself is not stored. */
    static ObjectNode selectionCounts(JsonNode selection) {
        ObjectNode counts = JsonNodeFactory.instance.objectNode();
        JsonNode jobs = selection.get("jobs");
        if (jobs == null || !jobs.isArray()) return counts;
        Map<String, Integer> byStatus = new HashMap<>();
        for (JsonNode job : jobs) {
            JsonNode status = job.get("status");
            if (status != null && status.isString()) byStatus.merge(status.stringValue(), 1, Integer::sum);
        }
        byStatus.keySet().stream().sorted().forEach(status -> counts.put(status, byStatus.get(status)));
        return counts;
    }

    // ------------------------------------------------------------------------------------------------ outcomes

    /**
     * A busy, rate-limited, retryable or unavailable AI side makes the round wait (the service's {@code Retry-After} up to
     * {@code busy-retry-after}); any other refusal ends it with the service's code.
     */
    private GraphRound aiFailure(GraphRound round, AiClientException failure, String refusedPrefix, String timeoutCode) {
        ObjectNode detail = nodes.objectNode();
        detail.put("requestId", failure.requestId());
        if (failure instanceof AiServiceRejectionException rejection) {
            detail.put("httpStatus", rejection.httpStatus());
            detail.put("code", rejection.code());
            boolean busy = rejection.httpStatus() == 409 && "round_busy".equals(rejection.code());
            if (busy || rejection.httpStatus() >= 500 || rejection.httpStatus() == 429 || rejection.retryable()) {
                Duration after = rejection.retryAfter().filter(d -> d.compareTo(properties.busyRetryAfter()) <= 0)
                        .orElse(busy ? properties.busyRetryAfter() : properties.waitRetryAfter());
                return wait(round, "ai:" + rejection.code(), detail, after, timeoutCode);
            }
            return fail(round, refusedPrefix + ":" + rejection.code(), detail);
        }
        AiTransportException transport = (AiTransportException) failure;
        detail.put("transport", transport.failure().name().toLowerCase(Locale.ROOT));
        return wait(round, "transport:" + transport.failure().name().toLowerCase(Locale.ROOT), detail, properties.waitRetryAfter(),
                timeoutCode);
    }

    private GraphRound wait(GraphRound round, String code, ObjectNode detail, Duration retryAfter, String timeoutCode) {
        return waitBounded(round, code, detail, retryAfter, timeoutCode, properties.maxAttemptsPerStage());
    }

    private GraphRound waitBounded(GraphRound round, String code, ObjectNode detail, Duration retryAfter, String timeoutCode,
            int maxAttempts) {
        if (round.attempts() + 1 >= maxAttempts) {
            detail.put("attempts", round.attempts() + 1);
            return fail(round, timeoutCode, detail);
        }
        Instant next = clock.instant().plus(retryAfter);
        return record(round, GraphRoundPatch.waitAt(round.stage(), next), Outcome.WAITING, code, detail);
    }

    private GraphRound fail(GraphRound round, String code, ObjectNode detail) {
        return fail(round, code, detail, round.stage());
    }

    /** {@code resumeAt}: the open stage a retry of this failure resumes at (the failure event's {@code failedAt}). */
    private GraphRound fail(GraphRound round, String code, ObjectNode detail, GraphRoundStage resumeAt) {
        ObjectNode written = detail == null ? nodes.objectNode() : detail;
        written.put("failedAt", resumeAt.wire());
        log.warn("graph round {} failed at {}: {}", round.roundId(), round.stage().wire(), code);
        return record(round, GraphRoundPatch.fail(code), Outcome.FAILED, code, written);
    }

    /**
     * Fenced on the lease this step started under: the lease is extended first ({@link #renew}) and the write carries its
     * token. When the extension fails this run lost the row (another holder took it, or took it and finished) and the step's
     * result is dropped; the row is returned as it is now and {@link #progress} stops.
     */
    private GraphRound record(GraphRound round, GraphRoundPatch patch, Outcome outcome, String code, ObjectNode detail) {
        return renew(round)
                .map(held -> rounds.advance(held, patch, outcome, code, null, detail, clock.instant()).orElseGet(() -> lost(round)))
                .orElseGet(() -> lost(round));
    }

    /**
     * The lease extended for its holder before a write or an import ({@link GraphRoundRepository#extend}): the row must still
     * carry this step's owner and token at this step's stage. A lease that merely expired while the call was in flight, with
     * nobody taking the row, is extended with its token kept, so a long call does not lose its result; a row another holder
     * took (a new token) or moved is not, and nothing is written over what happened meanwhile.
     */
    private Optional<GraphRound> renew(GraphRound round) {
        return rounds.extend(round, properties.lease(), clock.instant());
    }

    private GraphRound lost(GraphRound round) {
        log.warn("graph round {}: the lease was lost at {}; this step's result is dropped", round.roundId(), round.stage().wire());
        return current(round);
    }

    /** The row as it is now, whoever holds it. */
    private GraphRound current(GraphRound round) {
        return rounds.find(round.roundId()).orElse(round);
    }
}
