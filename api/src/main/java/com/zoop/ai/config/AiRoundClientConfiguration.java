package com.zoop.ai.config;

import com.zoop.ai.http.HttpRoundClient;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** Off by default and independent of the other AI clients: only the graph round scheduler runs rounds and asks for freezes. */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = AiRoundClientProperties.PREFIX, name = "enabled", havingValue = "true")
@EnableConfigurationProperties({AiRoundClientProperties.class, AiTransportProperties.class})
public class AiRoundClientConfiguration {
    /** One bean serves both families ({@code RoundRunClient} and {@code RoundHandoffClient}); the same principal holds both scopes. */
    @Bean
    HttpRoundClient aiRoundClient(AiRoundClientProperties properties, AiTransportProperties transport) {
        return new HttpRoundClient(properties.toSettings(transport));
    }
}
