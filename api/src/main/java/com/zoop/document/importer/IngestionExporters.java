package com.zoop.document.importer;

import java.util.function.Supplier;

import com.zoop.ai.observation.ObservationExportClient;
import org.springframework.beans.factory.ObjectProvider;

/**
 * Builds the {@link IngestionExporter} of an operator import from its {@link ObservationSource}: the installed S2-1 CLI, or
 * the observation export client that {@code zoop.ai.observation-export-client} registers. {@code http} needs the client and
 * fails startup without it (the caller's exception, naming its own setting); {@code cli} ignores an enabled client, since the
 * web application sharing this environment may hold one (its round bridge with {@code zoop.graph.round.import-source=http}).
 * The same rule the handoff read client follows.
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
