package com.zoop.auth.config;

import java.time.Clock;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class AuthClockConfiguration {
    @Bean
    Clock authClock() {
        return Clock.systemUTC();
    }
}
