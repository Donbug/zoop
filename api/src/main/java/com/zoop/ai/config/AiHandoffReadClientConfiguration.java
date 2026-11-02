package com.zoop.ai.config;

import com.zoop.ai.http.HttpHandoffReadClient;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** Off by default and independent of the S1/S2/S3 clients: only the graph handoff import reads handoffs over HTTP. */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = AiHandoffReadClientProperties.PREFIX, name = "enabled", havingValue = "true")
@EnableConfigurationProperties({AiHandoffReadClientProperties.class, AiTransportProperties.class})
public class AiHandoffReadClientConfiguration {
    @Bean
    HttpHandoffReadClient aiHandoffReadClient(AiHandoffReadClientProperties properties, AiTransportProperties transport) {
        return new HttpHandoffReadClient(properties.toSettings(transport));
    }
}
