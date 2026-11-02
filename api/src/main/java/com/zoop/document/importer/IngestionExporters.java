package com.zoop.document.importer;

import java.util.function.Supplier;

import com.zoop.ai.observation.ObservationExportClient;
import org.springframework.beans.factory.ObjectProvider;

/**
 * Builds the {@link IngestionExporter} of an operator import from its {@link ObservationSource}: the installed S2-1 CLI, or
 * the observation export client that {@code zoop.ai.observation-export-client} registers. {@code http} needs the client and
 * fails startup without it (the caller's exception, naming its own setting); {@code cli} uses the installed exporter even when
 * this application's round bridge also has an enabled HTTP client.
 */
public final class IngestionExporters {
    private IngestionExporters() {
    }

    public static IngestionExporter forSource(ObservationSource source, Supplier<IngestionExporter> cli,
            ObjectProvider<ObservationExportClient> observationExports, Supplier<RuntimeException> missingClient) {
        if (source == ObservationSource.HTTP) {
            ObservationExportClient client = observationExports.getIfAvailable();
            if (client == null) {
                throw missingClient.get();
            }
            return new HttpIngestionExporter(client);
        }
        return cli.get();
    }
}
