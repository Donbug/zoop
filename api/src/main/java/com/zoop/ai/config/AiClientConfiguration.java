package com.zoop.ai.config;

import com.zoop.ai.AiAnalysisClient;
import com.zoop.ai.http.HttpAiAnalysisClient;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Registers the production {@link AiAnalysisClient} only when {@code zoop.ai.client.enabled=true}. Unconfigured, the
 * application starts without any AI setting and no bean exists. When enabled, an invalid base URL, token or timeout fails
 * startup (closed) with a message that names the setting, not its value.
 */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = "zoop.ai.client", name = "enabled", havingValue = "true")
@EnableConfigurationProperties(AiClientProperties.class)
public class AiClientConfiguration {

    @Bean
    HttpAiAnalysisClient aiAnalysisClient(AiClientProperties properties) {
        return new HttpAiAnalysisClient(properties.toSettings());
    }
}
