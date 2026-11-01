package com.zoop.ai.config;

import java.time.Duration;
import java.util.Set;

import com.zoop.ai.AiClientConfigurationException;
import com.zoop.ai.AiClientSettings;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * {@code zoop.ai.observation-export-client.*} ({@code ZOOP_AI_OBSERVATION_EXPORT_CLIENT_*}): the observation export route
 * (scope {@code observation.read}) the graph handoff import, the document import and the web round bridge use in place of the
 * installed {@code zoop-ai-ingest export --require-store}. Disabled by default and independent of every other AI client. The AI side runs the CLI child for at most
 * 45 s and answers at most 16 MiB, so the defaults are a 50 s request deadline and a 16 MiB response bound.
 */
@ConfigurationProperties("zoop.ai.observation-export-client")
public record AiObservationExportClientProperties(
        @DefaultValue("false") boolean enabled,
        String baseUrl,
        String token,
        @DefaultValue("3s") Duration connectTimeout,
        @DefaultValue("50s") Duration requestTimeout,
        @DefaultValue("16777216") int maxResponseBytes) {
    static final String PREFIX = "zoop.ai.observation-export-client";

    public AiClientSettings toSettings(AiTransportProperties transport) {
        // Outside the try: a bad host list is reported under zoop.ai, not under this client's prefix.
        Set<String> plaintextHttpHosts = transport.hosts();
        try {
            return AiClientSettings.of(baseUrl, token, connectTimeout, requestTimeout, maxResponseBytes, plaintextHttpHosts);
        } catch (AiClientConfigurationException error) {
            throw error.under(PREFIX);
        }
    }

    @Override
    public String toString() {
        return "AiObservationExportClientProperties[enabled=" + enabled + ", token=<redacted>]";
    }
}
