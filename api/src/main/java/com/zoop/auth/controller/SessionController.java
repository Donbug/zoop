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
    @Operation(summary = "현재 회원·비회원 세션 조회",
            description = "zoop_session 쿠키는 선택 사항입니다. 쿠키가 없거나 유효하지 않으면 anonymous 응답을 반환하며 세션을 새로 만들지 않습니다. Swagger UI는 HttpOnly 쿠키를 설정하지 않습니다.")
    public ResponseEntity<SessionResponse> getSession(
            @CookieValue(name = SessionCookie.NAME, required = false) String token,
            HttpServletRequest request) {
        var lookup = service.lookup(token, RequestIdFilter.currentId(request));
        var response = ResponseEntity.ok();
        if (lookup.clearCookie()) {
            response.header(HttpHeaders.SET_COOKIE, service.clearCookie().toString());
        }
        return response.body(lookup.response());
    }
}
