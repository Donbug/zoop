package com.zoop.ai.config;

import java.time.Duration;
import java.util.Set;

import com.zoop.ai.AiClientConfigurationException;
import com.zoop.ai.AiClientSettings;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * {@code zoop.ai.relation-client.*} (environment {@code ZOOP_AI_RELATION_CLIENT_*}, see {@code application.yml}): the S3
 * relation transport client. Independent of the S1 and S2 clients, so a principal and token with only {@code relation.*} scopes
 * can be used. Disabled unless {@code enabled=true}; when enabled every value is validated by {@link AiClientSettings} at startup
 * and a failure names {@code zoop.ai.relation-client.<setting>}, never a value. The token is never printed.
 */
@ConfigurationProperties("zoop.ai.relation-client")
public record AiRelationClientProperties(
        @DefaultValue("false") boolean enabled,
        String baseUrl,
        String token,
        @DefaultValue("3s") Duration connectTimeout,
        @DefaultValue("30s") Duration requestTimeout,
        @DefaultValue("8388608") int maxResponseBytes) {
    static final String PREFIX = "zoop.ai.relation-client";

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
        return "AiRelationClientProperties[enabled=" + enabled + ", token=<redacted>]";
    }
}
