package com.zoop.auth.controller;

import com.zoop.auth.dto.SessionResponse;
import com.zoop.auth.service.MemberSessionService;
import com.zoop.auth.service.SessionCookie;
import com.zoop.common.request.RequestIdFilter;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.CookieValue;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/auth/guest")
public class GuestSessionController {
    private final MemberSessionService sessions;

    public GuestSessionController(MemberSessionService sessions) {
        this.sessions = sessions;
    }

    @PostMapping
    @Operation(summary = "비회원 세션 시작",
            description = "정확히 허용된 Origin이 필요합니다. 성공 시 200과 비회원 세션 쿠키를 반환합니다.")
    public ResponseEntity<SessionResponse> start(
            @CookieValue(name = SessionCookie.NAME, required = false) String previousToken,
            HttpServletRequest request) {
        var issued = sessions.issueGuest(previousToken, RequestIdFilter.currentId(request));
        return ResponseEntity.ok()
                .header(HttpHeaders.SET_COOKIE, issued.cookie().toString())
                .body(issued.response());
    }
}
