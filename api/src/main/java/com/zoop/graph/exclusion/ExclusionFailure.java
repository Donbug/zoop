package com.zoop.graph.exclusion;

/** Closed set of operator-visible failure codes of the exclusion command; a code is all that reaches the result file and the log. */
public enum ExclusionFailure {
    REQUEST_INVALID("request_invalid"),
    RESULT_UNAVAILABLE("result_unavailable"),
    /** The embedded exposure report is not exactly {@code zoop-handoff-exposure-1}, or contradicts itself. */
    REPORT_INVALID("report_invalid"),
    /** A handoff of the report (or the lift's version) is not an imported graph version of this app. */
    VERSION_UNKNOWN("version_unknown"),
    /** The version's {@code verification_receipt} cannot be read or verified against the registry. */
    RECEIPT_UNAVAILABLE("receipt_unavailable"),
    /** The report's handoff id or a digest is not the one the app imported (exposure consumption rule 1). */
    RECEIPT_MISMATCH("receipt_mismatch"),
    DATABASE_UNAVAILABLE("database_unavailable"),
    INTERNAL_ERROR("internal_error");

    private final String code;

    ExclusionFailure(String code) {
        this.code = code;
    }

    public String code() {
        return code;
    }
}
