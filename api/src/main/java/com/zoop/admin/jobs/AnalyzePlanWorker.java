package com.zoop.admin.jobs;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicBoolean;

import com.zoop.admin.jobs.AnalyzePlanState.*;
import com.zoop.ai.*;
import com.zoop.ai.extraction.*;
import com.zoop.ai.plan.*;
import com.zoop.ai.relation.*;
import com.zoop.common.json.Canonical;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.transaction.TransactionException;

/** One bounded orchestration attempt. Every remote door is outside a repository transaction. */
public final class AnalyzePlanWorker {
    private static final Logger log = LoggerFactory.getLogger(AnalyzePlanWorker.class);
    private final JdbcAnalyzePlanRepository repository;
    private final PlanAdmissionClient admission;
    private final ExtractionClient extraction;
    private final RelationClient relation;
    private final Clock clock;
    private final AnalyzePlanProperties properties;
    private final ServiceBinding binding;
    private final Sleeper sleeper;
    private final AtomicBoolean running = new AtomicBoolean();
    private final AtomicBoolean stopping = new AtomicBoolean();

    public AnalyzePlanWorker(JdbcAnalyzePlanRepository repository, PlanAdmissionClient admission,
            ExtractionClient extraction, RelationClient relation, Clock clock, AnalyzePlanProperties properties,
            ServiceBinding binding) {
        this(repository, admission, extraction, relation, clock, properties, binding,
                duration -> Thread.sleep(duration.toMillis()));
    }

    AnalyzePlanWorker(JdbcAnalyzePlanRepository repository, PlanAdmissionClient admission,
            ExtractionClient extraction, RelationClient relation, Clock clock, AnalyzePlanProperties properties,
            ServiceBinding binding, Sleeper sleeper) {
        this.repository = repository;
        this.admission = admission;
        this.extraction = extraction;
        this.relation = relation;
        this.clock = clock;
        this.properties = properties;
        this.binding = binding;
        this.sleeper = sleeper;
    }

    @FunctionalInterface
    interface Sleeper { void sleep(Duration duration) throws InterruptedException; }

    public void stop() { stopping.set(true); }

    /** Claims no more than one job; concurrent calls in this JVM cannot consume another slot. */
    public boolean runOnce() {
        if (stopping.get() || !running.compareAndSet(false, true)) return false;
        try {
            Optional<AnalyzePlanClaim> claimed = repository.claimNext();
            if (claimed.isEmpty()) return false;
            AnalyzePlanClaim claim = claimed.get();
            try {
                advance(claim);
            } catch (Stopped ignored) {
                // Shutdown/fence loss leaves durable intents intact for the next owner.
            } catch (DataAccessException | TransactionException uncertainCommit) {
                log.warn("analyze-plan persistence unavailable; preserving owned intent");
            } catch (RuntimeException unexpected) {
                // An unclassified failure cannot prove a mutation did not happen. Never erase its intent.
                log.warn("analyze-plan interrupted by {}", unexpected.getClass().getSimpleName());
            }
            return true;
        } finally {
            running.set(false);
        }
    }

    private void advance(AnalyzePlanClaim claim) {
        int failures = 0;
        while (!stopping.get()) {
            PlanRegistration plan = owned(claim);
            boolean cancelling = plan.cancelRequested();
            Optional<StageWork> work = repository.nextStage(claim);
            if (!clock.instant().isBefore(claim.deadline())) {
                boolean unknown = unknownAtExhaustion(claim, cancelling, work);
                finish(claim, cancelling ? "cancelled" : "failed", unknown ? "outcome_unknown" : "transient",
                        unknown ? "outcome_unknown" : "worker_deadline");
                return;
            }
            try {
                if (cancelling) {
                    if (work.isEmpty()) {
                        finish(claim, "cancelled", null, null);
                        return;
                    }
                    cancelStage(claim, work.get());
                } else {
                    currentAdmission(claim, plan, true);
                    // Admission commits the complete immutable unit set; read it only after that commit.
                    work = repository.nextStage(claim);
                    if (work.isEmpty()) {
                        currentAdmission(claim, owned(claim), false);
                        requireNormal(claim);
                        finish(claim, "succeeded", null, null);
                        return;
                    }
                    advanceStage(claim, work.get());
                }
                failures = 0;
            } catch (CancelRequested cancelled) {
                // Re-read the cancel-aware ledger immediately, without waiting for lease expiry.
            } catch (CustomException conflict) {
                if (conflict.getErrorCode() != ErrorCode.REVISION_CONFLICT) throw conflict;
                finish(claim, owned(claim).cancelRequested() ? "cancelled" : "failed", "contract", "ai_binding_mismatch");
                return;
            } catch (Failure failure) {
                if (work.isPresent()) checked(repository.recordObservation(claim, work.get(),
                        StageObservation.failure(failure.category, failure.code)));
                if (!failure.retry) {
                    boolean cancellingNow = owned(claim).cancelRequested();
                    boolean unknown = cancellingNow
                            && repository.hasUnsettledIssuedWork(claim).orElseThrow(Stopped::new);
                    finish(claim, cancellingNow ? "cancelled" : "failed",
                            unknown ? "outcome_unknown" : failure.category, unknown ? "outcome_unknown" : failure.code);
                    return;
                }
                failures++;
                if (failures >= properties.maxConsecutiveFailures()) {
                    boolean cancellingNow = owned(claim).cancelRequested();
                    boolean unknown = failure.category.equals("outcome_unknown")
                            || unknownAtExhaustion(claim, cancellingNow, repository.nextStage(claim));
                    finish(claim, cancellingNow ? "cancelled" : "failed",
                            unknown ? "outcome_unknown" : failure.category, unknown ? "outcome_unknown" : failure.code);
                    return;
                }
                waitFor(claim, backoff(failures, failure.retryAfter));
            }
        }
    }

