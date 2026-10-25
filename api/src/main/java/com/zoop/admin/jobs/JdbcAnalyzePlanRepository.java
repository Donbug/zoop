package com.zoop.admin.jobs;

import static com.zoop.admin.jobs.AnalyzePlanState.*;

import com.zoop.admin.jobs.AnalysisJobResponse.PlanRunOut;
import com.zoop.ai.ExecutionMode;
import com.zoop.ai.PipelineJob;
import com.zoop.ai.extraction.ExtractionSubmission;
import com.zoop.ai.plan.PlanAdmission;
import com.zoop.ai.plan.PlanManifest;
import com.zoop.ai.plan.PlanReference;
import com.zoop.ai.relation.RelationSubmission;
import com.zoop.ai.relation.RelationUpstream;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.function.Function;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/** Short DB transactions only. Lock order is execution advisory lock -> app job -> plan -> unit. */
@Repository
public class JdbcAnalyzePlanRepository {
    private final NamedParameterJdbcTemplate jdbc;
    private final ObjectMapper mapper;
    private final TransactionTemplate tx;
    private final Clock clock;
    private final Duration lease;
    private final Duration deadline;
    private final int maxReclaims;
    private final int maxRecoveryDispatches;

    public JdbcAnalyzePlanRepository(NamedParameterJdbcTemplate jdbc, ObjectMapper mapper,
            PlatformTransactionManager transactions, Clock clock, AnalyzePlanProperties properties) {
        this.jdbc = jdbc;
        this.mapper = mapper;
        this.tx = new TransactionTemplate(transactions);
        this.clock = clock;
        this.lease = properties.lease();
        this.deadline = properties.attemptDeadline();
        this.maxReclaims = properties.maxReclaims();
        this.maxRecoveryDispatches = properties.maxRecoveryDispatches();
    }

    public void executionLock() {
        jdbc.queryForObject("SELECT pg_advisory_xact_lock(hashtextextended('zoop-analysis-admin-execution-v1',0))",
                new MapSqlParameterSource(), Object.class);
    }

    /** Only serializes create/dedup; never taken by workers, and never followed by an existing job row lock. */
    public void registrationLock(String planId) {
        jdbc.queryForObject("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))",
                new MapSqlParameterSource("key", "zoop-analysis-plan-registration-v1:" + planId), Object.class);
    }

    public PlanRegistration register(PlanReference reference, ServiceBinding binding, String adminId, Instant at) {
        jdbc.update("""
                INSERT INTO analysis_plans(plan_id,plan_digest,service_binding,expected_principal,registered_at,registered_by)
                VALUES(:plan,:digest,:binding,:principal,:at,:admin) ON CONFLICT(plan_id) DO NOTHING
                """, params(reference.planId()).addValue("digest", reference.planDigest()).addValue("binding", binding.digest())
                .addValue("principal", binding.expectedPrincipal()).addValue("at", stamp(at)).addValue("admin", adminId));
        PlanRegistration saved = registration(reference.planId(), false).orElseThrow();
        if (!saved.reference().equals(reference) || !saved.binding().equals(binding)) {
            throw new CustomException(ErrorCode.REVISION_CONFLICT);
        }
        return saved;
    }

    public Optional<AnalyzePlanClaim> claimNext() {
        return tx.execute(ignored -> {
            executionLock();
            List<Job> running = jdbc.query("SELECT * FROM analysis_jobs WHERE scope='admin' AND status='running' FOR UPDATE",
                    this::job);
            Job chosen;
            boolean reclaimed = !running.isEmpty();
            if (reclaimed) {
                chosen = running.getFirst();
                if (!"analyze_plan".equals(chosen.kind()) || chosen.leaseUntil() == null
                        || chosen.leaseUntil().isAfter(clock.instant())) return Optional.empty();
            } else {
                var queued = jdbc.query("""
                        SELECT * FROM analysis_jobs WHERE scope='admin' AND kind='analyze_plan' AND status='queued'
                        AND NOT cancel_requested AND (next_attempt_at IS NULL OR next_attempt_at <= clock_timestamp())
                        ORDER BY requested_at,id LIMIT 1 FOR UPDATE
                        """, this::job);
                if (queued.isEmpty()) return Optional.empty();
                chosen = queued.getFirst();
            }
            Instant now = clock.instant(); // AFTER all row waits, never transaction-start now().
            var attempts = mapper.readTree(chosen.attempts());
            int number = attempts.size() + 1;
            Instant until = now.plus(lease);
            Instant ends = reclaimed && !attempts.isEmpty()
                    ? Instant.parse(attempts.get(0).get("deadline").stringValue()) : now.plus(deadline);
            if (reclaimed && !attempts.isEmpty()) {
                ObjectNode previous = (ObjectNode) attempts.get(attempts.size() - 1);
                previous.put("status", "failed");
                previous.put("finishedAt", now.toString());
                previous.put("failureCode", "lease_expired");
            }
            String token = UUID.randomUUID().toString();
            ObjectNode entry = mapper.createObjectNode();
            entry.put("attemptNo", number); entry.put("ownerToken", token); entry.put("claimedAt", now.toString());
            entry.put("deadline", ends.toString()); entry.put("reclaimed", reclaimed);
            entry.put("status", "running");
            entry.set("recoveryDispatches", mapper.createObjectNode());
            ((tools.jackson.databind.node.ArrayNode) attempts).add(entry);
            jdbc.update("""
                    UPDATE analysis_jobs SET status='running', started_at=COALESCE(started_at,:at),
                    owner_token=:token,lease_until=:until,recovered=recovered OR :reclaimed,attempts=CAST(:attempts AS jsonb)
                    WHERE id=:id
                    """, new MapSqlParameterSource("id", chosen.id()).addValue("at", stamp(now)).addValue("token", token)
                    .addValue("until", stamp(until)).addValue("reclaimed", reclaimed)
                    .addValue("attempts", mapper.writeValueAsString(attempts)));
            var claim = new AnalyzePlanClaim(chosen.id(), chosen.planId(), token, number, ends, until);
            if (reclaimed && number > maxReclaims + 1) {
                Optional<Boolean> unresolved = hasUnsettledIssuedWork(claim);
                if (unresolved.isEmpty()) return Optional.empty();
                boolean unknown = unresolved.get();
                finishLocked(claim, new AnalyzePlanTerminal(chosen.cancelRequested() ? "cancelled" : "failed",
                        unknown ? "outcome_unknown" : "transient",
                        unknown ? "outcome_unknown" : "worker_reclaim_limit"), clock.instant());
                return Optional.empty();
            }
            return Optional.of(claim);
        });
    }

