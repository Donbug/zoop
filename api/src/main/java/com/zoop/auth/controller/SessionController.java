package com.zoop.auth.controller;

import com.zoop.auth.dto.SessionResponse;
import com.zoop.auth.service.MemberSessionService;
import com.zoop.auth.service.SessionCookie;
import com.zoop.common.request.RequestIdFilter;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.CookieValue;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/auth/session")
public class SessionController {
    private final MemberSessionService service;

    public SessionController(MemberSessionService service) {
        this.service = service;
    }

    @GetMapping
    public ResponseEntity<SessionResponse> getSession(
            @CookieValue(name = SessionCookie.NAME, required = false) String token,
            HttpServletRequest request) {
        var lookup = service.lookup(token, RequestIdFilter.currentId(request));
        var response = ResponseEntity.ok();
        if (lookup.clearCookie()) {
            response.header(HttpHeaders.SET_COOKIE, SessionCookie.clear().toString());
        }
        return response.body(lookup.response());
    }
}
