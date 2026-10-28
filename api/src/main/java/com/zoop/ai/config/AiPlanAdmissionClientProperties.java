package com.zoop.ai.config;

import java.time.Duration;

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

    public AiClientSettings toSettings() {
        try {
            return AiClientSettings.of(baseUrl, token, connectTimeout, requestTimeout, maxResponseBytes);
        } catch (AiClientConfigurationException error) {
            throw error.under(PREFIX);
        }
    }

    @Override
    public String toString() {
        return "AiPlanAdmissionClientProperties[enabled=" + enabled + ", token=<redacted>]";
    }
}
