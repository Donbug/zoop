package com.zoop.ai.http;

/** Wire documents of the S2 extraction and S3 relation families as the real service writes them (every key present). */
final class PipelineJson {
    static final String INPUT = "1".repeat(64);
    static final String APPROVED = "2".repeat(64);
    static final String OTHER = "3".repeat(64);
    static final String UPSTREAM_DIGEST = "4".repeat(64);
    static final String UPSTREAM_JOB = "s2-job-1";
    static final String CANDIDATE = "rc-" + "a".repeat(64);
    static final String STAMP = "2026-10-14T03:00:00Z";
    static final String EXTRACTION_SCHEMA = "zoop-ai-internal-extraction-1";
    static final String RELATION_SCHEMA = "zoop-ai-internal-relation-1";

    static final String REVIEW_APPLIED = "{\"state\":\"applied\",\"resultingSourceRevision\":\"2\",\"recordedAt\":\"" + STAMP + "\"}";
    static final String REVIEW_UNCONFIRMED = "{\"state\":\"unconfirmed\",\"resultingSourceRevision\":null,\"recordedAt\":null}";
    static final String REVAL_NONE = reval("not_requested", "null", "null", "null");
    static final String REVAL_VERIFIED = reval("verified", "\"eligible\"", "\"3\"", "\"" + STAMP + "\"");
    static final String REVAL_SUPERSEDED = reval("superseded", "null", "\"3\"", "\"" + STAMP + "\"");
    static final String REVAL_CONTRACT_CHANGED = reval("contract_changed", "null", "null", "\"" + STAMP + "\"");

    private PipelineJson() {
    }

    static String reval(String state, String verdict, String resulting, String updatedAt) {
        return "{\"state\":\"" + state + "\",\"dispatchCount\":0,\"lastOutcome\":null,\"lastRuntimeCode\":null,\"verdict\":" + verdict
                + ",\"resultingSourceRevision\":" + resulting + ",\"updatedAt\":" + updatedAt + "}";
    }

    static String delivery(String withheldReason) {
        return withheldReason == null ? "{\"state\":\"available\",\"reason\":null}"
                : "{\"state\":\"withheld\",\"reason\":\"" + withheldReason + "\"}";
    }

    private static final String DISPATCH = "{\"state\":\"pending\",\"dispatchCount\":0,\"lastOutcome\":null,\"lastRuntimeCode\":null,"
            + "\"updatedAt\":\"" + STAMP + "\"}";
    private static final String PROVENANCE = "{\"sourceKind\":\"synthetic\",\"executionMode\":\"replay\",\"recordingKind\":\"authored-test\"}";

    // ---- S2 ----

    static String extractionStatus(String jobId, String state, String next, String approved, String withheldReason) {
        return "{\"schemaVersion\":\"" + EXTRACTION_SCHEMA + "\",\"jobId\":\"" + jobId + "\",\"inputDigest\":\"" + INPUT
                + "\",\"approval\":{\"approvedRequestDigest\":\"" + approved + "\"},\"provenance\":" + PROVENANCE + ",\"state\":\"" + state
                + "\",\"phase\":\"extract.pending\",\"resumeMode\":\"resume\",\"failure\":null,"
                + "\"usage\":{\"replayCalls\":0,\"startedWithoutReceipt\":0,\"providerCalls\":0,\"paidModelCalls\":0,\"receivedCalls\":0,\"unsentCalls\":0,"
                + "\"inputTokens\":null,\"outputTokens\":null,\"reasoningTokens\":null,\"estimatedUsd\":null,\"chargedUsd\":null},"
                + "\"stages\":[{\"stage\":\"extract\",\"state\":\"pending\"}],\"delivery\":" + delivery(withheldReason)
                + ",\"dispatch\":" + DISPATCH + ",\"next\":\"" + next + "\",\"acceptedAt\":\"" + STAMP + "\",\"observedAt\":\"" + STAMP + "\"}";
    }

    static String extractionJob(String jobId, String inputDigest) {
        return "{\"jobId\":\"" + jobId + "\",\"inputDigest\":\"" + inputDigest
                + "\",\"counts\":{\"documents\":1},\"eventCandidates\":[{\"title\":\"UNTRUSTED-TEXT\"}],\"topicCandidates\":[]}";
    }

