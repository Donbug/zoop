package com.zoop.ai.config;

import java.time.Duration;
import java.util.Set;

import com.zoop.ai.AiClientConfigurationException;
import com.zoop.ai.AiClientSettings;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * {@code zoop.ai.extraction-client.*} (environment {@code ZOOP_AI_EXTRACTION_CLIENT_*}, see {@code application.yml}): the S2
 * extraction transport client. Independent of the S1 client, so a principal and token with only {@code extraction.*} scopes can
 * be used. Disabled unless {@code enabled=true}; when enabled every value is validated by {@link AiClientSettings} at startup
 * and a failure names {@code zoop.ai.extraction-client.<setting>}, never a value. The token is never printed.
 */
@ConfigurationProperties("zoop.ai.extraction-client")
public record AiExtractionClientProperties(
        @DefaultValue("false") boolean enabled,
        String baseUrl,
        String token,
        @DefaultValue("3s") Duration connectTimeout,
        @DefaultValue("30s") Duration requestTimeout,
        @DefaultValue("8388608") int maxResponseBytes) {
    static final String PREFIX = "zoop.ai.extraction-client";

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
        return "AiExtractionClientProperties[enabled=" + enabled + ", token=<redacted>]";
    }
}
