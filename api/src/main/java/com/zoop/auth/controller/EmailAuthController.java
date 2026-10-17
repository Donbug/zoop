package com.zoop.auth.controller;

import com.zoop.auth.dto.LoginRequest;
import com.zoop.auth.dto.SessionResponse;
import com.zoop.auth.dto.SignupRequest;
import com.zoop.auth.service.AuthAttemptGate;
import com.zoop.auth.service.LoginService;
import com.zoop.auth.service.SessionCookie;
import com.zoop.auth.service.SignupService;
import com.zoop.common.request.RequestIdFilter;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.CookieValue;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/auth")
public class EmailAuthController {
    private final AuthAttemptGate attempts;
    private final SignupService signups;
    private final LoginService logins;

    public EmailAuthController(AuthAttemptGate attempts, SignupService signups, LoginService logins) {
        this.attempts = attempts;
        this.signups = signups;
        this.logins = logins;
    }

    @PostMapping("/signup")
    @Operation(summary = "이메일 회원가입",
            description = "정확히 허용된 Origin이 필요합니다. 성공 시 201과 회원 세션 쿠키를 반환합니다. 요청·응답 계약의 목표 명세는 docs/api/openapi.yaml을 참고하세요.")
    public ResponseEntity<SessionResponse> signup(@Valid @RequestBody SignupRequest body,
            @CookieValue(name = SessionCookie.NAME, required = false) String previousToken,
            HttpServletRequest request) {
        var email = attempts.signup(request, body.email());
        var issued = signups.signup(body, email, previousToken, RequestIdFilter.currentId(request));
        return ResponseEntity.status(HttpStatus.CREATED)
                .header(HttpHeaders.SET_COOKIE, issued.cookie().toString())
                .body(issued.response());
    }

    @PostMapping("/login")
    @Operation(summary = "이메일 로그인",
            description = "정확히 허용된 Origin이 필요합니다. 성공 시 200과 회원 세션 쿠키를 반환합니다. 요청·응답 계약의 목표 명세는 docs/api/openapi.yaml을 참고하세요.")
    public ResponseEntity<SessionResponse> login(@Valid @RequestBody LoginRequest body,
            @CookieValue(name = SessionCookie.NAME, required = false) String previousToken,
            HttpServletRequest request) {
        var email = attempts.login(request, body.email());
        var issued = logins.login(email, body.password(), previousToken, RequestIdFilter.currentId(request));
        return ResponseEntity.ok()
                .header(HttpHeaders.SET_COOKIE, issued.cookie().toString())
                .body(issued.response());
    }
}
