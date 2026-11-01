package com.zoop.ai.config;

import java.time.Duration;

import com.zoop.ai.AiClientConfigurationException;
import com.zoop.ai.AiClientSettings;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * {@code zoop.ai.round-client.*} ({@code ZOOP_AI_ROUND_CLIENT_*}): the round-run and round-handoff families (scopes
 * {@code round.run}, {@code round.read}) the graph round scheduler calls. Disabled by default and independent of every other AI
 * client. The requests are small and the answers are status documents (the selection report is at most a few hundred jobs), so
 * the response bound is 2 MiB; the freeze request carries the bindings export (up to 4 MB), which the request deadline covers.
 */
@ConfigurationProperties("zoop.ai.round-client")
public record AiRoundClientProperties(
        @DefaultValue("false") boolean enabled,
        String baseUrl,
        String token,
        String expectedPrincipal,
        @DefaultValue("3s") Duration connectTimeout,
        @DefaultValue("30s") Duration requestTimeout,
        @DefaultValue("2097152") int maxResponseBytes) {
    static final String PREFIX = "zoop.ai.round-client";

    public AiClientSettings toSettings() {
        try {
            return AiClientSettings.of(baseUrl, token, connectTimeout, requestTimeout, maxResponseBytes);
        } catch (AiClientConfigurationException error) {
            throw error.under(PREFIX);
        }
    }

    @Override
    public String toString() {
        return "AiRoundClientProperties[enabled=" + enabled + ", token=<redacted>]";
    }
}
