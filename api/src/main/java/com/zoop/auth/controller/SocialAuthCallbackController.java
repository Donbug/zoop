package com.zoop.auth.controller;

import com.zoop.auth.service.SocialAuthCallbackService;
import com.zoop.auth.service.SocialAuthService;
import com.zoop.common.request.RequestIdFilter;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/auth/social/{provider}/callback")
public class SocialAuthCallbackController {
    private final SocialAuthCallbackService callbacks;

    public SocialAuthCallbackController(SocialAuthCallbackService callbacks) {
        this.callbacks = callbacks;
    }

    @GetMapping
    public ResponseEntity<Void> callback(@PathVariable String provider, HttpServletRequest request) {
        return callbacks.callback(provider, single(request, "state"), single(request, "code"),
                single(request, "error"), pendingCookie(request), cookie(request, "zoop_session"),
                RequestIdFilter.currentId(request));
    }

    private static String single(HttpServletRequest request, String key) {
        String[] values = request.getParameterValues(key);
        if (values == null || values.length == 0) return null;
        return values.length == 1 ? values[0] : "!duplicate!";
    }

    private static String pendingCookie(HttpServletRequest request) {
        return cookie(request, SocialAuthService.PENDING_COOKIE);
    }

    private static String cookie(HttpServletRequest request, String name) {
        Cookie[] cookies = request.getCookies();
        if (cookies == null) return null;
        String value = null;
        for (Cookie cookie : cookies) {
            if (!name.equals(cookie.getName())) continue;
            if (value != null) return "!duplicate!";
            value = cookie.getValue();
        }
        return value;
    }
}
