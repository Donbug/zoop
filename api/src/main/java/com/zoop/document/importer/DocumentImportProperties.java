package com.zoop.document.importer;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * {@code zoop.document-import.*}, normally set from {@code ZOOP_DOCUMENT_IMPORT_*} and {@code ZOOP_INGESTION_*}
 * environment variables (see {@code application.yml}). Disabled unless {@code enabled=true}; when enabled
 * {@link #toSettings()} validates every value at startup.
 */
@ConfigurationProperties("zoop.document-import")
public record DocumentImportProperties(
        @DefaultValue("false") boolean enabled,
        String request,
        String result,
        String ingestionCli,
        String ingestionStateDir,
        String ingestionSources,
        String artifactRoot) {

    public DocumentImportSettings toSettings() {
        return DocumentImportSettings.of(request, result, ingestionCli, ingestionStateDir, ingestionSources,
                artifactRoot);
    }

    @Override
    public String toString() {
        return "DocumentImportProperties[enabled=" + enabled + "]";
    }
}
