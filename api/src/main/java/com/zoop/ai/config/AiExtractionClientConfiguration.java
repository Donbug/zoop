package com.zoop.ai.config;

import com.zoop.ai.extraction.ExtractionClient;
import com.zoop.ai.http.HttpExtractionClient;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Registers the production {@link ExtractionClient} only when {@code zoop.ai.extraction-client.enabled=true}. Unconfigured, the
 * application starts without any S2 setting and no bean exists. When enabled, an invalid base URL, token or timeout fails
 * startup (closed) with a message that names the setting, not its value.
 */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = AiExtractionClientProperties.PREFIX, name = "enabled", havingValue = "true")
@EnableConfigurationProperties({AiExtractionClientProperties.class, AiTransportProperties.class})
public class AiExtractionClientConfiguration {

    @Bean
    HttpExtractionClient aiExtractionClient(AiExtractionClientProperties properties, AiTransportProperties transport) {
        return new HttpExtractionClient(properties.toSettings(transport));
    }
}
