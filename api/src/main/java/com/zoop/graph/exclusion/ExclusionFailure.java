package com.zoop.graph.exclusion;

/** Closed set of operator-visible failure codes of the exclusion command; a code is all that reaches the result file and the log. */
public enum ExclusionFailure {
    REQUEST_INVALID("request_invalid"),
    /** The result file could not be reserved or written; written after the commit, so the change may have been made. */
    RESULT_UNAVAILABLE("result_unavailable"),
    /** The embedded exposure report is not exactly {@code zoop-handoff-exposure-1}, or contradicts itself. */
    REPORT_INVALID("report_invalid"),
    /** A handoff of the report (or the lift's version) is not an imported graph version of this app. */
    VERSION_UNKNOWN("version_unknown"),
    /** The version's {@code verification_receipt} cannot be read or verified against the registry. */
    RECEIPT_UNAVAILABLE("receipt_unavailable"),
    /** The report's handoff id or a digest is not the one the app imported (exposure consumption rule 1). */
    RECEIPT_MISMATCH("receipt_mismatch"),
    /** The request id was recorded for another request. */
    REQUEST_CONFLICT("request_conflict"),
    /** A lift target changed after the lift's {@code expectedRevision}, or that revision is ahead of the store. */
    REVISION_STALE("revision_stale"),
    /** Known rollback: nothing was written. */
    DATABASE_UNAVAILABLE("database_unavailable"),
    /** The commit may or may not have happened: re-run the same request (same requestId) to read its recorded result. */
    OUTCOME_UNKNOWN("outcome_unknown"),
    INTERNAL_ERROR("internal_error");

    private final String code;

    ExclusionFailure(String code) {
        this.code = code;
    }

    public String code() {
        return code;
    }
}