    public boolean renew(AnalyzePlanClaim claim) {
        return fenced(claim, true, j -> {
            jdbc.update("UPDATE analysis_jobs SET lease_until=:until WHERE id=:id",
                    new MapSqlParameterSource("id", claim.appJobId()).addValue("until", stamp(clock.instant().plus(lease))));
            return true;
        });
    }

    public Optional<PlanRegistration> loadPlan(AnalyzePlanClaim claim) {
        return tx.execute(ignored -> {
            Job j = lock(claim, true);
            return j == null ? Optional.empty() : registration(claim.planId(), j.cancelRequested());
        });
    }

    /** A cancellation or exhausted owner must account for all issued work, not merely the cursor's checkpoint name. */
    public Optional<Boolean> hasUnsettledIssuedWork(AnalyzePlanClaim claim) {
        return tx.execute(ignored -> {
            Job job = lock(claim, true);
            if (job == null) return Optional.empty();
            Boolean unsettled = jdbc.queryForObject("""
                    SELECT (p.admission_intent_at IS NOT NULL AND p.admission_id IS NULL)
                        OR EXISTS(SELECT 1 FROM analysis_plan_units u WHERE u.plan_id=p.plan_id AND (
                    """ + unsettledStage("u.s2_checkpoint") + " OR " + unsettledStage("u.s3_checkpoint") + """
                    )) FROM analysis_plans p WHERE p.plan_id=:plan
                    """, params(claim.planId()), Boolean.class);
            return job.leaseUntil().isAfter(clock.instant()) ? Optional.of(Boolean.TRUE.equals(unsettled)) : Optional.empty();
        });
    }

    public boolean recordAdmissionIntent(AnalyzePlanClaim claim) {
        return fenced(claim, false, j -> {
            jdbc.update("UPDATE analysis_plans SET admission_intent_at=COALESCE(admission_intent_at,:at) WHERE plan_id=:plan",
                    params(claim.planId()).addValue("at", stamp(clock.instant())));
            cursor(claim.appJobId(), "admitting", null, null);
            return true;
        });
    }

