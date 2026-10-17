package com.zoop.admin.auth.service;

import java.time.Duration;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.ResponseCookie;

public final class AdminSessionCookie {
    public static final String NAME = "zoop_admin_session";

    private AdminSessionCookie() {
    }

    public static ResponseCookie issue(String token, Duration lifetime, boolean secure) {
        return base(token, secure).maxAge(lifetime).build();
    }

    public static ResponseCookie clear(boolean secure) {
        return base("", secure).maxAge(Duration.ZERO).build();
    }

    public static String token(HttpServletRequest request) {
        String token = null;
        if (request.getCookies() != null) {
            for (Cookie cookie : request.getCookies()) {
                if (NAME.equals(cookie.getName())) {
                    if (token != null) throw new CustomException(ErrorCode.ACCESS_DENIED);
                    token = cookie.getValue();
                }
            }
        }
        return token;
    }

    private static ResponseCookie.ResponseCookieBuilder base(String value, boolean secure) {
        return ResponseCookie.from(NAME, value).secure(secure).httpOnly(true)
                .sameSite("Lax").path("/api/v1");
    }
}
