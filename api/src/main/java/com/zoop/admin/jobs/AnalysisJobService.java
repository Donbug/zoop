package com.zoop.admin.jobs;

import com.zoop.admin.audit.AuditReasonPolicy;
import com.zoop.admin.auth.repository.AdminAuditRepository;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.jobs.AnalysisJobResponse.FlushResult;
import com.zoop.admin.jobs.AnalysisJobResponse.IngestBaseline;
import com.zoop.admin.jobs.AnalysisJobResponse.IngestOutcome;
import com.zoop.admin.jobs.AnalysisJobResponse.JobCreated;
import com.zoop.admin.jobs.AnalysisJobResponse.JobError;
import com.zoop.admin.jobs.AnalysisJobResponse.JobList;
import com.zoop.admin.jobs.AnalysisJobResponse.JobLock;
import com.zoop.admin.jobs.AnalysisJobResponse.JobOut;
import com.zoop.admin.jobs.AnalysisJobResponse.LedgerCounts;
import com.zoop.admin.jobs.AnalysisJobResponse.RunReport;
import com.zoop.admin.jobs.JdbcAnalysisJobRepository.IdempotencyRow;
import com.zoop.admin.jobs.JdbcAnalysisJobRepository.JobRow;
import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * The administrator's view of analysis jobs (#132) and the two actions on an existing one (#133): cancel and retry. Neither
 * calls the AI service: a cancel marks the row (a running job is stopped by the worker that owns it) and a retry only queues a
 * new job with {@code retry_of}, which the worker submits later. Submitting a new job ({@code createAnalysisJob}) is not
 * offered until that worker exists, so no accepted job can wait forever.
 */
@Service
public class AnalysisJobService {
    static final String RETRY_RULE = "실패하거나 취소된 작업만, 그 작업의 가장 최근 시도에서 재시도할 수 있습니다. 재시도는 새 작업으로 대기열에 들어가며 "
            + "실행 여부가 확인되지 않은 외부 호출은 자동으로 다시 보내지 않습니다.";
    private static final Set<String> STATUSES = Set.of("queued", "running", "succeeded", "failed", "cancelled");
    private static final int DEFAULT_LIMIT = 50;
    private static final int MAX_LIMIT = 100;

    private final JdbcAnalysisJobRepository repository;
    private final AdminAuditRepository audit;
    private final ObjectMapper mapper;
    private final CsrfKeyRing keys;
    private final Clock clock;

    public AnalysisJobService(JdbcAnalysisJobRepository repository, AdminAuditRepository audit, ObjectMapper mapper,
            CsrfKeyRing keys, Clock clock) {
        this.repository = repository;
        this.audit = audit;
        this.mapper = mapper;
        this.keys = keys;
        this.clock = clock;
    }

