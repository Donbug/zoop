package com.zoop.admin.jobs;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.admin.jobs.AnalysisJobResponse.RetryState;
import com.zoop.admin.jobs.JdbcAnalysisJobRepository.JobRow;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;

class RetryJudgeTest {
    private static final Instant T0 = Instant.parse("2026-10-22T00:00:00Z");
    private static final String INPUT = "{\"planId\": \"plan-1\"}";

    @Test
    void aQueuedOrRunningJobIsInProgressAndASucceededOneIsDone() {
        assertCode("in_progress", job("job-aaaaaaaa", "queued", null, 0), List.of());
        assertCode("in_progress", job("job-aaaaaaaa", "running", null, 0), List.of());
        assertCode("succeeded", job("job-aaaaaaaa", "succeeded", null, 0), List.of());
    }

    @Test
    void aFailedOrCancelledJobWithNothingAgainstItIsAllowed() {
        for (String status : new String[] {"failed", "cancelled"}) {
            RetryState state = RetryJudge.judge(job("job-aaaaaaaa", status, null, 0), "provider_error", List.of());
            assertTrue(state.allowed(), status);
            assertEquals("allowed", state.code());
            assertNull(state.blockedBy());
        }
    }

    @Test
    void aWaitingRetryBlocksItAsDuplicateRunningAndAFinishedOneAsNewerAttempt() {
        JobRow failed = job("job-aaaaaaaa", "failed", null, 0);
        JobRow queuedRetry = job("job-bbbbbbbb", "queued", failed.id(), 1);
        RetryState running = RetryJudge.judge(failed, null, List.of(queuedRetry, failed));
        assertEquals("duplicate_running", running.code());
        assertEquals(queuedRetry.id(), running.blockedBy());

        JobRow failedRetry = job("job-bbbbbbbb", "failed", failed.id(), 1);
        RetryState newer = RetryJudge.judge(failed, null, List.of(failedRetry, failed));
        assertEquals("newer_attempt", newer.code(), "only the latest attempt may be retried");
        assertEquals(failedRetry.id(), newer.blockedBy());
        assertTrue(RetryJudge.judge(failedRetry, null, List.of(failedRetry, failed)).allowed(), "the latest attempt can");
    }

    @Test
    void aLaterSuccessOnTheSameKindAndInputSupersedesIt() {
        JobRow failed = job("job-aaaaaaaa", "failed", null, 0);
        JobRow later = job("job-cccccccc", "succeeded", null, 2);
        RetryState state = RetryJudge.judge(failed, null, List.of(later, failed));
        assertEquals("superseded", state.code());
        assertEquals(later.id(), state.blockedBy());

        JobRow otherInput = new JobRow("job-dddddddd", "ingest", "admin", "수집", "succeeded", "r", "admin-1", T0.plusSeconds(3),
                T0.plusSeconds(3), T0.plusSeconds(4), null, "k-d", "{\"planId\": \"plan-2\"}", false, false, null, null, null,
                null, null, null);
        assertTrue(RetryJudge.judge(failed, null, List.of(otherInput, failed)).allowed(), "another input does not supersede");
        JobRow earlier = job("job-eeeeeeee", "succeeded", null, -1);
        assertTrue(RetryJudge.judge(failed, null, List.of(failed, earlier)).allowed(), "an earlier success does not either");
    }

    @Test
    void anUnknownProviderOutcomeIsNeverRetriedAutomatically() {
        for (String code : RetryJudge.OUTCOME_UNKNOWN) {
            RetryState state = RetryJudge.judge(job("job-aaaaaaaa", "failed", null, 0), code, List.of());
            assertFalse(state.allowed(), code);
            assertEquals("outcome_unknown", state.code());
        }
    }

    @Test
    void anotherRunningJobNeverRefusesARetry() {
        // other_running stays in the contract, but the queue takes the retry behind the running job.
        JobRow failed = job("job-aaaaaaaa", "failed", null, 0);
        JobRow unrelated = new JobRow("job-ffffffff", "project", "admin", "투영", "running", "r", "admin-1", T0.plusSeconds(5),
                T0.plusSeconds(5), null, null, "k-f", "{}", false, false, null, null, null, null, null, null);
        assertEquals("allowed", RetryJudge.judge(failed, null, List.of(unrelated, failed)).code());
    }

    private static void assertCode(String code, JobRow job, List<JobRow> others) {
        RetryState state = RetryJudge.judge(job, null, others);
        assertEquals(code, state.code());
        assertFalse(state.allowed());
    }

    private static JobRow job(String id, String status, String retryOf, int offsetSeconds) {
        Instant at = T0.plusSeconds(offsetSeconds);
        boolean finished = !"queued".equals(status) && !"running".equals(status);
        return new JobRow(id, "ingest", "admin", "수집", status, "r", "admin-1", at,
                "queued".equals(status) ? null : at, finished ? at.plusSeconds(1) : null, retryOf, "k-" + id, INPUT, false,
                false, null, null, null, null, null, null);
    }
}
