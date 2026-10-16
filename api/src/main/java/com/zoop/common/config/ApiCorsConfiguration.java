package com.zoop.common.config;

import java.util.Arrays;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/** CORS policy shared by all public API modules. */
@Configuration
public class ApiCorsConfiguration implements WebMvcConfigurer {
    private final String allowedOrigins;

    public ApiCorsConfiguration(@Value("${zoop.api.cors.allowed-origins:}") String allowedOrigins) {
        this.allowedOrigins = allowedOrigins;
    }

    @Override
    public void addCorsMappings(CorsRegistry registry) {
        String[] origins = allowedOrigins == null || allowedOrigins.isBlank()
                ? new String[0]
                : Arrays.stream(allowedOrigins.split(",", -1))
                        .map(String::trim).filter(value -> !value.isEmpty()).toArray(String[]::new);
        if (origins.length == 0) {
            return;
        }
        registry.addMapping("/api/**")
                .allowedOrigins(origins)
                .allowedMethods("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
                .allowedHeaders("Content-Type", "X-CSRF-Token", "X-Request-ID", "Idempotency-Key")
                .exposedHeaders("X-Request-ID", "Retry-After")
                .allowCredentials(true)
                .maxAge(3600);
    }
}
