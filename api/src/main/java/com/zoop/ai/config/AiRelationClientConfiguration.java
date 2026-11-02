package com.zoop.ai.config;

import com.zoop.ai.http.HttpRelationClient;
import com.zoop.ai.relation.RelationClient;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Registers the production {@link RelationClient} only when {@code zoop.ai.relation-client.enabled=true}. Unconfigured, the
 * application starts without any S3 setting and no bean exists. When enabled, an invalid base URL, token or timeout fails
 * startup (closed) with a message that names the setting, not its value.
 */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = AiRelationClientProperties.PREFIX, name = "enabled", havingValue = "true")
@EnableConfigurationProperties({AiRelationClientProperties.class, AiTransportProperties.class})
public class AiRelationClientConfiguration {

    @Bean
    HttpRelationClient aiRelationClient(AiRelationClientProperties properties, AiTransportProperties transport) {
        return new HttpRelationClient(properties.toSettings(transport));
    }
}
