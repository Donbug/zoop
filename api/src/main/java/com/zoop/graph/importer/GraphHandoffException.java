package com.zoop.graph.importer;

import java.util.regex.Pattern;

/**
 * One import (or its request) failed in a defined way. The message is the code only. The optional details are identifiers,
 * never text or paths: the CLI's own error code, and the position of the observation that failed. No cause, no stack trace,
 * so that nothing else can ride along into a log.
 */
public final class GraphHandoffException extends RuntimeException {
    /** The CLIs' own codes are lowercase snake_case (digits allowed, e.g. {@code s2_payload_invalid}); anything else is not echoed. */
    private static final Pattern CLI_CODE = Pattern.compile("[a-z0-9_]{1,64}");

    private final GraphHandoffFailure failure;
    private final String cliCode;
    private final int observation;

    public GraphHandoffException(GraphHandoffFailure failure) {
        this(failure, null, -1);
    }

    private GraphHandoffException(GraphHandoffFailure failure, String cliCode, int observation) {
        super(failure.code(), null, false, false);
        this.failure = failure;
        this.cliCode = cliCode;
        this.observation = observation;
    }

    /** The handoff CLI refused with its structured error. */
    public static GraphHandoffException handoffRefused(String code) {
        return new GraphHandoffException(GraphHandoffFailure.HANDOFF_REFUSED, safe(code), -1);
    }

    /** The handoff CLI answered {@code delivery.status=withheld}. */
    public static GraphHandoffException handoffWithheld(String code) {
        return new GraphHandoffException(GraphHandoffFailure.HANDOFF_WITHHELD, safe(code), -1);
    }

    /** The per-observation S2-1 export failed; {@code ingestionCode} is set only for the CLI's own refusal. */
    public static GraphHandoffException ingestion(GraphHandoffFailure failure, String ingestionCode, int observation) {
        return new GraphHandoffException(failure, safe(ingestionCode), observation);
    }

    /** The same failure, attributed to the observation at this position (bundle order). */
    public GraphHandoffException atObservation(int index) {
        return new GraphHandoffException(failure, cliCode, index);
    }

    public GraphHandoffFailure failure() {
        return failure;
    }

    /** The CLI's own error code ({@code handoffCode} or {@code ingestionCode} in the result), or null. */
    public String cliCode() {
        return cliCode;
    }

    /** Position of the failing observation in bundle order (articles, then their observations), or -1. */
    public int observation() {
        return observation;
    }

    private static String safe(String code) {
        return code != null && CLI_CODE.matcher(code).matches() ? code : null;
    }
}
