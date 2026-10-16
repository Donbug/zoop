package com.zoop.common.config;

import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;
import org.springframework.web.filter.CorsFilter;
import org.springframework.web.servlet.config.annotation.CorsRegistry;

import static org.assertj.core.api.Assertions.assertThat;

class ApiCorsConfigurationTest {
    @Test
    void frontendPreflightWorksForCompanyApiWithCredentials() throws Exception {
        var response = preflight("http://localhost:3000", "http://localhost:3000");

        assertThat(response.getStatus()).isEqualTo(200);
        assertThat(response.getHeader("Access-Control-Allow-Origin")).isEqualTo("http://localhost:3000");
        assertThat(response.getHeader("Access-Control-Allow-Credentials")).isEqualTo("true");
        assertThat(response.getHeader("Access-Control-Allow-Methods")).contains("POST");
        assertThat(response.getHeader("Access-Control-Allow-Headers")).containsIgnoringCase("X-CSRF-Token");
    }

    @Test
    void otherOriginsCannotPreflightCompanyApi() throws Exception {
        var response = preflight("http://localhost:3000", "http://localhost:3001");

        assertThat(response.getStatus()).isEqualTo(403);
        assertThat(response.getHeader("Access-Control-Allow-Origin")).isNull();
    }

    @Test
    void noOriginsConfiguredAddsNoCorsMapping() {
        var registry = new InspectableCorsRegistry();

        new ApiCorsConfiguration("").addCorsMappings(registry);

        assertThat(registry.configurations()).isEmpty();
    }

    private MockHttpServletResponse preflight(String configuredOrigin, String requestOrigin) throws Exception {
        var registry = new InspectableCorsRegistry();
        new ApiCorsConfiguration(configuredOrigin).addCorsMappings(registry);
        var source = new UrlBasedCorsConfigurationSource();
        registry.configurations().forEach(source::registerCorsConfiguration);
        var filter = new CorsFilter(source);
        var request = new MockHttpServletRequest("OPTIONS", "/api/v1/companies");
        request.addHeader("Origin", requestOrigin);
        request.addHeader("Access-Control-Request-Method", "POST");
        request.addHeader("Access-Control-Request-Headers", "content-type,x-csrf-token");
        var response = new MockHttpServletResponse();

        filter.doFilter(request, response, new MockFilterChain());
        return response;
    }

    private static final class InspectableCorsRegistry extends CorsRegistry {
        Map<String, CorsConfiguration> configurations() {
            return getCorsConfigurations();
        }
    }
}