    public boolean bindAdmission(AnalyzePlanClaim claim, PlanAdmission admission) {
        return fenced(claim, true, j -> {
            PlanRegistration p = registration(claim.planId(), j.cancelRequested()).orElseThrow();
            PlanManifest m = admission.manifest();
            if (!p.reference().equals(m.reference()) || !p.binding().expectedPrincipal().equals(m.principal()) || m.units().isEmpty()) {
                throw new CustomException(ErrorCode.REVISION_CONFLICT);
            }
            String manifest = mapper.writeValueAsString(manifest(m));
            List<String> existing = jdbc.query("SELECT manifest::text FROM analysis_plans WHERE plan_id=:plan FOR UPDATE",
                    params(claim.planId()), (rs, n) -> rs.getString(1));
            if (p.admissionId() != null) {
                if (!p.admissionId().equals(admission.admissionId()) || !p.acceptedAt().equals(admission.acceptedAt())
                        || p.policyRevision() != admission.policyRevision() || !p.policyDigest().equals(admission.policyDigest())
                        || !mapper.readTree(existing.getFirst()).equals(mapper.readTree(manifest))) {
                    throw new CustomException(ErrorCode.REVISION_CONFLICT);
                }
            } else {
                jdbc.update("""
                        UPDATE analysis_plans SET admission_id=:admission,accepted_at=:accepted,policy_revision=:revision,
                        policy_digest=:policy,receipt_sha256=:receipt,manifest_digest=:digest,manifest=CAST(:manifest AS jsonb)
                        WHERE plan_id=:plan
                        """, params(claim.planId()).addValue("admission", admission.admissionId())
                        .addValue("accepted", stamp(admission.acceptedAt())).addValue("revision", admission.policyRevision())
                        .addValue("policy", admission.policyDigest()).addValue("receipt", m.receiptSha256())
                        .addValue("digest", m.manifestDigest()).addValue("manifest", manifest));
                int ordinal = 0;
                for (PlanManifest.Unit u : m.units()) {
                    jdbc.update("""
                            INSERT INTO analysis_plan_units(plan_id,ordinal,unit_key,s2_job_id,s2_approved_request_digest,
                            s2_input_digest,s3_job_id,s2_submit,s3_submit,s2_checkpoint,s3_checkpoint)
                            VALUES(:plan,:ordinal,:key,:key,:approved,:input,:s3,CAST(:s2submit AS jsonb),CAST(:s3submit AS jsonb),
                            CAST(:checkpoint AS jsonb),CAST(:checkpoint AS jsonb))
                            """, params(claim.planId()).addValue("ordinal", ++ordinal).addValue("key", u.unitKey())
                            .addValue("approved", u.extractionSubmit().approvedRequestDigest()).addValue("input", u.extractionInputDigest())
                            .addValue("s3", u.relationSubmit().jobId()).addValue("s2submit", mapper.writeValueAsString(extraction(u.extractionSubmit())))
                            .addValue("s3submit", mapper.writeValueAsString(relation(u.relationSubmit())))
                            .addValue("checkpoint", mapper.writeValueAsString(StageCheckpoint.initial())));
                }
            }
            jdbc.update("""
                    UPDATE analysis_plans SET last_authority_state=:state,last_authority_reason=:reason,
                    authority_observed_at=:at,last_admission_code=NULL WHERE plan_id=:plan
                    """, params(claim.planId()).addValue("state", admission.authority().state().name().toLowerCase(java.util.Locale.ROOT))
                    .addValue("reason", admission.authority().reason().orElse(null)).addValue("at", stamp(clock.instant())));
            return true;
        });
    }

    public Optional<StageWork> nextStage(AnalyzePlanClaim claim) {
        return tx.execute(ignored -> {
            Job j = lock(claim, true);
            if (j == null) return Optional.empty();
            String s2Unsettled = unsettledStage("s2_checkpoint");
            String condition = j.cancelRequested()
                    ? "(" + s2Unsettled + " OR " + unsettledStage("s3_checkpoint") + ")"
                    : "s3_checkpoint->>'state' <> 'result_observed'";
            return jdbc.query("""
                    SELECT u.*,p.manifest->'provenance' AS provenance,
                    """ + s2Unsettled + """ 
                    AS s2_unsettled FROM analysis_plan_units u
                    JOIN analysis_plans p USING(plan_id) WHERE u.plan_id=:plan AND
                    """ + condition + " ORDER BY ordinal LIMIT 1", params(claim.planId()), (rs, n) -> {
                        StageCheckpoint s2 = mapper.readValue(rs.getString("s2_checkpoint"), StageCheckpoint.class);
                        StageCheckpoint s3 = mapper.readValue(rs.getString("s3_checkpoint"), StageCheckpoint.class);
                        StageKind stage = j.cancelRequested()
                                ? rs.getBoolean("s2_unsettled") ? StageKind.S2 : StageKind.S3
                                : "result_observed".equals(s2.state()) ? StageKind.S3 : StageKind.S2;
                        JsonNode provenance = mapper.readTree(rs.getString("provenance"));
                        ExecutionMode mode = ExecutionMode.valueOf(provenance.get("executionMode").stringValue().toUpperCase(java.util.Locale.ROOT));
                        var source = PipelineJob.SourceKind.valueOf(provenance.get("sourceKind").stringValue().toUpperCase(java.util.Locale.ROOT));
                        var s2submit = new ExtractionSubmission(rs.getString("s2_job_id"),rs.getString("s2_approved_request_digest"),mode);
                        var s3submit = new RelationSubmission(rs.getString("s3_job_id"),source,mode,
                                new RelationUpstream(rs.getString("s2_job_id"),rs.getString("s2_input_digest")));
                        StageCheckpoint saved = stage == StageKind.S2 ? s2 : s3;
                        String stageJobId = stage == StageKind.S2 ? s2submit.jobId() : s3submit.jobId();
                        StageCheckpoint current = new StageCheckpoint(saved.schemaVersion(), saved.state(), saved.intentAt(),
                                saved.acceptedObservedAt(), saved.lastStatus(), saved.resultObservedAt(),
                                saved.resultContentSha256(), saved.receipts(), saved.failureCategory(), saved.failureCode(),
                                saved.consecutiveFailures(), recoveryCount(j.attempts(), stageJobId));
                        return new StageWork(claim.planId(),rs.getInt("ordinal"),stage,s2submit,s3submit,
                                rs.getString("s2_input_digest"),rs.getString("s3_input_digest"),current);
                    }).stream().findFirst();
        });
    }

