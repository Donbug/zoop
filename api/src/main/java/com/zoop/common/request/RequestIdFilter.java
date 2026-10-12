package com.zoop.common.request;

import java.io.IOException;
import java.util.UUID;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.MDC;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
public class RequestIdFilter extends OncePerRequestFilter {
    public static final String HEADER = "X-Request-ID";
    public static final String ATTRIBUTE = RequestIdFilter.class.getName() + ".requestId";

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String suppliedId = request.getHeader(HEADER);
        String requestId = suppliedId == null || suppliedId.isBlank() ? UUID.randomUUID().toString() : suppliedId;
        request.setAttribute(ATTRIBUTE, requestId);
        response.setHeader(HEADER, requestId);
        MDC.put("requestId", requestId);
        try {
            chain.doFilter(request, response);
        } finally {
            MDC.remove("requestId");
        }
    }

    public static String currentId(HttpServletRequest request) {
        Object requestId = request.getAttribute(ATTRIBUTE);
        if (requestId instanceof String id) {
            return id;
        }
        throw new IllegalStateException("RequestIdFilter must run before error handling");
    }
}
