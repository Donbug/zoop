package com.zoop.graph.importer;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * {@code zoop.graph-handoff-import.*}, normally set from {@code ZOOP_GRAPH_HANDOFF_IMPORT_*}, {@code ZOOP_HANDOFF_*},
 * {@code ZOOP_*_STATE_DIR}, {@code ZOOP_INGESTION_*} and {@code ZOOP_ARTIFACT_ROOT} environment variables (see
 * {@code application.yml}). Disabled unless {@code enabled=true}; when enabled {@link GraphHandoffImportSettings#of} validates
 * every value at startup.
 */
@ConfigurationProperties("zoop.graph-handoff-import")
public record GraphHandoffImportProperties(
        @DefaultValue("false") boolean enabled,
        String request,
        String result,
        String handoffCli,
        String handoffStateDir,
        String relationStateDir,
        String extractionStateDir,
        String ingestionCli,
        String ingestionStateDir,
        String ingestionSources,
        String canonical,
        String decisions,
        String bindings,
        String artifactRoot) {

    public GraphHandoffImportSettings toSettings() {
        return GraphHandoffImportSettings.of(this);
    }

    @Override
    public String toString() {
        return "GraphHandoffImportProperties[enabled=" + enabled + "]";
    }
}
