package com.zoop.auth.controller;

import com.zoop.auth.service.AuthClientIpResolver;
import com.zoop.auth.dto.SocialAuthorizationResponse;
import com.zoop.auth.dto.SocialLinkStartRequest;
import com.zoop.auth.dto.SocialProvidersResponse;
import com.zoop.auth.service.SocialAuthService;
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
