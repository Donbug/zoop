package com.zoop.ai.config;

import java.time.Duration;
import java.util.Set;

import com.zoop.ai.AiClientConfigurationException;
import com.zoop.ai.AiClientSettings;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * {@code zoop.ai.chat-client.*} (environment {@code ZOOP_AI_CHAT_CLIENT_*}, see {@code application.yml}): the chatbot model stage
 * transport. Independent of the other AI clients, so a principal and token with only {@code chat.invoke} can be used. Disabled
 * unless {@code enabled=true}; when enabled every value is validated at startup and a failure names
 * {@code zoop.ai.chat-client.<setting>}, never a value. {@code mode} is {@code replay} (authored fixtures on the AI side, no
 * network) or {@code live} (real model calls behind the AI service's own chat gate). The request timeout covers the longest stage
 * (answer, 25 s) plus the service's margin. The token is never printed.
 */
@ConfigurationProperties("zoop.ai.chat-client")
public record AiChatClientProperties(
        @DefaultValue("false") boolean enabled,
        String baseUrl,
        String token,
        @DefaultValue("replay") String mode,
        @DefaultValue("3s") Duration connectTimeout,
        @DefaultValue("35s") Duration requestTimeout,
        @DefaultValue("2097152") int maxResponseBytes) {
    static final String PREFIX = "zoop.ai.chat-client";

    public AiClientSettings toSettings(AiTransportProperties transport) {
        // Outside the try: a bad host list is reported under zoop.ai, not under this client's prefix.
        Set<String> plaintextHttpHosts = transport.hosts();
        try {
            return AiClientSettings.of(baseUrl, token, connectTimeout, requestTimeout, maxResponseBytes, plaintextHttpHosts);
        } catch (AiClientConfigurationException error) {
            throw error.under(PREFIX);
        }
    }

    /** {@code replay} or {@code live}; anything else refuses to start. */
    public String validatedMode() {
        if (!"replay".equals(mode) && !"live".equals(mode)) {
            throw new IllegalStateException(PREFIX + ".mode must be replay or live");
        }
        return mode;
    }

    @Override
    public String toString() {
        return "AiChatClientProperties[enabled=" + enabled + ", mode=" + mode + ", token=<redacted>]";
    }
}
