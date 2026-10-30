package com.zoop.document.bindings;

/**
 * Closed set of operator-visible failure codes of the document bindings export. They are internal (there is no HTTP), carry
 * no message and never a value: a code is all that reaches the result file, the log and the exit path.
 */
public enum DocumentBindingsFailure {
    SELECTION_INVALID("selection_invalid"),
    SELECTION_UNREGISTERED("selection_unregistered"),
    RESULT_UNAVAILABLE("result_unavailable"),
    OUTPUT_UNAVAILABLE("output_unavailable"),
    BINDINGS_LIMIT("bindings_limit"),
    IDENTITY_INVALID("identity_invalid"),
    ARTIFACT_KIND_INVALID("artifact_kind_invalid"),
    DATABASE_UNAVAILABLE("database_unavailable"),
    INTERNAL_ERROR("internal_error");

    private final String code;

    DocumentBindingsFailure(String code) {
        this.code = code;
    }

    public String code() {
        return code;
    }
}