    public boolean recordIntent(AnalyzePlanClaim claim, StageWork stage, StageAction action) {
        return fenced(claim, action == StageAction.CANCEL, j -> {
            StageCheckpoint old = lockedStage(claim, stage);
            if (old == null || "result_observed".equals(old.state())) return false;
            int recoveries = recoveryCount(j.attempts(), stage.jobId());
            if (action == StageAction.RECOVER) {
                if (recoveries >= maxRecoveryDispatches) return false;
                var attempts = (tools.jackson.databind.node.ArrayNode) mapper.readTree(j.attempts());
                var latest = (ObjectNode) attempts.get(attempts.size()-1);
                var counts = (ObjectNode) latest.get("recoveryDispatches");
                int local = counts.has(stage.jobId()) ? counts.get(stage.jobId()).intValue() : 0;
                counts.put(stage.jobId(), local + 1);
                jdbc.update("UPDATE analysis_jobs SET attempts=CAST(:attempts AS jsonb) WHERE id=:id",
                        new MapSqlParameterSource("id",claim.appJobId()).addValue("attempts",mapper.writeValueAsString(attempts)));
                recoveries++;
            }
            StageCheckpoint changed = new StageCheckpoint(old.schemaVersion(), action == StageAction.CANCEL ? "cancel_pending" : "submit_pending",
                    clock.instant(),old.acceptedObservedAt(),old.lastStatus(),old.resultObservedAt(),old.resultContentSha256(),
                    old.receipts(),null,null,old.consecutiveFailures(),recoveries);
            writeStage(stage, changed, null);
            cursor(claim.appJobId(), action == StageAction.CANCEL ? "cancelling" : stage.stage()==StageKind.S2 ? "extracting" : "relating",stage.ordinal(),null);
            return true;
        });
    }

    public boolean recordObservation(AnalyzePlanClaim claim, StageWork stage, StageObservation observation) {
        return fenced(claim, true, j -> {
            StageCheckpoint old = lockedStage(claim, stage);
            if (old == null) return false;
            String pin = validateObservation(stage, observation);
            if (pin != null && old.lastStatus() != null && old.lastStatus().relation() != null
                    && !pin.equals(old.lastStatus().relation().inputDigest())) {
                throw new CustomException(ErrorCode.REVISION_CONFLICT);
            }
            if ("result_observed".equals(old.state())) {
                if (observation.resultContentSha256() != null
                        && !observation.resultContentSha256().equals(old.resultContentSha256())) {
                    throw new CustomException(ErrorCode.REVISION_CONFLICT);
                }
                return true;
            }
            Instant now = clock.instant();
            boolean accepted = observation.status() != null;
            boolean result = observation.resultContentSha256() != null;
            boolean cancelled = accepted && state(observation.status()) == PipelineJob.State.CANCELLED;
            var changed = new StageCheckpoint(old.schemaVersion(), result ? "result_observed" : cancelled ? "cancelled"
                    : observation.failureCode() != null ? ("submit_pending".equals(old.state()) || "cancel_pending".equals(old.state())
                            ? old.state() : "blocked") : accepted ? "accepted" : old.state(),
                    old.intentAt(), old.acceptedObservedAt() != null ? old.acceptedObservedAt() : accepted ? now : null,
                    accepted ? observation.status() : old.lastStatus(),result ? now : null,observation.resultContentSha256(),
                    observation.receipts() != null ? List.copyOf(observation.receipts()) : old.receipts(),observation.failureCategory(),observation.failureCode(),
                    observation.failureCode() == null ? 0 : old.consecutiveFailures()+1,old.recoveryDispatches());
            writeStage(stage, changed, pin);
            cursor(claim.appJobId(), j.cancelRequested() ? "cancelling"
                    : stage.stage() == StageKind.S2 ? "extracting" : "relating", stage.ordinal(), observation.failureCategory());
            return true;
        });
    }

    public boolean defer(AnalyzePlanClaim claim, Instant nextAttemptAt) {
        return fenced(claim, true, j -> {
            if (nextAttemptAt.isAfter(claim.deadline())) return false;
            jdbc.update("UPDATE analysis_jobs SET next_attempt_at=:at WHERE id=:id",
                    new MapSqlParameterSource("id",claim.appJobId()).addValue("at",stamp(nextAttemptAt)));
            return true;
        });
    }

    public boolean finish(AnalyzePlanClaim claim, AnalyzePlanTerminal outcome) {
        return fenced(claim, !"succeeded".equals(outcome.status()), j -> {
            if (j.cancelRequested() && !"cancelled".equals(outcome.status())) return false;
            return finishLocked(claim,outcome,clock.instant());
        });
    }