    private static boolean hasPending(Optional<StageWork> work) {
        return work.filter(value -> value.checkpoint().state().endsWith("pending")).isPresent();
    }

    private boolean unknownAtExhaustion(AnalyzePlanClaim claim, boolean cancelling, Optional<StageWork> work) {
        // Accepted WAIT/blocked work is still unresolved cancellation, even without a pending mutation name.
        return cancelling ? repository.hasUnsettledIssuedWork(claim).orElseThrow(Stopped::new) : hasPending(work);
    }

    private PlanAdmission currentAdmission(AnalyzePlanClaim claim, PlanRegistration plan, boolean allowInitial) {
        if (!binding.equals(plan.binding())) throw fail("contract", "plan_binding_mismatch");
        PlanAdmission value;
        requireNormal(claim);
        try {
            value = admission.status(plan.reference());
        } catch (AiServiceRejectionException error) {
            if (error.httpStatus() != 404 || !error.code().equals("admission_not_found")) throw remote(error, false);
            if (plan.admissionId() != null) throw fail("contract", "ai_state_missing");
            if (!allowInitial) throw fail("contract", "ai_state_missing");
            checked(repository.recordAdmissionIntent(claim));
            requireNormal(claim);
            try {
                value = admission.admit(plan.reference());
            } catch (AiClientException refused) {
                throw remote(refused, true);
            }
        } catch (AiClientException error) {
            throw remote(error, false);
        }
        if (!value.manifest().reference().equals(plan.reference())
                || !value.manifest().principal().equals(binding.expectedPrincipal())
                || value.manifest().units().isEmpty()) throw fail("contract", "plan_binding_mismatch");
        checked(repository.bindAdmission(claim, value));
        if (value.authority().state() != PlanAdmission.State.ACTIVE) {
            throw fail("authority", value.authority().reason().orElse("policy_denied"));
        }
        return value;
    }

    private void advanceStage(AnalyzePlanClaim claim, StageWork stage) {
        StageStatus status;
        try {
            status = readStatus(claim, stage);
        } catch (AiServiceRejectionException missing) {
            if (missing.httpStatus() != 404 || !missing.code().equals("job_not_found")) throw remote(missing, false);
            if (stage.checkpoint().acceptedObservedAt() != null) throw fail("contract", "ai_state_missing");
            mutate(claim, stage, StageAction.SUBMIT);
            return;
        } catch (AiClientException error) {
            throw remote(error, false);
        }
        observe(claim, stage, status);
        StateView view = view(status);
        if (unsafe(view)) throw fail("outcome_unknown", "outcome_unknown");
        switch (view.next) {
            case WAIT -> waitFor(claim, view.retryAfter.orElse(properties.pollInterval()));
            case RECOVER -> {
                if (view.dispatch != PipelineJob.DispatchState.IDLE || view.resume != PipelineJob.ResumeMode.RESUME) {
                    throw fail("contract", "ai_contract_mismatch");
                }
                if (stage.checkpoint().recoveryDispatches() >= properties.maxRecoveryDispatches()) {
                    throw fail("transient", "recovery_limit");
                }
                mutate(claim, stage, StageAction.RECOVER);
            }
            case FETCH_RESULT -> fetchResult(claim, stage, status);
            case OPERATOR_RECONCILE -> throw fail("outcome_unknown", "outcome_unknown");
            case NONE -> {
                if (view.state == PipelineJob.State.CANCELLED) throw fail("terminal", "ai_cancelled");
                throw fail("contract", "ai_contract_mismatch");
            }
        }
    }

