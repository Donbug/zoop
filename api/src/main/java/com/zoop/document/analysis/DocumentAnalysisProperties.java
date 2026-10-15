package com.zoop.document.analysis;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * {@code zoop.document-analysis.*}, normally set from {@code ZOOP_DOCUMENT_ANALYSIS_*}, {@code ZOOP_INGESTION_*} and
 * {@code ZOOP_ARTIFACT_ROOT} environment variables (see {@code application.yml}). Disabled unless {@code enabled=true}; when
 * enabled {@link #toSettings()} validates every value at startup.
 */
@ConfigurationProperties("zoop.document-analysis")
public record DocumentAnalysisProperties(
        @DefaultValue("false") boolean enabled,
        String request,
        String result,
        String grants,
        String ingestionCli,
        String ingestionStateDir,
        String ingestionSources,
        String artifactRoot) {

    public DocumentAnalysisSettings toSettings() {
        return DocumentAnalysisSettings.of(request, result, grants, ingestionCli, ingestionStateDir, ingestionSources,
                artifactRoot);
    }

    @Override
    public String toString() {
        return "DocumentAnalysisProperties[enabled=" + enabled + "]";
    }
}
