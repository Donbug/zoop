package com.zoop.document.importer;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.nio.charset.StandardCharsets;
import java.util.Optional;
import java.util.OptionalInt;
import java.util.concurrent.atomic.AtomicReference;

import com.zoop.ai.AiClientException;
import com.zoop.ai.AiOperation;
import com.zoop.ai.AiTransportException;
import com.zoop.ai.ObservationServiceErrorException;
import com.zoop.ai.observation.ObservationExportClient;
import com.zoop.document.DocumentImportException;
import com.zoop.document.DocumentImportFailure;
import org.junit.jupiter.api.Test;

class HttpIngestionExporterTest {
    private static final Observation OBSERVATION = new Observation("round-1", "src-a", 2, 5, "doc-" + "a".repeat(64),
            "b".repeat(64), "c".repeat(64));

    @Test
    void theSelectorIsTheObservationAndTheBytesComeBackUntouched() {
        AtomicReference<ObservationExportClient.Selector> seen = new AtomicReference<>();
        byte[] export = "{\"schemaVersion\":\"zoop-ingestion-s2-1\"}".getBytes(StandardCharsets.UTF_8);
        HttpIngestionExporter exporter = new HttpIngestionExporter(selector -> {
            seen.set(selector);
            return export;
        });

        assertArrayEquals(export, exporter.export(OBSERVATION));
        assertEquals(new ObservationExportClient.Selector("round-1", "src-a", 2, 5, "doc-" + "a".repeat(64), "b".repeat(64),
                "c".repeat(64)), seen.get());
    }

    @Test
    void aFiveOhThreeIsUnavailableAndEveryOtherEnvelopeIsARefusalNamedByItsCode() {
        DocumentImportException refused = failure(rejection(403, "source_unauthorized"));
        assertEquals(DocumentImportFailure.INGESTION_EXPORT_FAILED, refused.failure());
        assertEquals("source_unauthorized", refused.ingestionCode());
        assertEquals("round_not_found", failure(rejection(404, "round_not_found")).ingestionCode());
        assertEquals("registry_changed", failure(rejection(409, "registry_changed")).ingestionCode());
        assertEquals("scope_denied", failure(rejection(403, "scope_denied")).ingestionCode());
        assertEquals("authentication_required", failure(rejection(401, "authentication_required")).ingestionCode());
        // The AI side's CLI binding is broken: an operator must act, so it is a refusal with its code, never "try again later".
        DocumentImportException contract = failure(rejection(500, "runtime_contract_mismatch"));
        assertEquals(DocumentImportFailure.INGESTION_EXPORT_FAILED, contract.failure());
        assertEquals("runtime_contract_mismatch", contract.ingestionCode());

        for (String code : new String[] {"runtime_busy", "service_busy", "execution_unavailable", "service_configuration_invalid"}) {
            DocumentImportException busy = failure(rejection(503, code));
            assertEquals(DocumentImportFailure.INGESTION_EXPORT_UNAVAILABLE, busy.failure(), code);
            assertNull(busy.ingestionCode());
        }
    }

    @Test
    void transportFailuresAreUnavailableAndContractViolationsAreInvalid() {
        for (AiTransportException.Failure failure : new AiTransportException.Failure[] {AiTransportException.Failure.CONNECT_FAILED,
                AiTransportException.Failure.CONNECT_TIMEOUT, AiTransportException.Failure.TIMEOUT, AiTransportException.Failure.IO_ERROR,
                AiTransportException.Failure.INTERRUPTED}) {
            assertEquals(DocumentImportFailure.INGESTION_EXPORT_UNAVAILABLE, failure(transport(failure)).failure(), failure.name());
        }
        for (AiTransportException.Failure failure : new AiTransportException.Failure[] {AiTransportException.Failure.RESPONSE_MALFORMED,
                AiTransportException.Failure.UNEXPECTED_RESPONSE, AiTransportException.Failure.RESPONSE_TOO_LARGE,
                AiTransportException.Failure.REDIRECT_REFUSED}) {
            assertEquals(DocumentImportFailure.EXPORT_INVALID, failure(transport(failure)).failure(), failure.name());
        }
    }

    private static DocumentImportException failure(AiClientException thrown) {
        HttpIngestionExporter exporter = new HttpIngestionExporter(selector -> {
            throw thrown;
        });
        return assertThrows(DocumentImportException.class, () -> exporter.export(OBSERVATION));
    }

    private static ObservationServiceErrorException rejection(int status, String code) {
        return new ObservationServiceErrorException(AiOperation.OBSERVATION_EXPORT, "req-1", status, code, status >= 500,
                Optional.empty(), Optional.empty(), Optional.empty());
    }

    private static AiTransportException transport(AiTransportException.Failure failure) {
        return new AiTransportException(AiOperation.OBSERVATION_EXPORT, "req-1", failure, OptionalInt.empty(), null);
    }
}
