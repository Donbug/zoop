package com.zoop.auth.controller;

import com.zoop.auth.service.MemberSessionService;
import com.zoop.auth.service.SessionCookie;
import io.swagger.v3.oas.annotations.Operation;
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
    @Operation(summary = "현재 회원 세션 로그아웃",
            description = "유효한 회원 세션 쿠키가 있으면 허용 Origin과 세션 결합 X-CSRF-Token이 필요합니다. 세션이 없거나 무효이면 다른 세션을 변경하지 않고 204를 반환하며 회원 쿠키를 제거합니다.")
    public ResponseEntity<Void> logout(
            @CookieValue(name = SessionCookie.NAME, required = false) String token) {
        sessions.logoutMember(token);
        return ResponseEntity.noContent()
                .header(HttpHeaders.SET_COOKIE, sessions.clearCookie().toString())
                .build();
    }
}
