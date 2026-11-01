package com.zoop.admin.pipeline;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import com.zoop.admin.auth.repository.AdminAuditRepository;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.jobs.JdbcAnalysisJobRepository;
import com.zoop.admin.jobs.JdbcAnalysisJobRepository.IdempotencyRow;
import com.zoop.admin.pipeline.GraphRoundAdminResponse.GraphRoundOut;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.graph.round.GraphRound;
import com.zoop.graph.round.GraphRoundClock;
import com.zoop.graph.round.GraphRoundEvent;
import com.zoop.graph.round.GraphRoundEvent.Outcome;
import com.zoop.graph.round.GraphRoundPatch;
import com.zoop.graph.round.GraphRoundRepository;
import com.zoop.graph.round.GraphRoundStage;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.dao.DataAccessException;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * The two admin commands on rounds (A-ADM-03, #55): {@code retryGraphRound} resumes a failed round at the stage it failed, under
 * the same round id (the AI side's idempotency keys are bound to it), and {@code startGraphRound} opens a row for a slot by
 * hand ({@code started_by = admin:<id>}). Both only mark the row; the scheduler's next pass does the work, so both are 404
 * while no scheduler runs here. Both are idempotent under the #275 contract (same key and body replay, another body
 * conflicts) through the shared {@code idempotency_records}, and both leave an audit row.
 */
@Service
public class GraphRoundAdminCommandService {
    static final String START_PATH = "/api/v1/admin/pipeline/rounds";
    static final Duration COMMAND_LEASE = Duration.ofSeconds(30);

    private final GraphRoundRepository rounds;
    private final ObjectProvider<GraphRoundClock> calendar;
    private final JdbcAnalysisJobRepository idempotency;
    private final AdminAuditRepository audit;
    private final ObjectMapper mapper;
    private final Clock clock;

    public GraphRoundAdminCommandService(GraphRoundRepository rounds, ObjectProvider<GraphRoundClock> calendar,
            JdbcAnalysisJobRepository idempotency, AdminAuditRepository audit, ObjectMapper mapper, Clock clock) {
        this.rounds = rounds;
        this.calendar = calendar;
        this.idempotency = idempotency;
        this.audit = audit;
        this.mapper = mapper;
        this.clock = clock;
    }

    @Transactional
    public GraphRoundOut retry(String roundId, String idempotencyKey, AdminPrincipal admin, String requestId) {
        if (roundId == null || !roundId.matches("round-[0-9]{8}T[0-9]{4}")) throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        requireScheduler();
        return idempotent(admin, START_PATH + "/" + roundId + "/retry", idempotencyKey, roundId, hash("retry", roundId), () -> {
            GraphRound round = rounds.find(roundId).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
            if (round.stage() != GraphRoundStage.FAILED) throw new CustomException(ErrorCode.REVISION_CONFLICT);
            GraphRoundStage resume = resumeStage(round);
            Instant now = clock.instant();
            String owner = "admin:" + admin.adminId();
            GraphRound claimed = rounds.claim(roundId, owner, COMMAND_LEASE, now)
                    .orElseThrow(() -> new CustomException(ErrorCode.REVISION_CONFLICT));
            ObjectNode detail = StrictJson.newObject();
            detail.put("adminId", admin.adminId());
            detail.put("resumeAt", resume.wire());
            round.failureCode().ifPresent(code -> detail.put("failureCode", code));
            GraphRound retried = rounds.advance(claimed, GraphRoundPatch.retryAt(resume), Outcome.RETRIED, null, requestId, detail, now)
                    .orElseThrow(() -> new CustomException(ErrorCode.REVISION_CONFLICT));
            rounds.release(roundId, owner);
            audit.recordGraphRoundAction(admin.adminId(), admin.email(), "pipeline.round.retry", roundId, requestId, now);
            return GraphRoundAdminService.out(rounds.find(roundId).orElse(retried));
        });
    }

    @Transactional
    public GraphRoundOut start(GraphRoundStartRequest request, String idempotencyKey, AdminPrincipal admin, String requestId) {
        GraphRoundClock clockOfSlots = requireScheduler();
        Instant now = clock.instant();
        boolean current = request == null || request.slotAt() == null;
        Instant slotAt = current ? clockOfSlots.minute(now) : parse(request.slotAt());
        String roundId = clockOfSlots.roundId(slotAt);
        // The request hash names what the admin sent, not the minute it arrived in: a replay of "start now" replays.
        return idempotent(admin, START_PATH, idempotencyKey, roundId, hash("start", current ? "now" : roundId), () -> {
            if (rounds.findBySlot(slotAt).isPresent() || rounds.find(roundId).isPresent()) {
                throw new CustomException(ErrorCode.REVISION_CONFLICT);
            }
            GraphRound created;
            try {
                created = rounds.create(roundId, slotAt, "admin:" + admin.adminId(), now);
            } catch (DataIntegrityViolationException taken) {
                throw new CustomException(ErrorCode.REVISION_CONFLICT);
            }
            audit.recordGraphRoundAction(admin.adminId(), admin.email(), "pipeline.round.start", roundId, requestId, now);
            return GraphRoundAdminService.out(created);
        });
    }

    /** The stage a retry resumes at: what the failure event recorded, else what the failure code's family says. */
    static GraphRoundStage resumeStage(GraphRound round, List<GraphRoundEvent> events) {
        String code = round.failureCode().orElse("");
        // Terminal jobs re-enter the queue's retry judgement even when an older event named analysis_queued.
        if (code.equals("analysis_failed") || code.startsWith("analysis_failed:")) return GraphRoundStage.PLAN_READY;
        for (int i = events.size() - 1; i >= 0; i--) {
            GraphRoundEvent event = events.get(i);
            if (event.outcome() != Outcome.FAILED) continue;
            Optional<JsonNode> failedAt = event.detail().map(d -> d.get("failedAt"));
            if (failedAt.isPresent() && failedAt.get() != null && failedAt.get().isString()) {
                try {
                    GraphRoundStage stage = GraphRoundStage.parse(failedAt.get().stringValue());
                    if (!stage.terminal()) return stage;
                } catch (IllegalArgumentException ignored) {
                    // fall through to the code family
                }
            }
            break;
        }
        if (code.startsWith("import")) return GraphRoundStage.HANDOFF_READY;
        if (code.startsWith("freeze") || code.startsWith("bindings")) return GraphRoundStage.ANALYSIS_DONE;
        // R4's wait for a still-running job timed out: keep reading that job. R3's analysis_queue_timeout (no job yet), a finished
        // job (analysis_failed) and a rejected plan are queued again from plan_ready.
        if (code.equals("analysis_timeout") && round.analysisJobId().isPresent()) return GraphRoundStage.ANALYSIS_QUEUED;
        if (code.startsWith("analysis") || code.startsWith("plan_rejected")) return GraphRoundStage.PLAN_READY;
        return GraphRoundStage.SCHEDULED;
    }

    private GraphRoundStage resumeStage(GraphRound round) {
        return resumeStage(round, rounds.events(round.roundId()));
    }

    private GraphRoundClock requireScheduler() {
        GraphRoundClock clockOfSlots = calendar.getIfAvailable();
        if (clockOfSlots == null) throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        return clockOfSlots;
    }

    private static Instant parse(String slotAt) {
        try {
            Instant at = Instant.parse(slotAt);
            if (!at.equals(at.truncatedTo(java.time.temporal.ChronoUnit.MINUTES))) throw new CustomException(ErrorCode.INVALID_REQUEST);
            return at;
        } catch (DateTimeParseException invalid) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
    }

    private interface Action {
        GraphRoundOut run();
    }

    private GraphRoundOut idempotent(AdminPrincipal admin, String path, String key, String targetId, String requestHash, Action action) {
        if (key == null || key.isBlank() || key.length() > 200 || key.chars().anyMatch(Character::isISOControl)) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        try {
            boolean claimed = idempotency.claimIdempotency(UUID.randomUUID().toString(), admin.adminId(), path, key, targetId,
                    requestHash, clock.instant());
            IdempotencyRow record = idempotency.findIdempotencyForUpdate(admin.adminId(), path, key)
                    .orElseThrow(() -> new IllegalStateException("Claimed idempotency record is missing"));
            if (!record.requestHash().equals(requestHash)) throw new CustomException(ErrorCode.IDEMPOTENCY_CONFLICT);
            if (!claimed) {
                if (!"completed".equals(record.status()) || record.responseBody() == null) {
                    throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, true);
                }
                return mapper.readValue(record.responseBody(), GraphRoundOut.class);
            }
            GraphRoundOut result = action.run();
            idempotency.completeIdempotency(record.id(), 202, mapper.writeValueAsString(result));
            return result;
        } catch (DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
    }

    private static String hash(String command, String target) {
        ObjectNode body = StrictJson.newObject();
        body.put("command", command);
        body.put("target", target);
        return Canonical.digest(body);
    }
}
