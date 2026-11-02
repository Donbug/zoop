package com.zoop.ai.config;

import com.zoop.ai.http.HttpHandoffExposureClient;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** Off by default and independent of the S1/S2/S3 clients: only the operator exclusion command reads exposure. */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = AiHandoffExposureClientProperties.PREFIX, name = "enabled", havingValue = "true")
@EnableConfigurationProperties({AiHandoffExposureClientProperties.class, AiTransportProperties.class})
public class AiHandoffExposureClientConfiguration {
    @Bean
    HttpHandoffExposureClient aiHandoffExposureClient(AiHandoffExposureClientProperties properties,
            AiTransportProperties transport) {
        return new HttpHandoffExposureClient(properties.toSettings(transport));
    }
}