    private StageStatus readStatus(AnalyzePlanClaim claim, StageWork stage) {
        owned(claim);
        requireBeforeDeadline(claim);
        try {
            return stage.stage() == StageKind.S2
                    ? new StageStatus(extraction.status(stage.jobId()), null)
                    : new StageStatus(null, relation.status(stage.jobId()));
        } catch (AiServiceRejectionException error) {
            Optional<StageStatus> status = embedded(error);
            if (status.isPresent()) {
                observe(claim, stage, status.get());
                if (error.code().equals("reconcile_required") || error.code().equals("live_response_unknown")) {
                    throw fail("outcome_unknown", "outcome_unknown");
                }
                return status.get();
            }
            throw error;
        }
    }

    private void mutate(AnalyzePlanClaim claim, StageWork stage, StageAction action) {
        if (action != StageAction.CANCEL) currentAdmission(claim, owned(claim), false);
        checked(repository.recordIntent(claim, stage, action));
        if (action == StageAction.CANCEL) {
            owned(claim);
            requireBeforeDeadline(claim);
        } else requireNormal(claim);
        try {
            StageStatus status;
            if (stage.stage() == StageKind.S2) {
                status = new StageStatus(switch (action) {
                    case SUBMIT -> extraction.submit(stage.extractionSubmit()).status();
                    case RECOVER -> extraction.recover(stage.jobId()).status();
                    case CANCEL -> extraction.cancel(stage.jobId());
                }, null);
            } else {
                status = new StageStatus(null, switch (action) {
                    case SUBMIT -> relation.submit(stage.relationSubmit()).status();
                    case RECOVER -> relation.recover(stage.jobId()).status();
                    case CANCEL -> relation.cancel(stage.jobId());
                });
            }
            observe(claim, stage, status);
        } catch (AiServiceRejectionException error) {
            Optional<StageStatus> embedded = embedded(error);
            if (embedded.isPresent()) observe(claim, stage, embedded.get());
            if (action == StageAction.CANCEL && error.code().equals("job_already_terminal") && embedded.isPresent()) return;
            throw remote(error, true);
        } catch (AiClientException error) {
            throw remote(error, true);
        }
    }

    private void fetchResult(AnalyzePlanClaim claim, StageWork stage, StageStatus earlier) {
        if (view(earlier).state != PipelineJob.State.READY) throw fail("contract", "ai_contract_mismatch");
        currentAdmission(claim, owned(claim), false);
        requireNormal(claim);
        try {
            StageObservation observation;
            if (stage.stage() == StageKind.S2) {
                ExtractionResult result = extraction.result(stage.jobId());
                StageStatus own = new StageStatus(result.status(), null);
                validate(stage, own, null);
                checked(repository.recordObservation(claim, stage, new StageObservation(own, null, result.receipts(), null, null)));
                validateDeliverable(view(own), result.delivery());
                UntrustedExtractionPayload payload = result.readyPayload().orElseThrow(() -> fail("authority", "result_withheld"));
                if (!payload.jobId().equals(stage.jobId()) || !payload.inputDigest().equals(stage.extractionInputDigest())) {
                    throw fail("contract", "ai_binding_mismatch");
                }
                observation = new StageObservation(own, Canonical.sha256(payload.untrustedJson()), result.receipts(), null, null);
            } else {
                RelationResult result = relation.result(stage.jobId());
                StageStatus own = new StageStatus(null, result.status());
                // The prior status pin was committed before this HTTP request, never inferred from the payload.
                validate(stage, own, earlier.relation().inputDigest());
                checked(repository.recordObservation(claim, stage, new StageObservation(own, null, result.receipts(), null, null)));
                validateDeliverable(view(own), result.delivery());
                UntrustedRelationPayload payload = result.readyPayload().orElseThrow(() -> fail("authority", "result_withheld"));
                if (!payload.jobId().equals(stage.jobId()) || !payload.inputDigest().equals(result.status().inputDigest())) {
                    throw fail("contract", "ai_binding_mismatch");
                }
                observation = new StageObservation(own, Canonical.sha256(payload.untrustedJson()), result.receipts(), null, null);
            }
            checked(repository.recordObservation(claim, stage, observation));
        } catch (AiServiceRejectionException error) {
            embedded(error).ifPresent(status -> observe(claim, stage, status));
            throw remote(error, false);
        } catch (AiClientException error) {
            throw remote(error, false);
        }
    }

