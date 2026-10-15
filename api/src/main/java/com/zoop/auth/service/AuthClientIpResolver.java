package com.zoop.auth.service;

import java.net.InetAddress;
import java.net.UnknownHostException;
import java.util.Arrays;
import java.util.Set;
import java.util.stream.Collectors;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import jakarta.servlet.http.HttpServletRequest;

/** Walk X-Forwarded-For from the nearest trusted proxy toward the client. */
public final class AuthClientIpResolver {
    private final Set<String> trustedProxies;

    public AuthClientIpResolver(String csv) {
        trustedProxies = csv == null || csv.isBlank() ? Set.of()
                : Arrays.stream(csv.split(",", -1)).map(String::trim)
                        .map(AuthClientIpResolver::numericIp).collect(Collectors.toUnmodifiableSet());
    }

    public String resolve(HttpServletRequest request) {
        String current = numericIp(request.getRemoteAddr());
        if (!trustedProxies.contains(current)) {
            return current;
        }
        var headers = request.getHeaders("X-Forwarded-For");
        if (!headers.hasMoreElements()) {
            return current;
        }
        String forwarded = headers.nextElement();
        if (headers.hasMoreElements() || forwarded == null || forwarded.isBlank()
                || forwarded.length() > 1024) {
            throw new CustomException(ErrorCode.ACCESS_DENIED);
        }
        String[] hops = forwarded.split(",", -1);
        if (hops.length > 20) {
            throw new CustomException(ErrorCode.ACCESS_DENIED);
        }
        for (int i = hops.length - 1; i >= 0 && trustedProxies.contains(current); i--) {
            try {
                current = numericIp(hops[i].trim());
            } catch (IllegalArgumentException exception) {
                throw new CustomException(ErrorCode.ACCESS_DENIED);
            }
        }
        return current;
    }

    private static String numericIp(String value) {
        if (value == null || !(value.matches("[0-9]{1,3}(\\.[0-9]{1,3}){3}")
                || value.contains(":") && value.matches("[0-9A-Fa-f:.]+"))) {
            throw new IllegalArgumentException("Invalid proxy IP configuration");
        }
        try {
            return InetAddress.getByName(value).getHostAddress();
        } catch (UnknownHostException exception) {
            throw new IllegalArgumentException("Invalid proxy IP configuration");
        }
    }
}
