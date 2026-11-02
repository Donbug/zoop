package com.zoop.graph.importer;

import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;

import com.zoop.document.importer.IngestionExporter;
import com.zoop.document.importer.Observation;
import com.zoop.document.importer.ProcessIngestionExporter;

/** Routes the full selector, then independently re-exports it through the existing credential-free process. */
public final class RoutedIngestionExporter implements IngestionExporter {
    private final Path cli;
    private final HandoffSourceContexts contexts;
    private final Map<HandoffSourceContexts.Context, ProcessIngestionExporter> exporters = new HashMap<>();

    public RoutedIngestionExporter(Path cli, HandoffSourceContexts contexts) {
        this.cli = cli;
        this.contexts = contexts;
    }

    @Override
    public byte[] export(Observation observation) {
        var context = contexts.observation(observation);
        byte[] result = exporters.computeIfAbsent(context,
                route -> ProcessIngestionExporter.forPaths(cli, route.ingestion(), route.sources())).export(observation);
        contexts.unchanged();
        return result;
    }
}
