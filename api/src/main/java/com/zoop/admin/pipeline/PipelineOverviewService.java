package com.zoop.admin.pipeline;

import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Objects;

import com.zoop.admin.jobs.AnalysisJobResponse.JobOut;
import com.zoop.admin.jobs.AnalysisJobResponse.RunReport;
import com.zoop.admin.jobs.AnalysisJobService;
import com.zoop.admin.pipeline.JdbcPipelineOverviewReader.ActiveVersion;
import com.zoop.admin.pipeline.PipelineOverviewResponse.GraphDbStatus;
import com.zoop.admin.pipeline.PipelineOverviewResponse.IssueCounts;
import com.zoop.admin.pipeline.PipelineOverviewResponse.JobFailure;
import com.zoop.admin.pipeline.PipelineOverviewResponse.LedgerRef;
import com.zoop.admin.pipeline.PipelineOverviewResponse.Overview;
import com.zoop.admin.pipeline.PipelineOverviewResponse.OverviewJobs;
import com.zoop.admin.pipeline.PipelineOverviewResponse.PastRun;
import com.zoop.admin.pipeline.PipelineOverviewResponse.PolicyInfo;
import com.zoop.admin.pipeline.PipelineOverviewResponse.PublicationState;
import com.zoop.admin.pipeline.PipelineOverviewResponse.ReviewCounts;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

/**
 * {@code getPipelineOverview} (A-ADM-03, FS059·FS067-01): analysis jobs, review targets and decisions, and the public version,
 * from the app database in one snapshot. The contract's shape comes from the prototype, whose ledger was the AI side's; what the
 * app does not hold is answered as the contract allows and never guessed (2026-10-26 decisions A–D):
 * <ul>
 * <li>{@code ledger} is the app database ({@value #DATABASE}) read at {@code asOf}.</li>
 * <li>{@code policy}: only the active version's policy version; the AI decision policy and model are not the app's, and the app
 *     never verifies on the web.</li>
 * <li>{@code ruleCandidates}/{@code ruleEvents} are 0: a publication rule never publishes a HOLD (AI answer 5-A).</li>
 * <li>{@code projection}: the graph state recorded with the active version, never a current reading (the importer records none,
 *     so an imported version is {@code unavailable}); {@code pendingJobs} is null, the app cannot count them now.</li>
 * <li>{@code review} counts administrators' decisions only, never migrated ones.</li>
 * <li>{@code runs[].usage} is null where the app holds no usage, never a guessed 0.</li>
 * <li>{@code ledgerMatchesActive}: the most recent import is the active version. Issue lists between versions are not compared.</li>
 * </ul>
 */
@Service
public class PipelineOverviewService {
    static final String DATABASE = "zoop-app";
    static final int RUNS = 10;

    private final JdbcPipelineOverviewReader reader;
    private final AnalysisJobService jobs;
    private final Clock clock;

    public PipelineOverviewService(JdbcPipelineOverviewReader reader, AnalysisJobService jobs, Clock clock) {
        this.reader = reader;
        this.jobs = jobs;
        this.clock = clock;
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public Overview overview() {
        try {
            Instant now = clock.instant();
            String asOf = now.toString();
            ActiveVersion active = reader.activeVersion().orElse(null);
            var decisions = reader.decisions();
            var pipeline = jobs.pipelineAt(now, RUNS);
            List<String> plans = pipeline.recent().stream().filter(j -> j.planRun() != null).map(j -> j.planRun().planId())
                    .filter(Objects::nonNull).distinct().toList();
            Map<String, Map<String, Long>> statuses = reader.relationStatusesByPlan(plans);
            JobOut failed = pipeline.lastFailure();
            return new Overview(asOf, new LedgerRef(DATABASE, asOf),
                    new PolicyInfo(active == null ? null : active.policyVersion(), null, false, null),
                    reader.candidates(),
                    active == null ? new IssueCounts(0, 0, 0)
                            : new IssueCounts(active.issues(), active.relations(), active.articles()),
                    new ReviewCounts(decisions.revision(), decisions.total(), decisions.allowed(), decisions.rejected(),
                            decisions.holdPending(), 0, 0),
                    projection(active, asOf),
                    new PublicationState(active == null ? null : active.id(),
                            active != null && reader.latestImportedVersionId().filter(active.id()::equals).isPresent(),
                            List.of(), List.of()),
                    new OverviewJobs(pipeline.running(), pipeline.queued(), pipeline.failed24h(),
                            failed == null ? null : new JobFailure(failed.id(), failed.label(), failed.finishedAt(),
                                    failed.error() == null ? null : failed.error().code(),
                                    failed.error() == null ? null : failed.error().message()),
                            pipeline.ingest()),
                    pipeline.recent().stream().map(job -> run(job, statuses)).toList());
        } catch (DataAccessException unavailable) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, unavailable);
        }
    }

    private static GraphDbStatus projection(ActiveVersion active, String asOf) {
        if (active == null) return new GraphDbStatus("unavailable", null, null, null, null, asOf);
        String status = switch (active.graphDbStatus() == null ? "" : active.graphDbStatus()) {
            case "reflected" -> "reflected";
            case "pending" -> "pending";
            default -> "unavailable";
        };
        return new GraphDbStatus(status, null, null, null, null, asOf);
    }

    /**
     * An analyze-plan job counts its units and the status of its review targets so far (null until it has targets; a relation
     * with no verdict yet has no target, so {@code pending} is unknown). Other jobs answer from their own run report. The run id
     * is always the job id, so a run links to its job.
     */
    private static PastRun run(JobOut job, Map<String, Map<String, Long>> statuses) {
        if (job.planRun() != null) {
            Map<String, Long> counts = statuses.get(job.planRun().planId());
            return new PastRun(job.id(), job.label(), "admin-job", "job-runner", job.planRun().totalUnits(),
                    count(counts, "ALLOW"), count(counts, "HOLD"), count(counts, "REJECT"), null, null, null);
        }
        RunReport report = job.report();
        if (report == null) {
            return new PastRun(job.id(), job.label(), "admin-job", "job-runner", null, null, null, null, null, null, null);
        }
        return new PastRun(job.id(), job.label(), "admin-job", "job-runner",
                report.processed(), report.approved(), report.held(), report.rejected(), report.pending(), report.errorCount(),
                report.usage());
    }

    private static Integer count(Map<String, Long> counts, String status) {
        return counts == null ? null : Math.toIntExact(counts.getOrDefault(status, 0L));
    }
}
