package com.zoop.ai.config;

import com.zoop.ai.http.HttpObservationExportClient;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** Off by default and independent of the other AI clients: only the graph handoff import re-checks observations over HTTP. */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = AiObservationExportClientProperties.PREFIX, name = "enabled", havingValue = "true")
@EnableConfigurationProperties(AiObservationExportClientProperties.class)
public class AiObservationExportClientConfiguration {
    @Bean
    HttpObservationExportClient aiObservationExportClient(AiObservationExportClientProperties properties) {
        return new HttpObservationExportClient(properties.toSettings());
    }
}
