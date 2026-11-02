package com.zoop.ai.config;

import java.time.Duration;
import java.util.Set;

import com.zoop.ai.AiClientConfigurationException;
import com.zoop.ai.AiClientSettings;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * {@code zoop.ai.handoff-read-client.*} ({@code ZOOP_AI_HANDOFF_READ_CLIENT_*}): the read-only handoff family (scope
 * {@code handoff.read}) the graph handoff import uses in place of the installed {@code zoop-ai-handoff export}. Disabled by
 * default and independent of every other AI client. A bundle is at most 6 MiB and its envelope about 7 MiB, so the default
 * response bound is 16 MiB as the AI side recommends.
 */
@ConfigurationProperties("zoop.ai.handoff-read-client")
public record AiHandoffReadClientProperties(
        @DefaultValue("false") boolean enabled,
        String baseUrl,
        String token,
        @DefaultValue("3s") Duration connectTimeout,
        @DefaultValue("60s") Duration requestTimeout,
        @DefaultValue("16777216") int maxResponseBytes) {
    static final String PREFIX = "zoop.ai.handoff-read-client";

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
        return "AiHandoffReadClientProperties[enabled=" + enabled + ", token=<redacted>]";
    }
}
