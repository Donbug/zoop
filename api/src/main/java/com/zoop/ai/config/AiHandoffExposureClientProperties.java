package com.zoop.ai.config;

import java.time.Duration;

import com.zoop.ai.AiClientConfigurationException;
import com.zoop.ai.AiClientSettings;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * The exposure query transport ({@code handoff.exposure} token, separate from every other AI scope). The report is capped at 6 MiB
 * by its producer; the envelope adds a few bytes.
 */
@ConfigurationProperties("zoop.ai.handoff-exposure-client")
public record AiHandoffExposureClientProperties(
        @DefaultValue("false") boolean enabled,
        String baseUrl,
        String token,
        @DefaultValue("3s") Duration connectTimeout,
        @DefaultValue("60s") Duration requestTimeout,
        @DefaultValue("7340032") int maxResponseBytes) {
    static final String PREFIX = "zoop.ai.handoff-exposure-client";

    public AiClientSettings toSettings() {
        try {
            return AiClientSettings.of(baseUrl, token, connectTimeout, requestTimeout, maxResponseBytes);
        } catch (AiClientConfigurationException error) {
            throw error.under(PREFIX);
        }
    }

    @Override
    public String toString() {
        return "AiHandoffExposureClientProperties[enabled=" + enabled + ", token=<redacted>]";
    }
}
