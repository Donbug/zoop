package com.zoop.auth.controller;

import com.zoop.auth.dto.SessionResponse;
import com.zoop.auth.dto.SocialSignupRequest;
import com.zoop.auth.service.MemberSessionService;
import com.zoop.auth.service.SessionCookie;
import com.zoop.auth.service.SocialAuthService;
import com.zoop.auth.service.SocialSignupService;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.exception.ErrorResponse;
import com.zoop.common.request.RequestIdFilter;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/auth/social/signup")
public class SocialSignupController {
    private final SocialSignupService signups;

    public SocialSignupController(SocialSignupService signups) {
        this.signups = signups;
    }

    @PostMapping
    public ResponseEntity<?> signup(@Valid @RequestBody SocialSignupRequest body,
            HttpServletRequest request) {
        var result = signups.signup(body, cookie(request, SocialAuthService.PENDING_COOKIE),
                cookie(request, SessionCookie.NAME), RequestIdFilter.currentId(request));
        if (result.isEmpty()) {
            return ResponseEntity.status(HttpStatus.CONFLICT)
                    .body(ErrorResponse.of(ErrorCode.SOCIAL_LINK_REQUIRED, RequestIdFilter.currentId(request)));
        }
        MemberSessionService.IssuedSession issued = result.orElseThrow();
        return ResponseEntity.status(HttpStatus.CREATED)
                .header(HttpHeaders.SET_COOKIE, issued.cookie().toString())
                .header(HttpHeaders.SET_COOKIE, clearPendingCookie())
                .body(issued.response());
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

    private static String clearPendingCookie() {
        return ResponseCookie.from(SocialAuthService.PENDING_COOKIE, "")
                .httpOnly(true).sameSite("Lax").path("/api/v1/auth/social")
                .maxAge(0).build().toString();
    }
}
