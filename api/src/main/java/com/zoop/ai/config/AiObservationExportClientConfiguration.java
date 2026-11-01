package com.zoop.ai.config;

import com.zoop.ai.http.HttpObservationExportClient;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Off by default and independent of the other AI clients: the graph handoff import and the document import read observations
 * over HTTP ({@code observation-source=http}), and so does the web round bridge ({@code zoop.graph.round.import-source=http}).
 */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = AiObservationExportClientProperties.PREFIX, name = "enabled", havingValue = "true")
@EnableConfigurationProperties({AiObservationExportClientProperties.class, AiTransportProperties.class})
public class AiObservationExportClientConfiguration {
    @Bean
    HttpObservationExportClient aiObservationExportClient(AiObservationExportClientProperties properties,
            AiTransportProperties transport) {
        return new HttpObservationExportClient(properties.toSettings(transport));
    }
}