    public void cancelQueued(String appJobId, Instant at) {
        PlanRunOut summary = summary(appJobId,"cancelled");
        jdbc.update("""
                UPDATE analysis_jobs SET status='cancelled',cancel_requested=true,finished_at=:at,
                checkpoint=jsonb_build_object('schemaVersion','zoop-app-analyze-plan-checkpoint-1','phase','cancelled',
                'activeOrdinal',NULL,'terminalSummary',CAST(:summary AS jsonb),'lastFailureCategory',NULL)
                WHERE id=:id AND kind='analyze_plan' AND scope='admin' AND status='queued'
                """, new MapSqlParameterSource("id",appJobId).addValue("at",stamp(at)).addValue("summary",mapper.writeValueAsString(summary)));
    }

    public PlanRunOut summary(String appJobId, String phaseOverride) {
        return jdbc.query("""
                SELECT j.checkpoint,p.plan_id,p.plan_digest,p.admission_id,p.manifest_digest,
                  p.manifest->'round'->>'sourceId' AS source_id,p.manifest->'round'->>'roundId' AS round_id,
                  CASE WHEN p.admission_id IS NULL THEN NULL ELSE jsonb_array_length(p.manifest->'units') END AS total,
                  (SELECT count(*) FROM analysis_plan_units u WHERE u.plan_id=p.plan_id
                   AND u.s2_checkpoint->>'state'='result_observed' AND u.s3_checkpoint->>'state'='result_observed') AS ready
                FROM analysis_jobs j JOIN analysis_plans p USING(plan_id) WHERE j.id=:id AND j.scope='admin'
                """,new MapSqlParameterSource("id",appJobId),(rs,n)-> {
                    JsonNode checkpoint=mapper.readTree(rs.getString("checkpoint"));
                    if (phaseOverride==null && checkpoint.hasNonNull("terminalSummary")) {
                        return mapper.treeToValue(checkpoint.get("terminalSummary"),PlanRunOut.class);
                    }
                    Integer total=(Integer)rs.getObject("total");
                    Integer active=checkpoint.hasNonNull("activeOrdinal")?checkpoint.get("activeOrdinal").intValue():null;
                    return new PlanRunOut(rs.getString("plan_id"),rs.getString("plan_digest"),rs.getString("admission_id"),
                            rs.getString("manifest_digest"),rs.getString("source_id"),rs.getString("round_id"),
                            phaseOverride==null?checkpoint.get("phase").stringValue():phaseOverride,total,rs.getInt("ready"),active,
                            "ai_processing_handoff",false);
                }).stream().findFirst().orElseThrow();
    }

    public String retryBarrier(String planId) {
        var registration = registration(planId, false);
        if (registration.isEmpty()) return "dataset_missing";
        Boolean unknown = jdbc.queryForObject("""
                SELECT EXISTS(SELECT 1 FROM analysis_plan_units WHERE plan_id=:plan AND (
                    s2_checkpoint->>'failureCategory'='outcome_unknown' OR s3_checkpoint->>'failureCategory'='outcome_unknown'))
                """, params(planId), Boolean.class);
        if (Boolean.TRUE.equals(unknown)) return "outcome_unknown";
        if ("inactive".equals(registration.get().authorityState())) return "plan_not_reusable";
        if (registration.get().admissionId() != null) {
            // A stage can observe permanent grant retirement after the last successful admission-status read.
            Boolean retired = jdbc.queryForObject("""
                    SELECT EXISTS(SELECT 1 FROM analysis_plan_units WHERE plan_id=:plan AND (
                        (s2_checkpoint->>'failureCategory'='authority'
                         AND s2_checkpoint->>'failureCode' IN ('policy_disabled','policy_expired','policy_replaced'))
                        OR (s3_checkpoint->>'failureCategory'='authority'
                         AND s3_checkpoint->>'failureCode' IN ('policy_disabled','policy_expired','policy_replaced'))))
                    """, params(planId), Boolean.class);
            if (Boolean.TRUE.equals(retired)) return "plan_not_reusable";
        }
        Boolean cancelled = jdbc.queryForObject("""
                SELECT EXISTS(SELECT 1 FROM analysis_plan_units WHERE plan_id=:plan AND (
                    s2_checkpoint->>'state'='cancelled' OR s3_checkpoint->>'state'='cancelled'))
                """, params(planId), Boolean.class);
        return Boolean.TRUE.equals(cancelled) ? "plan_not_reusable" : null;
    }

