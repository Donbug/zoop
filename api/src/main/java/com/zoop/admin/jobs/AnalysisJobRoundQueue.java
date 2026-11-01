package com.zoop.admin.jobs;

import java.util.Optional;

import com.zoop.admin.jobs.AnalysisJobResponse.JobCreated;
import com.zoop.admin.jobs.AnalysisJobResponse.JobError;
import com.zoop.admin.jobs.JdbcAnalysisJobRepository.JobRow;
import com.zoop.ai.plan.PlanReference;
import com.zoop.graph.round.RoundAnalysisQueue;
import tools.jackson.databind.ObjectMapper;

/**
 * The round scheduler's door to the analyze_plan queue: the same service and rows as the admin screen, with the system actor
 * ({@code requested_by = system:scheduler}, a system audit row) and the command key per plan, so a plan is analysed once however
 * many rounds or retries name it.
 */
public final class AnalysisJobRoundQueue implements RoundAnalysisQueue {
    private final AnalysisJobService jobs;
    private final JdbcAnalysisJobRepository repository;
    private final ObjectMapper mapper;

    public AnalysisJobRoundQueue(AnalysisJobService jobs, JdbcAnalysisJobRepository repository, ObjectMapper mapper) {
        this.jobs = jobs;
        this.repository = repository;
        this.mapper = mapper;
    }

    @Override
    public Queued queue(String planId, String planDigest, String roundId, String requestId) {
        JobCreated created = jobs.createForSystem(new PlanReference(planId, planDigest), "정기 회차 " + roundId, requestId);
        return new Queued(created.job().id(), created.deduplicated());
    }

    @Override
    public JobStatus status(String jobId) {
        Optional<JobRow> row = repository.adminJob(jobId);
        if (row.isEmpty()) return new JobStatus(JobState.MISSING, Optional.empty());
        JobRow job = row.get();
        JobState state = switch (job.status()) {
            case "queued" -> JobState.QUEUED;
            case "running" -> JobState.RUNNING;
            case "succeeded" -> JobState.SUCCEEDED;
            case "failed" -> JobState.FAILED;
            case "cancelled" -> JobState.CANCELLED;
            default -> JobState.MISSING;
        };
        Optional<String> code = Optional.empty();
        if (job.error() != null) {
            JobError error = mapper.readValue(job.error(), JobError.class);
            code = Optional.ofNullable(error == null ? null : error.code());
        }
        return new JobStatus(state, code);
    }
}