    private static void validateDeliverable(StateView own, PipelineJob.Delivery delivery) {
        if (unsafe(own)) throw fail("outcome_unknown", "outcome_unknown");
        if (own.state != PipelineJob.State.READY || own.next != PipelineJob.Next.FETCH_RESULT) {
            throw fail("contract", "ai_contract_mismatch");
        }
        if (own.delivery.state() != PipelineJob.DeliveryState.AVAILABLE
                || delivery.state() != PipelineJob.DeliveryState.AVAILABLE) throw fail("authority", "result_withheld");
    }

    private void cancelStage(AnalyzePlanClaim claim, StageWork stage) {
        StageStatus status;
        try {
            status = readStatus(claim, stage);
        } catch (AiServiceRejectionException error) {
            embedded(error).ifPresent(value -> observe(claim, stage, value));
            if (error.httpStatus() == 404 && error.code().equals("job_not_found")) {
                if (stage.checkpoint().acceptedObservedAt() != null) throw fail("contract", "ai_state_missing");
                throw new Failure("outcome_unknown", "outcome_unknown", true, Optional.empty());
            }
            throw remote(error, false);
        } catch (AiClientException error) {
            throw remote(error, false);
        }
        observe(claim, stage, status);
        StateView value = view(status);
        if (unsafe(value)) throw fail("outcome_unknown", "outcome_unknown");
        if (value.state == PipelineJob.State.READY || value.state == PipelineJob.State.CANCELLED) return;
        mutate(claim, stage, StageAction.CANCEL);
        waitFor(claim, properties.pollInterval());
    }

    private void observe(AnalyzePlanClaim claim, StageWork stage, StageStatus status) {
        validate(stage, status, null);
        checked(repository.recordObservation(claim, stage,
                new StageObservation(status, null, null, null, null)));
    }

    static void validate(StageWork stage, StageStatus status, String pinnedDigest) {
        if (stage.stage() == StageKind.S2) {
            ExtractionJobStatus value = status.extraction();
            if (value == null || !value.jobId().equals(stage.jobId())
                    || !value.inputDigest().equals(stage.extractionInputDigest())
                    || !value.approvedRequestDigest().equals(stage.extractionSubmit().approvedRequestDigest())
                    || value.sourceKind() != stage.relationSubmit().sourceKind()
                    || value.executionMode() != stage.extractionSubmit().executionMode()) {
                throw fail("contract", "ai_binding_mismatch");
            }
        } else {
            RelationJobStatus value = status.relation();
            String digest = stage.s3InputDigest() != null ? stage.s3InputDigest() : pinnedDigest;
            if (value == null || !value.jobId().equals(stage.jobId())
                    || (digest != null && !digest.equals(value.inputDigest()))
                    || !value.upstream().equals(stage.relationSubmit().upstream())
                    || value.sourceKind() != stage.relationSubmit().sourceKind()
                    || value.executionMode() != stage.relationSubmit().executionMode()) {
                throw fail("contract", "ai_binding_mismatch");
            }
            PipelineJob.requireDigest("inputDigest", value.inputDigest());
        }
    }

    private static Optional<StageStatus> embedded(AiServiceRejectionException error) {
        if (error instanceof ExtractionServiceErrorException s2) return s2.status().map(value -> new StageStatus(value, null));
        if (error instanceof RelationServiceErrorException s3) return s3.status().map(value -> new StageStatus(null, value));
        return Optional.empty();
    }

    private static StateView view(StageStatus status) {
        if (status.extraction() != null) {
            var value = status.extraction();
            return new StateView(value.state(), value.resumeMode(), value.next(), value.dispatch().state(),
                    value.usage().startedWithoutReceipt(), value.failure(), value.delivery(), value.retryAfter());
        }
        var value = status.relation();
        return new StateView(value.state(), value.resumeMode(), value.next(), value.dispatch().state(),
                value.usage().startedWithoutReceipt(), value.failure(), value.delivery(), value.retryAfter());
    }

    private record StateView(PipelineJob.State state, PipelineJob.ResumeMode resume, PipelineJob.Next next,
            PipelineJob.DispatchState dispatch, long startedWithoutReceipt, Optional<PipelineJob.Failure> failure,
            PipelineJob.Delivery delivery, Optional<Duration> retryAfter) {}

    private static boolean unsafe(StateView value) {
        return value.startedWithoutReceipt > 0 || value.resume == PipelineJob.ResumeMode.RECONCILE_ONLY
                || value.next == PipelineJob.Next.OPERATOR_RECONCILE
                || value.failure.map(PipelineJob.Failure::code)
                        .filter(code -> code.equals("live_response_unknown") || code.equals("reconcile_required")).isPresent();
    }

