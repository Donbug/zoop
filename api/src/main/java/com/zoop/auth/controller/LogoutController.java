package com.zoop.auth.controller;

import com.zoop.auth.service.MemberSessionService;
import com.zoop.auth.service.SessionCookie;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.CookieValue;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/auth/logout")
public class LogoutController {
    private final MemberSessionService sessions;

    public LogoutController(MemberSessionService sessions) {
        this.sessions = sessions;
    }

    @PostMapping
    public ResponseEntity<Void> logout(
            @CookieValue(name = SessionCookie.NAME, required = false) String token) {
        sessions.logoutMember(token);
        return ResponseEntity.noContent()
                .header(HttpHeaders.SET_COOKIE, SessionCookie.clear().toString())
                .build();
    }
}