    public List<ReadyUnitReference> readyUnits(String planId,int afterOrdinal,int limit) {
        if(limit<1 || limit>1000 || afterOrdinal<0) throw new IllegalArgumentException("bounded page required");
        return jdbc.query("""
                SELECT u.*,p.plan_digest,p.admission_id,p.manifest_digest,p.manifest->'provenance' AS provenance
                FROM analysis_plan_units u JOIN analysis_plans p USING(plan_id)
                WHERE u.plan_id=:plan AND ordinal>:after
                AND s2_checkpoint->>'state'='result_observed' AND s3_checkpoint->>'state'='result_observed'
                ORDER BY ordinal LIMIT :limit
                """, params(planId).addValue("after", afterOrdinal).addValue("limit", limit), (rs, n) -> {
                    JsonNode s2 = mapper.readTree(rs.getString("s2_checkpoint"));
                    JsonNode s3 = mapper.readTree(rs.getString("s3_checkpoint"));
                    JsonNode provenance = mapper.readTree(rs.getString("provenance"));
                    return new ReadyUnitReference(planId, rs.getString("plan_digest"), rs.getString("admission_id"),
                            rs.getString("manifest_digest"), rs.getInt("ordinal"), rs.getString("unit_key"),
                            rs.getString("s2_job_id"), rs.getString("s2_input_digest"), rs.getString("s3_job_id"),
                            rs.getString("s3_input_digest"),
                            PipelineJob.SourceKind.valueOf(provenance.get("sourceKind").stringValue().toUpperCase(java.util.Locale.ROOT)),
                            ExecutionMode.valueOf(provenance.get("executionMode").stringValue().toUpperCase(java.util.Locale.ROOT)),
                            Instant.parse(s2.get("resultObservedAt").stringValue()), Instant.parse(s3.get("resultObservedAt").stringValue()),
                            s2.get("resultContentSha256").stringValue(), s3.get("resultContentSha256").stringValue());
                });
    }

