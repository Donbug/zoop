package com.zoop.document.importer;

import com.zoop.ai.AiClientException;
import com.zoop.ai.AiServiceRejectionException;
import com.zoop.ai.AiTransportException;
import com.zoop.ai.observation.ObservationExportClient;
import com.zoop.document.DocumentImportException;
import com.zoop.document.DocumentImportFailure;

/**
 * The observation re-check over ai/service's observation export route instead of a local {@code zoop-ai-ingest} child: the same
 * selector, the same CLI JSON back, the same strict parser afterwards. Only the failure translation lives here, and it keeps
 * the CLI exporter's meaning:
 * <ul>
 * <li>a 503 envelope ({@code runtime_busy}, {@code service_busy}, {@code execution_unavailable},
 *     {@code service_configuration_invalid}) and every transport failure (connection, timeout, interruption) →
 *     {@code ingestion_export_unavailable}: a later run may succeed. The service's {@code Retry-After} is not carried (the CLI
 *     path has none either); the caller's fixed wait rule applies;</li>
 * <li>every other envelope → {@code ingestion_export_failed} with the service's code, which names the cause: the CLI's own
 *     refusal relayed ({@code source_unauthorized}, {@code round_not_found}, {@code registry_changed}, ... as a CLI exit 2 is),
 *     this client's token or request ({@code authentication_required}, {@code scope_denied}, {@code invalid_request},
 *     {@code request_too_large}), or the AI side's CLI binding ({@code runtime_contract_mismatch},
 *     {@code runtime_binding_mismatch}, 500), which an operator must fix before any export can succeed;</li>
 * <li>an answer outside the contract (malformed, unexpected status, too large, redirect) → {@code export_invalid}: the same
 *     bytes would fail again until the service is fixed.</li>
 * </ul>
 * Nothing is retried here; the caller's own wait rules decide, as for the CLI.
 */
public final class HttpIngestionExporter implements IngestionExporter {
    private final ObservationExportClient client;

    public HttpIngestionExporter(ObservationExportClient client) {
        this.client = client;
    }

    @Override
    public byte[] export(Observation observation) {
        try {
            return client.export(new ObservationExportClient.Selector(observation.roundId(), observation.sourceId(),
                    observation.page(), observation.ordinal(), observation.documentId(), observation.rawVersion(),
                    observation.documentVersion()));
        } catch (AiClientException failure) {
            throw translate(failure);
        }
    }

    static DocumentImportException translate(AiClientException failure) {
        if (failure instanceof AiServiceRejectionException rejection) {
            return rejection.httpStatus() == 503
                    ? new DocumentImportException(DocumentImportFailure.INGESTION_EXPORT_UNAVAILABLE)
                    : DocumentImportException.ingestionRefused(rejection.code());
        }
        AiTransportException transport = (AiTransportException) failure;
        return switch (transport.failure()) {
            case RESPONSE_MALFORMED, UNEXPECTED_RESPONSE, RESPONSE_TOO_LARGE, REDIRECT_REFUSED ->
                    new DocumentImportException(DocumentImportFailure.EXPORT_INVALID);
            default -> new DocumentImportException(DocumentImportFailure.INGESTION_EXPORT_UNAVAILABLE);
        };
    }
}