    @Transactional(readOnly = true)
    public JobList list(String adminId, String status, String cursor, Integer requestedLimit) {
        if (status != null && !STATUSES.contains(status)) throw new CustomException(ErrorCode.INVALID_REQUEST);
        if (requestedLimit != null && (requestedLimit < 1 || requestedLimit > MAX_LIMIT)) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        var position = JobCursor.decode(mapper, keys, cursor, adminId, status, requestedLimit, MAX_LIMIT);
        int limit = requestedLimit != null ? requestedLimit : position == null ? DEFAULT_LIMIT : position.limit();
        try {
            List<JobRow> rows = repository.page(status, position == null ? null : position.at(),
                    position == null ? null : position.id(), limit + 1);
            boolean hasNext = rows.size() > limit;
            List<JobRow> page = hasNext ? rows.subList(0, limit) : rows;
            JobRow running = repository.running().orElse(null);
            List<JobRow> judged = new ArrayList<>(page);
            if (running != null) judged.add(running);
            List<JobRow> context = repository.retryContext(judged);
            List<JobOut> items = page.stream().map(j -> out(j, context)).toList();
            JobOut active = running == null ? null : out(running, context);
            JobLock lock = active == null ? new JobLock(false, null, null)
                    : new JobLock(true, active.id(), "다른 관리자 작업이 실행 중입니다. 새 작업은 대기열에서 순서대로 실행됩니다.");
            String nextCursor = null;
            if (hasNext) {
                JobRow last = page.get(page.size() - 1);
                nextCursor = JobCursor.encode(mapper, keys, adminId, status, limit, last.requestedAt(), last.id());
            }
            return new JobList(items, active, lock, baseline(), RETRY_RULE, nextCursor);
        } catch (DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
    }

    @Transactional(readOnly = true)
    public JobOut get(String id) {
        try {
            JobRow job = repository.adminJob(id).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
            return out(job, repository.retryContext(List.of(job)));
        } catch (DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
    }

    /**
     * Queued → cancelled at once; running → cancel requested (the owning worker ends it, an in-flight AI child is not killed);
     * already cancelled → the same job again. A succeeded or failed job is finished, so cancelling it is a 409: a cancel never
     * withdraws a completed result or a public version.
     */
    @Transactional
    public JobOut cancel(String id, JobReasonRequest request, String idempotencyKey, AdminPrincipal admin, String requestId) {
        String reason = reason(request);
        String path = "/api/v1/admin/jobs/" + id + "/cancel";
        return idempotent(admin, path, idempotencyKey, id, requestHash("cancel", id, reason), 200, JobOut.class, () -> {
            JobRow job = repository.lockAdmin(id).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
            Instant now = clock.instant();
            switch (job.status()) {
                case "queued" -> repository.cancelQueued(id, now);
                case "running" -> {
                    if (job.cancelRequested()) return get(id); // already asked: nothing changes, nothing to audit
                    repository.requestCancel(id);
                }
                case "cancelled" -> {
                    return get(id);
                }
                default -> throw new CustomException(ErrorCode.REVISION_CONFLICT);
            }
            JobOut after = get(id);
            audit.recordAnalysisJobAction(admin.adminId(), admin.email(), "analysis.job.cancel", id, job.status(),
                    after.status(), null, reason, requestId, now);
            return after;
        });
    }

    /** A retry is a new queued job with {@code retry_of}, the same kind, label and input; refused unless the judge allows it. */
    @Transactional
    public JobCreated retry(String id, JobReasonRequest request, String idempotencyKey, AdminPrincipal admin,
            String requestId) {
        String reason = reason(request);
        String path = "/api/v1/admin/jobs/" + id + "/retry";
        return idempotent(admin, path, idempotencyKey, id, requestHash("retry", id, reason), 202, JobCreated.class, () -> {
            // The source row lock serialises two retries of the same job; the judge then sees the first one.
            JobRow job = repository.lockAdmin(id).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
            if (!RetryJudge.judge(job, errorCode(job), repository.retryContext(List.of(job))).allowed()) throw new CustomException(ErrorCode.REVISION_CONFLICT);
            Instant now = clock.instant();
            String newId = "job-" + UUID.randomUUID();
            repository.insertQueued(newId, job.kind(), job.label(), reason, admin.adminId(), now, id, "retry:" + id,
                    job.input());
            audit.recordAnalysisJobAction(admin.adminId(), admin.email(), "analysis.job.retry", id, job.status(),
                    job.status(), newId, reason, requestId, now);
            return new JobCreated(get(newId), false);
        });
    }

    private interface Action<T> {
        T run();
    }

    /** The #275 idempotency contract: same key and body replay the stored response, another body is IDEMPOTENCY_CONFLICT. */
    private <T> T idempotent(AdminPrincipal admin, String path, String key, String jobId, String requestHash, int status,
            Class<T> type, Action<T> action) {
        validateKey(key);
        try {
            boolean claimed = repository.claimIdempotency(UUID.randomUUID().toString(), admin.adminId(), path, key, jobId,
                    requestHash, clock.instant());
            IdempotencyRow record = repository.findIdempotencyForUpdate(admin.adminId(), path, key)
                    .orElseThrow(() -> new IllegalStateException("Claimed idempotency record is missing"));
            if (!record.requestHash().equals(requestHash)) throw new CustomException(ErrorCode.IDEMPOTENCY_CONFLICT);
            if (!claimed) {
                if (!"completed".equals(record.status()) || record.responseBody() == null) {
                    throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, true);
                }
                return mapper.readValue(record.responseBody(), type);
            }
            T result = action.run();
            repository.completeIdempotency(record.id(), status, mapper.writeValueAsString(result));
            return result;
        } catch (DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
    }

    /** {@code context} holds at least the job's retries and later successes on its input (see {@code retryContext}). */
    private JobOut out(JobRow j, List<JobRow> context) {
        JobError error = read(j.error(), JobError.class);
        Double duration = j.startedAt() == null || j.finishedAt() == null ? null
                : Duration.between(j.startedAt(), j.finishedAt()).toMillis() / 1000.0;
        return new JobOut(j.id(), j.kind(), j.label(), j.status(), j.reason(), j.requestedBy(), iso(j.requestedAt()),
                iso(j.startedAt()), iso(j.finishedAt()), duration, j.retryOf(), j.cancelRequested(), j.recovered(),
                RetryJudge.judge(j, error == null ? null : error.code(), context), read(j.ingest(), IngestOutcome.class),
                read(j.report(), RunReport.class), read(j.flush(), FlushResult.class), error,
                read(j.ledgerBefore(), LedgerCounts.class), read(j.ledgerAfter(), LedgerCounts.class));
    }

    /**
     * The next article run's baseline: the start of the newest ingest that finished normally (OpenAPI {@code IngestBaseline}).
     * {@code unresolvedFailures} counts article files, which only the worker's per-article records can tell; until they exist
     * it is null rather than a job count shown as an article count.
     */
    private IngestBaseline baseline() {
        var latest = repository.latestSucceededIngest();
        IngestOutcome outcome = latest.map(j -> read(j.ingest(), IngestOutcome.class)).orElse(null);
        return new IngestBaseline(latest.map(j -> iso(j.startedAt())).orElse(null), latest.map(JobRow::id).orElse(null),
                outcome == null ? null : outcome.outcome(), outcome == null ? null : outcome.newArticles(), null);
    }

    private String errorCode(JobRow job) {
        JobError error = read(job.error(), JobError.class);
        return error == null ? null : error.code();
    }

    private <T> T read(String json, Class<T> type) {
        return json == null ? null : mapper.readValue(json, type);
    }

    private static String reason(JobReasonRequest request) {
        String reason = request.reason().strip();
        if (!AuditReasonPolicy.safeMemberReason(reason)) throw new CustomException(ErrorCode.INVALID_REQUEST);
        return reason;
    }

    static String requestHash(String action, String jobId, String reason) {
        ObjectNode body = StrictJson.newObject();
        body.put("action", action);
        body.put("jobId", jobId);
        body.put("reason", reason);
        return Canonical.digest(body);
    }

    private static void validateKey(String key) {
        if (key == null || key.isBlank() || key.length() > 200 || key.chars().anyMatch(Character::isISOControl)) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
    }

    private static String iso(Instant value) {
        return value == null ? null : value.toString();
    }
}
