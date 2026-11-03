package com.zoop.chat.tool;

import java.time.Clock;
import java.time.Duration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Registers {@code web.search} only when {@code zoop.chat.web.enabled=true} (off by default). The provider is chosen by
 * {@code zoop.chat.web.provider}: {@code synthetic} for fixtures, or {@code naver-api-hub-webkr}, the adapter whose use still
 * waits for the open decisions of web search design 7. Startup is refused for anything else, and for a provider missing its
 * credentials, rather than running without a provider. Registered, the tool is never planned by
 * the router ({@link ChatToolRegistry#bound}); it is an MCP tool of the agent path, whose answers cite its hits as
 * {@code web_result} (web search design 6).
 */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(name = "zoop.chat.web.enabled", havingValue = "true")
public class ChatWebSearchConfiguration {
    @Bean
    ChatWebSearchProvider chatWebSearchProvider(@Value("${zoop.chat.web.provider:none}") String provider,
            @Value("${zoop.chat.web.naver-api-hub.client-id:}") String clientId,
            @Value("${zoop.chat.web.naver-api-hub.client-secret:}") String clientSecret) {
        if (SyntheticWebSearchProvider.ID.equals(provider)) return new SyntheticWebSearchProvider();
        if (NaverApiHubWebSearchProvider.ID.equals(provider)) {
            return new NaverApiHubWebSearchProvider(clientId, clientSecret);
        }
        throw new IllegalStateException("zoop.chat.web.enabled needs a supported zoop.chat.web.provider"
                + " (synthetic or " + NaverApiHubWebSearchProvider.ID + ")");
    }

    @Bean
    ChatWebSearchTool chatWebSearchTool(ChatWebSearchProvider provider, Clock clock,
            @Value("${zoop.chat.web.cache-ttl:PT5M}") String cacheTtl,
            @Value("${zoop.chat.web.cache-max-entries:256}") int cacheEntries) {
        return new ChatWebSearchTool(provider, clock, Duration.parse(cacheTtl), cacheEntries);
    }
}
