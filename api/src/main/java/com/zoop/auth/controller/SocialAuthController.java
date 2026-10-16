package com.zoop.auth.controller;

import com.zoop.auth.service.AuthClientIpResolver;
import com.zoop.auth.dto.SocialAuthorizationResponse;
import com.zoop.auth.dto.SocialLinkStartRequest;
import com.zoop.auth.dto.SocialProvidersResponse;
import com.zoop.auth.service.SocialAuthService;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.CookieValue;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/auth/social")
public class SocialAuthController {
    private final SocialAuthService service;
    private final AuthClientIpResolver clientIps;

    public SocialAuthController(SocialAuthService service, AuthClientIpResolver clientIps) {
        this.service = service;
        this.clientIps = clientIps;
    }

    @GetMapping("/providers")
    public SocialProvidersResponse providers(@RequestParam(required = false) String cursor,
            @RequestParam(required = false) Integer limit) {
        return service.listProviders(cursor, limit);
    }

    @GetMapping("/{provider}/authorize")
    public ResponseEntity<Void> authorize(@PathVariable String provider,
            @RequestParam(required = false) String returnTo,
            @CookieValue(name = SocialAuthService.PENDING_COOKIE, required = false) String pendingCookie,
            HttpServletRequest request) {
        return service.authorize(provider, returnTo, clientIps.resolve(request), pendingCookie);
    }

    @PostMapping("/{provider}/link/authorize")
    @Operation(summary = "기존 회원 계정에 소셜 제공자 연결 시작",
            description = "회원 세션, 세션 결합 X-CSRF-Token, 허용 Origin이 함께 필요합니다. Swagger UI에서는 HttpOnly 세션 쿠키를 설정할 수 없으므로 이 UI에서 직접 실행할 수 없습니다.")
    public ResponseEntity<SocialAuthorizationResponse> authorizeLink(@PathVariable String provider,
            @RequestBody SocialLinkStartRequest body,
            @CookieValue(name = SocialAuthService.PENDING_COOKIE, required = false) String pendingCookie,
            @CookieValue(name = "zoop_session", required = false) String sessionCookie,
            @RequestHeader(name = "X-CSRF-Token", required = false) String csrfToken,
            HttpServletRequest request) {
        return service.authorizeLink(provider, body.returnTo(), clientIps.resolve(request), pendingCookie,
                sessionCookie, csrfToken);
    }
}
