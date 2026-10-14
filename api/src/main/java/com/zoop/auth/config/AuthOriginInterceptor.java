package com.zoop.auth.config;

import com.zoop.auth.service.AuthOriginPolicy;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

@Component
public class AuthOriginInterceptor implements HandlerInterceptor {
    private final AuthOriginPolicy policy;

    public AuthOriginInterceptor(AuthOriginPolicy policy) {
        this.policy = policy;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        if ("POST".equals(request.getMethod())) {
            policy.verify(request);
        }
        return true;
    }
}
