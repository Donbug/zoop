package com.zoop.document.analysis;

/**
 * Closed set of operator-visible failure codes of the document analysis. They are internal (there is no HTTP): a code, plus at
 * most a few identifier details (see {@link AnalysisException}), is all that reaches the result file and the log, never
 * document text, a path, a credential or a model output.
 *
 * <p>Settled outcomes such as a {@code withheld} or {@code failed} analysis are not failures of the run: they are stored,
 * terminal results with their own machine {@code reason}. A failure here means "nothing was written for this item" (or, for
 * {@link #DATABASE_UNAVAILABLE}, "the outcome is unknown").
 */
public enum AnalysisFailure {
    // the request and the run
    REQUEST_INVALID("request_invalid"),
    RESULT_UNAVAILABLE("result_unavailable"),
    ANALYSIS_BUSY("analysis_busy"),
    GRANT_REGISTRY_UNAVAILABLE("grant_registry_unavailable"),
    ARTIFACT_STORE_UNAVAILABLE("artifact_store_unavailable"),
    ARTIFACT_FILE_CONFLICT("artifact_file_conflict"),
    DATABASE_UNAVAILABLE("database_unavailable"),
    INTERNAL_ERROR("internal_error"),

    // prepare: the S2-1 export (same codes as the document import)
    INGESTION_EXPORT_FAILED("ingestion_export_failed"),
    INGESTION_EXPORT_UNAVAILABLE("ingestion_export_unavailable"),
    EXPORT_INVALID("export_invalid"),
    IDENTITY_UNSUPPORTED("identity_unsupported"),
    TEXT_HASH_MISMATCH("text_hash_mismatch"),
    TEXT_ENCODING_INVALID("text_encoding_invalid"),
    PUBLISHED_AT_UNSUPPORTED("published_at_unsupported"),
    METADATA_UNSUPPORTED("metadata_unsupported"),

    // prepare: registered document, company, rights and the compare-and-set
    DOCUMENT_NOT_REGISTERED("document_not_registered"),
    ARTICLE_PROVIDER_CONFLICT("article_provider_conflict"),
    ARTICLE_ACCESS_UNAVAILABLE("article_access_unavailable"),
    DOCUMENT_VERSION_MISMATCH("document_version_mismatch"),
    COMPANY_UNKNOWN("company_unknown"),
    COMPANY_CONTEXT_CHANGED("company_context_changed"),
    GRANT_DENIED("grant_denied"),
    REQUEST_TOO_LARGE("request_too_large"),
    ANALYSIS_UNCHANGED("analysis_unchanged"),
    LATEST_CONFLICT("latest_conflict"),
    ANALYSIS_PENDING("analysis_pending"),
    ARTIFACT_CONFLICT("artifact_conflict"),

    // advance: the AI service
    ANALYSIS_UNKNOWN("analysis_unknown"),
    ANALYSIS_NOT_PENDING("analysis_not_pending"),
    SUBMIT_ARTIFACT_INVALID("submit_artifact_invalid"),
    STATUS_UNAVAILABLE("status_unavailable"),
    STATUS_BINDING_INVALID("status_binding_invalid"),
    SUBMIT_OUTCOME_UNKNOWN("submit_outcome_unknown"),
    SUBMIT_CONFLICT("submit_conflict"),
    SUBMIT_REFUSED("submit_refused"),
    RECOVER_REQUIRED("recover_required"),
    RECOVER_REFUSED("recover_refused"),
    OPERATOR_RECONCILE_REQUIRED("operator_reconcile_required"),
    AI_RESULT_UNAVAILABLE("ai_result_unavailable"),

    // advance: the delivered result does not belong to this analysis (nothing is written; the row stays pending)
    RESULT_BINDING_INVALID("result_binding_invalid"),
    RESULT_PAYLOAD_INVALID("result_payload_invalid"),
    RECEIPTS_INVALID("receipts_invalid"),
    ARTIFACT_CREATOR_UNKNOWN("artifact_creator_unknown"),
    TEXT_ARTIFACT_MISMATCH("text_artifact_mismatch"),
    EXECUTION_CONFLICT("execution_conflict"),
    EVIDENCE_CONFLICT("evidence_conflict"),
    RESULT_VERSION_COLLISION("result_version_collision");

    private final String code;

    AnalysisFailure(String code) {
        this.code = code;
    }

    public String code() {
        return code;
    }
}
