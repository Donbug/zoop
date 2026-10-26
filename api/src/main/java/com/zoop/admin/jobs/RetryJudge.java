package com.zoop.admin.jobs;

import com.zoop.admin.jobs.AnalysisJobResponse.RetryState;
import com.zoop.admin.jobs.JdbcAnalysisJobRepository.JobRow;
import java.util.Comparator;
import java.util.List;
import java.util.Optional;
import java.util.Set;

/**
 * Whether an administrator may retry a job (OpenAPI {@code RetryState}), judged from the job and the admin jobs related to it
 * (its retries, later successes on its input). A retry is a new job with {@code retry_of}; it never resends an AI request on its
 * own. {@code other_running} stays in the contract but is never returned: under the queue policy (ERD v6 section 31) another
 * running job only delays a retry, it does not refuse it.
 */
final class RetryJudge {
    /**
     * Failure codes meaning the provider may have executed the request without the answer reaching us (AI internal contract:
     * {@code reconcile_required}, {@code live_response_unknown}). Retrying could run, and charge, the work twice.
     */
    static final Set<String> OUTCOME_UNKNOWN = Set.of("outcome_unknown", "live_response_unknown", "reconcile_required");

    private RetryJudge() {
    }

    /** {@code errorCode} is the job's stored {@code error.code}, null when it has none; {@code context} may hold other jobs too. */
    static RetryState judge(JobRow job, String errorCode, List<JobRow> context, boolean workerAvailable, String planBarrier) {
        switch (job.status()) {
            case "queued", "running" -> {
                return state(false, "in_progress", "작업이 아직 진행 중입니다.", null);
            }
            case "succeeded" -> {
                return state(false, "succeeded", "이미 성공한 작업입니다.", null);
            }
            default -> {
                // failed or cancelled
            }
        }
        List<JobRow> retries = context.stream().filter(j -> job.id().equals(j.retryOf()))
                .sorted(Comparator.comparing(JobRow::requestedAt).reversed()).toList();
        Optional<JobRow> active = retries.stream()
                .filter(j -> "queued".equals(j.status()) || "running".equals(j.status())).findFirst();
        if (active.isPresent()) {
            return state(false, "duplicate_running", "이 작업의 재시도가 이미 대기 중이거나 실행 중입니다.", active.get().id());
        }
        if (!retries.isEmpty()) {
            return state(false, "newer_attempt", "이 작업에는 이미 더 새로운 재시도가 있습니다. 가장 최근 시도를 재시도해 주세요.",
                    retries.get(0).id());
        }
        // The same input succeeded later in another job: retrying this one would only redo that result.
        Optional<JobRow> successor = context.stream()
                .filter(j -> !j.id().equals(job.id()) && "succeeded".equals(j.status()) && j.kind().equals(job.kind())
                        && j.input().equals(job.input()) && j.requestedAt().isAfter(job.requestedAt()))
                .max(Comparator.comparing(JobRow::requestedAt));
        if (successor.isPresent()) {
            return state(false, "superseded", "같은 입력을 처리한 더 나중의 작업이 이미 성공했습니다.", successor.get().id());
        }
        if ((errorCode != null && OUTCOME_UNKNOWN.contains(errorCode)) || "outcome_unknown".equals(planBarrier)) {
            return state(false, "outcome_unknown",
                    "외부 실행 결과를 확인할 수 없어 자동으로 다시 실행하지 않습니다. 운영자가 실행 여부를 확인한 뒤 처리해 주세요.", null);
        }
        if (!workerAvailable || !"analyze_plan".equals(job.kind())) {
            return state(false, "worker_unavailable", "이 작업을 처리할 실행기가 연결되어 있지 않습니다.", null);
        }
        if (planBarrier != null) {
            return state(false, planBarrier, "등록된 계획을 그대로 이어서 처리할 수 없습니다.", null);
        }
        if (Set.of("plan_binding_mismatch", "ai_binding_mismatch", "ai_state_missing", "ai_contract_mismatch", "ai_cancelled")
                .contains(errorCode == null ? "" : errorCode)) {
            return state(false, "plan_not_reusable", "이 계획의 고정 실행을 다시 시작할 수 없습니다.", null);
        }
        return state(true, "allowed", "같은 계획을 이어서 처리할 수 있습니다.", null);
    }

    private static RetryState state(boolean allowed, String code, String reason, String blockedBy) {
        return new RetryState(allowed, code, reason, blockedBy);
    }
}
