package com.zoop.auth.service;

import java.time.Duration;

import org.springframework.http.ResponseCookie;

public final class SessionCookie {
    public static final String NAME = "zoop_session";
    public static final Duration LIFETIME = Duration.ofHours(12);

    private SessionCookie() {
    }

    public static ResponseCookie issue(String token) {
        return base(token).maxAge(LIFETIME).build();
    }

    public static ResponseCookie clear() {
        return base("").maxAge(Duration.ZERO).build();
    }

    private static ResponseCookie.ResponseCookieBuilder base(String value) {
        return ResponseCookie.from(NAME, value)
                .secure(true).httpOnly(true).sameSite("Lax")
                .path("/api/v1");
    }
}
