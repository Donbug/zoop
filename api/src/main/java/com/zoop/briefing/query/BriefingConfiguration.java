package com.zoop.briefing.query;

import java.time.Clock;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class BriefingConfiguration {
    @Bean
    @ConditionalOnMissingBean(Clock.class)
    Clock briefingClock() { return Clock.systemUTC(); }

    @Bean
    @ConditionalOnMissingBean(BriefingContentAccess.class)
    BriefingContentAccess denyUntilRightsOwnerIsConnected() { return round -> false; }
}
