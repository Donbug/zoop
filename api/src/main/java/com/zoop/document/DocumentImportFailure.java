package com.zoop.document;

import java.util.regex.Pattern;

/**
 * Closed set of operator-visible failure codes of the document import. They are internal (there is no HTTP), carry no
 * message and never a value: a code is all that reaches the result file, the log and the exit path.
 */
public enum DocumentImportFailure {
    REQUEST_INVALID("request_invalid"),
    RESULT_UNAVAILABLE("result_unavailable"),
    IMPORT_BUSY("import_busy"),
    INGESTION_EXPORT_FAILED("ingestion_export_failed"),
    INGESTION_EXPORT_UNAVAILABLE("ingestion_export_unavailable"),
    EXPORT_INVALID("export_invalid"),
    IDENTITY_UNSUPPORTED("identity_unsupported"),
    TEXT_HASH_MISMATCH("text_hash_mismatch"),
    TEXT_ENCODING_INVALID("text_encoding_invalid"),
    PUBLISHED_AT_UNSUPPORTED("published_at_unsupported"),
    METADATA_UNSUPPORTED("metadata_unsupported"),
    ARTIFACT_FILE_CONFLICT("artifact_file_conflict"),
    ARTIFACT_STORE_UNAVAILABLE("artifact_store_unavailable"),
    ARTICLE_PROVIDER_CONFLICT("article_provider_conflict"),
    ARTICLE_KIND_CONFLICT("article_kind_conflict"),
    ARTICLE_ACCESS_UNAVAILABLE("article_access_unavailable"),
    ARTIFACT_CONFLICT("artifact_conflict"),
    VERSION_CONFLICT("version_conflict"),
    CURRENT_VERSION_CONFLICT("current_version_conflict"),
    DATABASE_UNAVAILABLE("database_unavailable"),
    INTERNAL_ERROR("internal_error");

    /** The S2-1 CLI error codes are lowercase snake_case; anything else is not echoed. */
    public static final Pattern INGESTION_CODE = Pattern.compile("[a-z_]{1,64}");

    private final String code;

    DocumentImportFailure(String code) {
        this.code = code;
    }

    public String code() {
        return code;
    }
}
