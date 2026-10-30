package com.zoop.chat.tool;

import java.time.Clock;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Registers {@code web.search} only when {@code zoop.chat.web.enabled=true} (off by default). The provider is chosen by
 * {@code zoop.chat.web.provider}: only {@code synthetic} exists until a real one is selected (web search design 7), and
 * startup is refused for anything else rather than running without a provider. Registered, the tool can be executed but
 * is never planned by the router nor exposed on MCP ({@link ChatToolRegistry#bound}).
 */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(name = "zoop.chat.web.enabled", havingValue = "true")
public class ChatWebSearchConfiguration {
    @Bean
    ChatWebSearchProvider chatWebSearchProvider(@Value("${zoop.chat.web.provider:none}") String provider) {
        if (SyntheticWebSearchProvider.ID.equals(provider)) return new SyntheticWebSearchProvider();
        throw new IllegalStateException("zoop.chat.web.enabled needs zoop.chat.web.provider=synthetic; no real web search "
                + "provider is selected yet");
    }

    @Bean
    ChatWebSearchTool chatWebSearchTool(ChatWebSearchProvider provider, Clock clock) {
        return new ChatWebSearchTool(provider, clock);
    }
}
