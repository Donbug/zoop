package com.zoop.auth.config;

import com.zoop.auth.service.AuthClientIpResolver;
import com.zoop.auth.service.AuthOriginPolicy;
import com.zoop.auth.service.AuthRateLimiter;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

@Component
public class AuthOriginInterceptor implements HandlerInterceptor {
    private final AuthOriginPolicy policy;
    private final AuthClientIpResolver clientIps;
    private final AuthRateLimiter rates;

    public AuthOriginInterceptor(AuthOriginPolicy policy, AuthClientIpResolver clientIps,
            AuthRateLimiter rates) {
        this.policy = policy;
        this.clientIps = clientIps;
        this.rates = rates;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        if ("POST".equals(request.getMethod())) {
            policy.verify(request);
            String path = request.getRequestURI().substring(request.getContextPath().length());
            String ip = clientIps.resolve(request);
            if ("/api/v1/auth/signup".equals(path)) {
                rates.recordSignupIpAttempt(ip);
            } else if ("/api/v1/auth/login".equals(path)) {
                rates.recordLoginIpAttempt(ip);
            }
        }
        return true;
    }
}
