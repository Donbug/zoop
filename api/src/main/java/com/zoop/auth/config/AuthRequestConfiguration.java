package com.zoop.auth.config;

import com.zoop.auth.service.AuthClientIpResolver;
import com.zoop.auth.service.AuthOriginPolicy;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class AuthRequestConfiguration implements WebMvcConfigurer {
    private final AuthOriginInterceptor interceptor;
    private final MemberCsrfInterceptor memberCsrfInterceptor;
    private final MemberAuthorizationInterceptor memberAuthorizationInterceptor;

    public AuthRequestConfiguration(AuthOriginInterceptor interceptor,
            MemberCsrfInterceptor memberCsrfInterceptor,
            MemberAuthorizationInterceptor memberAuthorizationInterceptor) {
        this.interceptor = interceptor;
        this.memberCsrfInterceptor = memberCsrfInterceptor;
        this.memberAuthorizationInterceptor = memberAuthorizationInterceptor;
    }

    @Bean
    static AuthOriginPolicy authOriginPolicy(
            @Value("${zoop.auth.allowed-origins:${ZOOP_AUTH_ALLOWED_ORIGINS:}}") String origins,
            @Value("${zoop.auth.allow-http-loopback-origins:false}") boolean allowHttpLoopbackOrigins) {
        return new AuthOriginPolicy(origins, allowHttpLoopbackOrigins);
    }

    @Bean
    static AuthClientIpResolver authClientIpResolver(
            @Value("${ZOOP_AUTH_TRUSTED_PROXIES:}") String proxies) {
        return new AuthClientIpResolver(proxies);
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(interceptor).addPathPatterns(
                "/api/v1/auth/signup", "/api/v1/auth/login", "/api/v1/auth/guest", "/api/v1/auth/social/signup",
                "/api/v1/auth/social/*/link/authorize");
        registry.addInterceptor(memberCsrfInterceptor).addPathPatterns("/api/v1/**")
                .excludePathPatterns("/api/v1/auth/signup", "/api/v1/auth/login",
                        "/api/v1/auth/social/signup");
        registry.addInterceptor(memberAuthorizationInterceptor)
                .addPathPatterns("/api/v1/me/**", "/api/v1/portfolio", "/api/v1/portfolio/**",
                        "/api/v1/chat/**",
                        "/api/v1/feedback", "/api/v1/briefings/*/personalized",
                        "/api/v1/auth/tutorial");
    }
}
