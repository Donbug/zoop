package com.zoop.ai.http;

import java.util.Set;

import com.zoop.ai.ObservationServiceErrorException;

/** The observation export family's {@code ErrorEnvelope} ({@code zoop-ai-internal-1}) decoder and the export's schema name. */
final class ObservationWire {
    /** The S2-1 export document's {@code schemaVersion}, the same value the request selector carries. */
    static final String EXPORT_SCHEMA = "zoop-ingestion-s2-1";

    private ObservationWire() {
    }

    /** The shared envelope under the generic internal schema; {@code status} (a job status in other families) may be present only as null. */
    static AiHttpTransport.Rejections rejections() {
        return HandoffWire.envelope(AnalysisWire.INTERNAL_SCHEMA, Set.of("schemaVersion", "error", "status"),
                ObservationServiceErrorException::new);
    }
}
