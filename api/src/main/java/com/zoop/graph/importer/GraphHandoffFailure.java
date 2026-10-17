package com.zoop.graph.importer;

/**
 * Closed set of operator-visible failure codes of the graph handoff import. They are internal (there is no HTTP), carry no
 * message and never a value: a code is all that reaches the result file, the log and the exit path.
 */
public enum GraphHandoffFailure {
    REQUEST_INVALID("request_invalid"),
    RESULT_UNAVAILABLE("result_unavailable"),
    IMPORT_BUSY("import_busy"),
    ARTIFACT_STORE_UNAVAILABLE("artifact_store_unavailable"),
    ARTIFACT_FILE_CONFLICT("artifact_file_conflict"),
    /** The handoff CLI could not run or answer (missing binary, timeout, no JSON, unexpected exit status). */
    HANDOFF_EXPORT_UNAVAILABLE("handoff_export_unavailable"),
    /** The handoff CLI answered with its own structured error ({@code handoffCode}). */
    HANDOFF_REFUSED("handoff_refused"),
    /** The handoff is no longer deliverable under current authority ({@code handoffCode}); there is no content. */
    HANDOFF_WITHHELD("handoff_withheld"),
    /** The export envelope is not exactly what the installed CLI emits, or contradicts itself. */
    HANDOFF_EXPORT_INVALID("handoff_export_invalid"),
    /** The recomputed manifest or bundle digest is not the one the operator pinned in the request. */
    PIN_MISMATCH("pin_mismatch"),
    /** The bundle fails the closed schema, a reference closure, an id formula, a count or a digest. */
    BUNDLE_INVALID("bundle_invalid"),
    /** The whole review state of a pinned S3 job moved since the freeze, although the used relations did not. */
    REVIEW_STATE_CHANGED("review_state_changed"),
    INGESTION_EXPORT_FAILED("ingestion_export_failed"),
    INGESTION_EXPORT_UNAVAILABLE("ingestion_export_unavailable"),
    INGESTION_EXPORT_INVALID("ingestion_export_invalid"),
    /** The current S2-1 export of an observation differs from what the bundle recorded (grant, time, metadata). */
    OBSERVATION_MISMATCH("observation_mismatch"),
    /** The rights or the source facts of an observation changed between the first check and the commit. */
    RIGHTS_CHANGED("rights_changed"),
    ARTICLE_UNREGISTERED("article_unregistered"),
    ARTICLE_MISMATCH("article_mismatch"),
    TEXT_MISMATCH("text_mismatch"),
    EVIDENCE_INVALID("evidence_invalid"),
    EVIDENCE_COLLISION("evidence_collision"),
    COMPANY_MISMATCH("company_mismatch"),
    /** A time value cannot be written to the snapshot with the precision the bundle states; nothing is invented. */
    TEMPORAL_UNSUPPORTED("temporal_unsupported"),
    SNAPSHOT_INVALID("snapshot_invalid"),
    /** The graph version id exists with other pins (another receipt) or another kind. */
    VERSION_CONFLICT("version_conflict"),
    ARTIFACT_CONFLICT("artifact_conflict"),
    DATABASE_UNAVAILABLE("database_unavailable"),
    INTERNAL_ERROR("internal_error");

    private final String code;

    GraphHandoffFailure(String code) {
        this.code = code;
    }

    public String code() {
        return code;
    }
}