    private boolean fenced(AnalyzePlanClaim claim, boolean cancellation, Function<Job, Boolean> action) {
        return Boolean.TRUE.equals(tx.execute(transaction -> {
            Job job = lock(claim, cancellation);
            if (job == null) return false;
            boolean result = action.apply(job);
            if (!job.leaseUntil().isAfter(clock.instant())) {
                transaction.setRollbackOnly();
                return false;
            }
            return result;
        }));
    }
    private Job lock(AnalyzePlanClaim claim,boolean cancellation) {
        var jobs=jdbc.query("SELECT * FROM analysis_jobs WHERE id=:id AND scope='admin' AND kind='analyze_plan' FOR UPDATE",
                new MapSqlParameterSource("id",claim.appJobId()),this::job);
        if(jobs.isEmpty()) return null;
        Job j=jobs.getFirst();
        Instant now=clock.instant();
        if(!"running".equals(j.status()) || !claim.planId().equals(j.planId()) || !claim.ownerToken().equals(j.ownerToken())
                || j.leaseUntil()==null || !j.leaseUntil().isAfter(now) || (!cancellation && j.cancelRequested())) return null;
        jdbc.query("SELECT plan_id FROM analysis_plans WHERE plan_id=:plan FOR UPDATE",params(claim.planId()),(rs,n)->rs.getString(1));
        // A plan lock can also wait. Recheck real time after every lock wait, not PostgreSQL transaction-start time.
        return j.leaseUntil().isAfter(clock.instant())?j:null;
    }
    private StageCheckpoint lockedStage(AnalyzePlanClaim claim,StageWork stage) {
        if(!claim.planId().equals(stage.planId())) return null;
        var values=jdbc.query("SELECT * FROM analysis_plan_units WHERE plan_id=:plan AND ordinal=:ordinal FOR UPDATE",
                params(claim.planId()).addValue("ordinal",stage.ordinal()),(rs,n)-> {
                    if (!rs.getString("s2_job_id").equals(stage.extractionSubmit().jobId())
                            || !rs.getString("s3_job_id").equals(stage.relationSubmit().jobId())
                            || !rs.getString("s2_input_digest").equals(stage.extractionInputDigest())
                            || !rs.getString("s2_approved_request_digest").equals(stage.extractionSubmit().approvedRequestDigest())
                            || !mapper.readTree(rs.getString("s2_submit")).equals(extraction(stage.extractionSubmit()))
                            || !mapper.readTree(rs.getString("s3_submit")).equals(relation(stage.relationSubmit()))) return null;
                    if (stage.stage() == StageKind.S3 && !"result_observed".equals(
                            mapper.readTree(rs.getString("s2_checkpoint")).get("state").stringValue())) return null;
                    return mapper.readValue(rs.getString(stage.stage()==StageKind.S2?"s2_checkpoint":"s3_checkpoint"),StageCheckpoint.class);
                });
        // Parent is locked, but unit locks may have waited past its lease.
        Boolean valid=jdbc.queryForObject("SELECT lease_until > :at FROM analysis_jobs WHERE id=:id AND owner_token=:token",
                new MapSqlParameterSource("at",stamp(clock.instant())).addValue("id",claim.appJobId()).addValue("token",claim.ownerToken()),Boolean.class);
        return Boolean.TRUE.equals(valid)&&!values.isEmpty()?values.getFirst():null;
    }
    private void writeStage(StageWork stage,StageCheckpoint checkpoint,String pin) {
        String column=stage.stage()==StageKind.S2?"s2_checkpoint":"s3_checkpoint";
        int count=jdbc.update("UPDATE analysis_plan_units SET "+column+"=CAST(:checkpoint AS jsonb),s3_input_digest=COALESCE(s3_input_digest,:pin) WHERE plan_id=:plan AND ordinal=:ordinal AND (CAST(:pin AS text) IS NULL OR s3_input_digest IS NULL OR s3_input_digest=:pin)",
                params(stage.planId()).addValue("ordinal",stage.ordinal()).addValue("checkpoint",mapper.writeValueAsString(checkpoint)).addValue("pin",pin));
        if(count!=1) throw new CustomException(ErrorCode.REVISION_CONFLICT);
    }
    private String validateObservation(StageWork stage,StageObservation observation) {
        StageStatus status=observation.status();
        if(status==null) return null;
        if(stage.stage()==StageKind.S2) {
            var s=status.extraction();
            if(s==null || !s.jobId().equals(stage.extractionSubmit().jobId()) || !s.inputDigest().equals(stage.extractionInputDigest())
                    || !s.approvedRequestDigest().equals(stage.extractionSubmit().approvedRequestDigest())
                    || s.executionMode()!=stage.extractionSubmit().executionMode() || s.sourceKind()!=stage.relationSubmit().sourceKind()) throw new CustomException(ErrorCode.REVISION_CONFLICT);
        } else {
            var s=status.relation();
            if(s==null || !s.jobId().equals(stage.relationSubmit().jobId()) || !s.upstream().equals(stage.relationSubmit().upstream())
                    || s.executionMode()!=stage.relationSubmit().executionMode() || s.sourceKind()!=stage.relationSubmit().sourceKind()
                    || (stage.s3InputDigest()!=null && !stage.s3InputDigest().equals(s.inputDigest()))) throw new CustomException(ErrorCode.REVISION_CONFLICT);
        }
        if(observation.resultContentSha256()!=null && (state(status)!=PipelineJob.State.READY
                || (status.extraction()!=null?status.extraction().delivery():status.relation().delivery()).state()!=PipelineJob.DeliveryState.AVAILABLE)) throw new CustomException(ErrorCode.REVISION_CONFLICT);
        return status.relation()==null?null:status.relation().inputDigest();
    }
    private boolean finishLocked(AnalyzePlanClaim claim,AnalyzePlanTerminal outcome,Instant at) {
        PlanRunOut summary=summary(claim.appJobId(),"succeeded".equals(outcome.status())?"ready":outcome.status());
        if("succeeded".equals(outcome.status()) && (summary.totalUnits()==null || summary.totalUnits()==0 || summary.readyUnits()!=summary.totalUnits())) return false;
        ObjectNode checkpoint=mapper.createObjectNode(); checkpoint.put("schemaVersion","zoop-app-analyze-plan-checkpoint-1");
        checkpoint.put("phase",summary.phase()); checkpoint.putNull("activeOrdinal"); checkpoint.set("terminalSummary",mapper.valueToTree(summary));
        checkpoint.put("lastFailureCategory",outcome.failureCategory());
        String error=outcome.errorCode()==null?null:mapper.writeValueAsString(new AnalysisJobResponse.JobError(outcome.errorCode(),"분석 처리가 완료되지 않았습니다. 작업 상태를 확인해 주세요."));
        String attemptsJson = jdbc.queryForObject("SELECT attempts::text FROM analysis_jobs WHERE id=:id",
                new MapSqlParameterSource("id", claim.appJobId()), String.class);
        var attempts = (tools.jackson.databind.node.ArrayNode) mapper.readTree(attemptsJson);
        ObjectNode current = (ObjectNode) attempts.get(attempts.size() - 1);
        current.put("status", outcome.status());
        current.put("finishedAt", at.toString());
        current.put("failureCode", outcome.errorCode());
        return jdbc.update("""
                UPDATE analysis_jobs SET status=:status,finished_at=:at,owner_token=NULL,lease_until=NULL,next_attempt_at=NULL,
                checkpoint=CAST(:checkpoint AS jsonb),error=CAST(:error AS jsonb),attempts=CAST(:attempts AS jsonb)
                WHERE id=:id AND owner_token=:token AND status='running' AND lease_until > clock_timestamp()
                """, new MapSqlParameterSource("id", claim.appJobId()).addValue("status", outcome.status()).addValue("at", stamp(at))
                .addValue("checkpoint", mapper.writeValueAsString(checkpoint)).addValue("error", error)
                .addValue("attempts", mapper.writeValueAsString(attempts)).addValue("token", claim.ownerToken())) == 1;
    }
    private void cursor(String id,String phase,Integer ordinal,String category) {
        jdbc.update("UPDATE analysis_jobs SET checkpoint=jsonb_build_object('schemaVersion','zoop-app-analyze-plan-checkpoint-1','phase',CAST(:phase AS text),'activeOrdinal',CAST(:ordinal AS integer),'terminalSummary',NULL,'lastFailureCategory',CAST(:category AS text)) WHERE id=:id",
                new MapSqlParameterSource("id",id).addValue("phase",phase).addValue("ordinal",ordinal).addValue("category",category));
    }
    private Optional<PlanRegistration> registration(String planId,boolean cancel) {
        return jdbc.query("SELECT plan_id,plan_digest,service_binding,expected_principal,registered_at,registered_by,admission_intent_at,admission_id,accepted_at,policy_revision,policy_digest,receipt_sha256,manifest_digest,last_authority_state,last_authority_reason FROM analysis_plans WHERE plan_id=:plan",params(planId),
                (rs,n)->new PlanRegistration(new PlanReference(rs.getString("plan_id"),rs.getString("plan_digest")),
                    new ServiceBinding(rs.getString("service_binding"),rs.getString("expected_principal")),instant(rs,"registered_at"),rs.getString("registered_by"),
                    instant(rs,"admission_intent_at"),rs.getString("admission_id"),instant(rs,"accepted_at"),(Long)rs.getObject("policy_revision"),rs.getString("policy_digest"),
                    rs.getString("receipt_sha256"),rs.getString("manifest_digest"),rs.getString("last_authority_state"),rs.getString("last_authority_reason"),cancel)).stream().findFirst();
    }
    private int recoveryCount(String attempts,String jobId) {
        int total=0; for(var attempt:mapper.readTree(attempts).values()) { var counts=attempt.get("recoveryDispatches"); if(counts!=null && counts.has(jobId)) total+=counts.get(jobId).intValue(); } return total;
    }
    /** Column names are fixed repository literals. Read failures alone are not evidence that a command was issued. */
    private static String unsettledStage(String checkpoint) {
        return "(" + checkpoint + "->>'resultObservedAt' IS NULL AND ("
                + checkpoint + "->>'intentAt' IS NOT NULL OR "
                + checkpoint + "->>'acceptedObservedAt' IS NOT NULL OR "
                + checkpoint + "->>'lastStatus' IS NOT NULL) AND ("
                + "COALESCE(" + checkpoint + "->'lastStatus'->'extraction'->>'state', "
                + checkpoint + "->'lastStatus'->'relation'->>'state', '') NOT IN ('READY','CANCELLED') OR "
                + checkpoint + "->>'failureCategory'='outcome_unknown'))";
    }
    private static PipelineJob.State state(StageStatus s) { return s.extraction()!=null?s.extraction().state():s.relation().state(); }
    private record Job(String id,String kind,String status,String planId,String ownerToken,Instant leaseUntil,boolean cancelRequested,String attempts) {}
    private Job job(ResultSet rs,int n) throws SQLException { return new Job(rs.getString("id"),rs.getString("kind"),rs.getString("status"),rs.getString("plan_id"),rs.getString("owner_token"),instant(rs,"lease_until"),rs.getBoolean("cancel_requested"),rs.getString("attempts")); }
    private static Instant instant(ResultSet rs,String key) throws SQLException { var value=rs.getTimestamp(key); return value==null?null:value.toInstant(); }
    private static Timestamp stamp(Instant at) { return at==null?null:Timestamp.from(at); }
    private static MapSqlParameterSource params(String plan) { return new MapSqlParameterSource("plan",plan); }

