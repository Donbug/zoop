package com.zoop.ai.config;

import java.time.Duration;
import java.util.Set;

import com.zoop.ai.AiClientConfigurationException;
import com.zoop.ai.AiClientSettings;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/** Reference-only app transport settings. No policy, source grant or budget settings are accepted here. */
@ConfigurationProperties("zoop.ai.plan-admission-client")
public record AiPlanAdmissionClientProperties(
        @DefaultValue("false") boolean enabled,
        String baseUrl,
        String token,
        @DefaultValue("3s") Duration connectTimeout,
        @DefaultValue("30s") Duration requestTimeout,
        @DefaultValue("16000000") int maxResponseBytes) {
    static final String PREFIX = "zoop.ai.plan-admission-client";

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
        return "AiPlanAdmissionClientProperties[enabled=" + enabled + ", token=<redacted>]";
    }
}