    private static Failure remote(AiClientException error, boolean mutation) {
        if (mutation && error.requestMaybeProcessed()) {
            return new Failure("outcome_unknown", "outcome_unknown", true, retryAfter(error));
        }
        if (error instanceof AiTransportException transport
                && (transport.failure() == AiTransportException.Failure.RESPONSE_MALFORMED
                    || transport.failure() == AiTransportException.Failure.RESPONSE_TOO_LARGE
                    || transport.failure() == AiTransportException.Failure.REDIRECT_REFUSED
                    || transport.failure() == AiTransportException.Failure.UNEXPECTED_RESPONSE)) {
            return fail("contract", "ai_contract_mismatch");
        }
        if (error instanceof AiServiceRejectionException service) {
            if (service.code().equals("reconcile_required") || service.code().equals("live_response_unknown")) {
                return fail("outcome_unknown", "outcome_unknown");
            }
            if (service.retryable() || service.httpStatus() >= 500 || service.httpStatus() == 429) {
                return new Failure("transient", "ai_status_unavailable", true, service.retryAfter());
            }
            if (service.code().contains("binding") || service.code().contains("conflict")) {
                return fail("contract", "ai_binding_mismatch");
            }
            return fail("authority", safeCode(service.code()));
        }
        return new Failure("transient", "ai_status_unavailable", true, Optional.empty());
    }

    private static Optional<Duration> retryAfter(AiClientException error) {
        return error instanceof AiServiceRejectionException service ? service.retryAfter() : Optional.empty();
    }

    private static String safeCode(String code) {
        return code != null && code.matches("[a-z][a-z0-9_]{0,79}") ? code : "ai_contract_mismatch";
    }

    private Duration backoff(int failures, Optional<Duration> advised) {
        Duration bounded = Duration.ofSeconds(Math.min(30, 1L << Math.min(failures, 5)));
        return advised.filter(value -> value.compareTo(bounded) > 0).orElse(bounded);
    }

    private void waitFor(AnalyzePlanClaim claim, Duration requested) {
        Duration remaining = Duration.between(clock.instant(), claim.deadline());
        if (remaining.isNegative() || remaining.isZero()) return;
        Duration wait = requested.compareTo(remaining) > 0 ? remaining : requested;
        if (wait.isNegative() || wait.isZero()) wait = properties.pollInterval().compareTo(remaining) > 0
                ? remaining : properties.pollInterval();
        Instant until = clock.instant().plus(wait);
        checked(repository.defer(claim, until));
        while (clock.instant().isBefore(until)) {
            owned(claim);
            Duration slice = Duration.between(clock.instant(), until);
            Duration heartbeat = properties.lease().dividedBy(3);
            if (slice.compareTo(heartbeat) > 0) slice = heartbeat;
            try {
                sleeper.sleep(slice);
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                throw new Stopped();
            }
        }
    }

    private PlanRegistration owned(AnalyzePlanClaim claim) {
        if (stopping.get()) throw new Stopped();
        checked(repository.renew(claim));
        return repository.loadPlan(claim).orElseThrow(Stopped::new);
    }

    private void requireNormal(AnalyzePlanClaim claim) {
        if (owned(claim).cancelRequested()) throw new CancelRequested();
        requireBeforeDeadline(claim);
    }

    private void requireBeforeDeadline(AnalyzePlanClaim claim) {
        if (!clock.instant().isBefore(claim.deadline())) {
            boolean unknown = unknownAtExhaustion(claim, owned(claim).cancelRequested(), repository.nextStage(claim));
            throw fail(unknown ? "outcome_unknown" : "transient", unknown ? "outcome_unknown" : "worker_deadline");
        }
    }

    private void finish(AnalyzePlanClaim claim, String status, String category, String code) {
        owned(claim);
        checked(repository.finish(claim, new AnalyzePlanTerminal(status, category, code)));
    }

    private static void checked(boolean value) { if (!value) throw new Stopped(); }
    private static Failure fail(String category, String code) { return new Failure(category, code, false, Optional.empty()); }
    private static final class Stopped extends RuntimeException {}
    private static final class CancelRequested extends RuntimeException {}
    private static final class Failure extends RuntimeException {
        final String category;
        final String code;
        final boolean retry;
        final Optional<Duration> retryAfter;
        Failure(String category, String code, boolean retry, Optional<Duration> retryAfter) {
            this.category = category;
            this.code = code;
            this.retry = retry;
            this.retryAfter = retryAfter;
        }
    }
}
