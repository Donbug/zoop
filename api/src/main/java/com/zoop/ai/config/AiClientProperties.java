package com.zoop.ai.config;

import java.time.Duration;

import com.zoop.ai.AiClientSettings;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * {@code zoop.ai.client.*}, normally set from {@code ZOOP_AI_CLIENT_*} environment variables (see {@code application.yml}).
 * Disabled unless {@code enabled=true}; when enabled every value is validated by {@link AiClientSettings} at startup.
 * The token is never printed.
 */
@ConfigurationProperties("zoop.ai.client")
public record AiClientProperties(
        @DefaultValue("false") boolean enabled,
        String baseUrl,
        String token,
        @DefaultValue("3s") Duration connectTimeout,
        @DefaultValue("30s") Duration requestTimeout,
        @DefaultValue("8388608") int maxResponseBytes) {

    public AiClientSettings toSettings(AiTransportProperties transport) {
        return AiClientSettings.of(baseUrl, token, connectTimeout, requestTimeout, maxResponseBytes, transport.hosts());
    }

    @Override
    public String toString() {
        return "AiClientProperties[enabled=" + enabled + ", token=<redacted>]";
    }
}
