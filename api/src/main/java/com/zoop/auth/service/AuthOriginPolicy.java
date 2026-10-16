package com.zoop.auth.service;

import java.net.URI;
import java.util.Arrays;
import java.util.Set;
import java.util.stream.Collectors;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import jakarta.servlet.http.HttpServletRequest;

/** Exact Origin allowlist. HTTP is accepted only for loopback origins when explicitly enabled. */
public final class AuthOriginPolicy {
    private final Set<String> allowed;

    public AuthOriginPolicy(String csv) {
        this(csv, false);
    }

    public AuthOriginPolicy(String csv, boolean allowHttpLoopbackOrigins) {
        if (csv == null || csv.isBlank()) {
            allowed = Set.of();
            return;
        }
        allowed = Arrays.stream(csv.split(",", -1)).map(String::trim)
                .map(value -> validate(value, allowHttpLoopbackOrigins))
                .collect(Collectors.toUnmodifiableSet());
    }

    public void verify(HttpServletRequest request) {
        var headers = request.getHeaders("Origin");
        if (!headers.hasMoreElements()) {
            throw denied();
        }
        String origin = headers.nextElement();
        if (headers.hasMoreElements() || !allowed.contains(origin)) {
            throw denied();
        }
    }

    private static String validate(String value, boolean allowHttpLoopbackOrigins) {
        try {
            URI uri = URI.create(value);
            boolean https = "https".equals(uri.getScheme());
            boolean localHttp = allowHttpLoopbackOrigins && "http".equals(uri.getScheme())
                    && isLoopbackHost(uri.getHost());
            if ((!https && !localHttp) || uri.getHost() == null
                    || uri.getUserInfo() != null || uri.getRawQuery() != null
                    || uri.getRawFragment() != null || uri.getRawPath() != null && !uri.getRawPath().isEmpty()
                    || uri.getPort() > 65535 || uri.getPort() == 0 || value.contains("*")) {
                throw new IllegalArgumentException("Invalid auth Origin configuration");
            }
            return value;
        } catch (IllegalArgumentException exception) {
            throw new IllegalArgumentException("Invalid auth Origin configuration");
        }
    }

    private static boolean isLoopbackHost(String host) {
        return "localhost".equalsIgnoreCase(host) || "127.0.0.1".equals(host)
                || "::1".equals(host) || "[::1]".equals(host);
    }

    private static CustomException denied() {
        return new CustomException(ErrorCode.ACCESS_DENIED);
    }
}
