package com.zoop.admin.auth.controller;

import com.zoop.admin.auth.dto.AdminLoginRequest;
import com.zoop.admin.auth.dto.AdminSessionResponse;
import com.zoop.admin.auth.service.AdminLoginService;
import com.zoop.admin.auth.service.AdminAuthAuditService;
import com.zoop.admin.auth.service.AdminSessionCookie;
import com.zoop.admin.auth.service.AdminSessionService;
import com.zoop.common.request.RequestIdFilter;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/admin/auth")
public class AdminAuthController {
    private final AdminLoginService logins;
    private final AdminSessionService sessions;
    private final AdminAuthAuditService audit;

    public AdminAuthController(AdminLoginService logins, AdminSessionService sessions,
            AdminAuthAuditService audit) {
        this.logins = logins;
        this.sessions = sessions;
        this.audit = audit;
    }

    @GetMapping("/session")
    @Operation(summary = "관리자 세션 조회")
    public ResponseEntity<AdminSessionResponse> getAdminSession(
            HttpServletRequest request) {
        String token = AdminSessionCookie.token(request);
        var lookup = sessions.lookup(token, RequestIdFilter.currentId(request));
        ResponseEntity.BodyBuilder response = ResponseEntity.ok();
        if (lookup.clearCookie()) response.header(HttpHeaders.SET_COOKIE, sessions.clearCookie().toString());
        return response.body(lookup.response());
    }

    @PostMapping("/login")
    @Operation(summary = "관리자 로그인")
    public ResponseEntity<AdminSessionResponse> logInAdmin(@Valid @RequestBody AdminLoginRequest body,
            HttpServletRequest request) {
        String previousToken = AdminSessionCookie.token(request);
        var issued = logins.login(body, previousToken, RequestIdFilter.currentId(request));
        return ResponseEntity.ok().header(HttpHeaders.SET_COOKIE, issued.cookie().toString())
                .body(issued.response());
    }

    @PostMapping("/logout")
    @Operation(summary = "관리자 로그아웃")
    public ResponseEntity<Void> logOutAdmin(HttpServletRequest request) {
        String token = AdminSessionCookie.token(request);
        sessions.logout(token, RequestIdFilter.currentId(request),
                audit);
        return ResponseEntity.noContent().header(HttpHeaders.SET_COOKIE, sessions.clearCookie().toString()).build();
    }
}
