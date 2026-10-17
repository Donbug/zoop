package com.zoop.auth.service;

import java.time.Duration;

import org.springframework.http.ResponseCookie;

public final class SessionCookie {
    public static final String NAME = "zoop_session";
    public static final Duration LIFETIME = Duration.ofHours(12);

    private SessionCookie() {
    }

    public static ResponseCookie issue(String token) {
        return issue(token, true);
    }

    public static ResponseCookie issue(String token, boolean secure) {
        return base(token, secure).maxAge(LIFETIME).build();
    }

    public static ResponseCookie clear() {
        return clear(true);
    }

    public static ResponseCookie clear(boolean secure) {
        return base("", secure).maxAge(Duration.ZERO).build();
    }

    private static ResponseCookie.ResponseCookieBuilder base(String value, boolean secure) {
        return ResponseCookie.from(NAME, value)
                .secure(secure).httpOnly(true).sameSite("Lax")
                .path("/api/v1");
    }
}
