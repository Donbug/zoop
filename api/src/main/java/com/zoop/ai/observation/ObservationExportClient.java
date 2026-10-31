package com.zoop.ai.observation;

/**
 * ai/service's synchronous observation export ({@code exportObservation}, scope {@code observation.read}, AI PR #431): the
 * installed {@code zoop-ai-ingest export --require-store} run by the AI service for exactly one observation, answered as the
 * CLI's own JSON. The app persists quotes of the document, so the service always requires the {@code store} right; the rights
 * are checked by the CLI on every call and nothing is cached on either side. One request is one observation; there is no batch
 * and no job (decision D-R6, 2026-10-29).
 */
public interface ObservationExportClient {

    /** The S2-1 {@code Export} selector without its schema version: which exact observation of which round to export. */
    record Selector(String roundId, String sourceId, int page, int ordinal, String documentId, String rawVersion,
            String documentVersion) {
    }

    /**
     * The CLI's exact export JSON bytes (unvalidated beyond being one JSON object that names this observation); the strict
     * S2-1 parser decides everything else.
     *
     * @throws com.zoop.ai.ObservationServiceErrorException the service refused (4xx) or could not run the export (5xx)
     * @throws com.zoop.ai.AiTransportException             no decodable answer (connection, timeout, size, contract violation)
     */
    byte[] export(Selector selector);
}