    /** {@code statusReason} is the delivery inside the embedded status, {@code reason} the envelope's own. */
    static String extractionResult(String jobId, String approved, String statusReason, String reason, String job) {
        return "{\"schemaVersion\":\"" + EXTRACTION_SCHEMA + "\",\"status\":" + extractionStatus(jobId, "ready", "fetch_result", approved, statusReason)
                + ",\"delivery\":" + delivery(reason) + ",\"job\":" + job + ",\"receipts\":[{\"stage\":\"extract\",\"state\":\"received\",\"verdict\":null}]}";
    }

    // ---- S3 ----

    static String relationStatus(String jobId, String state, String next, String upstreamDigest, String withheldReason) {
        return "{\"schemaVersion\":\"" + RELATION_SCHEMA + "\",\"jobId\":\"" + jobId + "\",\"inputDigest\":\"" + INPUT
                + "\",\"provenance\":" + PROVENANCE + ",\"upstream\":{\"jobId\":\"" + UPSTREAM_JOB + "\",\"inputDigest\":\"" + upstreamDigest
                + "\"},\"state\":\"" + state + "\",\"phase\":\"relation.pending\",\"resumeMode\":\"resume\",\"failure\":null,"
                + "\"usage\":{\"replayCalls\":0,\"startedWithoutReceipt\":0,\"providerCalls\":0,\"modelCalls\":0},\"delivery\":"
                + delivery(withheldReason) + ",\"dispatch\":" + DISPATCH + ",\"next\":\"" + next + "\",\"acceptedAt\":\"" + STAMP
                + "\",\"observedAt\":\"" + STAMP + "\"}";
    }

    static String relationJob(String jobId, String inputDigest, String sourceVersion, String sourceRevision) {
        return "{\"jobId\":\"" + jobId + "\",\"inputDigest\":\"" + inputDigest + "\",\"counts\":{\"relations\":1},\"relations\":[{"
                + "\"relationCandidateId\":\"" + CANDIDATE + "\",\"sourceVersion\":\"" + sourceVersion + "\",\"sourceRevision\":\""
                + sourceRevision + "\",\"type\":\"UNTRUSTED\"}]}";
    }

    static String relationResult(String jobId, String reason, String job) {
        return "{\"schemaVersion\":\"" + RELATION_SCHEMA + "\",\"status\":" + relationStatus(jobId, "ready", "fetch_result", UPSTREAM_DIGEST, reason)
                + ",\"delivery\":" + delivery(reason) + ",\"job\":" + job + ",\"receipts\":[]}";
    }

    /** A current-contract operation: no limitation. */
    static String operation(String operationId, String jobId, String decision, String review, String revalidation, String next) {
        return operation(operationId, jobId, decision, review, revalidation, next, null);
    }

    /** {@code limitation} is {@code review_contract_changed} for an operation recorded under the earlier revalidation contract, else null. */
    static String operation(String operationId, String jobId, String decision, String review, String revalidation, String next, String limitation) {
        return "{\"schemaVersion\":\"" + RELATION_SCHEMA + "\",\"operationId\":\"" + operationId + "\",\"jobId\":\"" + jobId
                + "\",\"relationCandidateId\":\"" + CANDIDATE + "\",\"decision\":\"" + decision + "\",\"reviewer\":\"alpha\","
                + "\"expectedSourceVersion\":\"" + INPUT + "\",\"expectedSourceRevision\":\"1\",\"review\":" + review
                + ",\"revalidation\":" + revalidation + ",\"publication\":{\"state\":\"not_published\"},\"next\":\"" + next
                + "\",\"limitation\":" + (limitation == null ? "null" : "\"" + limitation + "\"")
                + ",\"acceptedAt\":\"" + STAMP + "\",\"observedAt\":\"" + STAMP + "\"}";
    }

    /** A {@code receipts} array of {@code count} content-free receipts: the services emit one per runtime call, without a fixed cap. */
    static String receipts(int count) {
        StringBuilder array = new StringBuilder("[");
        for (int i = 0; i < count; i++) {
            array.append(i == 0 ? "" : ",").append("{\"stage\":\"compare\",\"state\":\"received\",\"verdict\":null}");
        }
        return array.append(']').toString();
    }

    // ---- errors ----

    static String error(String schema, String code, boolean retryable, String requestId, String status, String operation) {
        return "{\"schemaVersion\":\"" + schema + "\",\"error\":{\"code\":\"" + code + "\",\"retryable\":" + retryable
                + ",\"requestId\":\"" + requestId + "\",\"runtimeCode\":null,\"field\":null},\"status\":"
                + (status == null ? "null" : status) + (operation == null ? "" : ",\"operation\":" + operation) + "}";
    }
}
