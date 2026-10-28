package com.zoop.ai.config;

import com.zoop.ai.http.HttpPlanAdmissionClient;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** Off by default, independent of S1/S2/S3 configuration, with the same internal service transport conventions. */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = AiPlanAdmissionClientProperties.PREFIX, name = "enabled", havingValue = "true")
@EnableConfigurationProperties(AiPlanAdmissionClientProperties.class)
public class AiPlanAdmissionClientConfiguration {
    @Bean
    HttpPlanAdmissionClient aiPlanAdmissionClient(AiPlanAdmissionClientProperties properties) {
        return new HttpPlanAdmissionClient(properties.toSettings());
    }
}
