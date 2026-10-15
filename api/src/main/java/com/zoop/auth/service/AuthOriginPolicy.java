package com.zoop.auth.service;

import java.net.URI;
import java.util.Arrays;
import java.util.Set;
import java.util.stream.Collectors;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import jakarta.servlet.http.HttpServletRequest;

/** Exact HTTPS Origin allowlist. An empty list denies all auth writes. */
public final class AuthOriginPolicy {
    private final Set<String> allowed;

    public AuthOriginPolicy(String csv) {
        if (csv == null || csv.isBlank()) {
            allowed = Set.of();
            return;
        }
        allowed = Arrays.stream(csv.split(",", -1)).map(String::trim).map(AuthOriginPolicy::validate)
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

    private static String validate(String value) {
        try {
            URI uri = URI.create(value);
            if (!"https".equals(uri.getScheme()) || uri.getHost() == null
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

    private static CustomException denied() {
        return new CustomException(ErrorCode.ACCESS_DENIED);
    }
}