    private ObjectNode manifest(PlanManifest m) {
        var node=mapper.createObjectNode(); node.put("schemaVersion",PlanManifest.SCHEMA_VERSION);node.put("planId",m.reference().planId());node.put("planDigest",m.reference().planDigest());
        node.put("receiptSha256",m.receiptSha256());node.put("principal",m.principal());node.set("round",mapper.valueToTree(m.round()));node.set("provenance",provenance(m.provenance()));
        var units=mapper.createArrayNode(); for(var u:m.units()) { var unit=mapper.createObjectNode();unit.put("unitKey",u.unitKey());unit.set("extractionSubmit",extraction(u.extractionSubmit()));unit.put("extractionInputDigest",u.extractionInputDigest());unit.set("relationSubmit",relation(u.relationSubmit()));units.add(unit); }
        node.set("units",units);node.put("manifestDigest",m.manifestDigest());return node;
    }
    private ObjectNode extraction(ExtractionSubmission s) { var n=mapper.createObjectNode();n.put("schemaVersion",ExtractionSubmission.SCHEMA_VERSION);n.put("jobId",s.jobId());n.put("approvedRequestDigest",s.approvedRequestDigest());return n; }
    private ObjectNode relation(RelationSubmission s) { var n=mapper.createObjectNode();n.put("schemaVersion",RelationSubmission.SCHEMA_VERSION);n.put("jobId",s.jobId());n.set("provenance",provenance(new PipelineJob.Provenance(s.sourceKind(),s.executionMode())));n.set("upstream",mapper.valueToTree(s.upstream()));return n; }
    private ObjectNode provenance(PipelineJob.Provenance p) { var n=mapper.createObjectNode();n.put("sourceKind",p.sourceKind().name().toLowerCase(java.util.Locale.ROOT));n.put("executionMode",p.executionMode().name().toLowerCase(java.util.Locale.ROOT));n.put("recordingKind",p.executionMode()==ExecutionMode.REPLAY?"authored-test":"provider");return n; }
}
