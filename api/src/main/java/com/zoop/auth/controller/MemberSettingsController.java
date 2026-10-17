package com.zoop.auth.controller;

import tools.jackson.databind.JsonNode;
import com.zoop.auth.config.MemberAuthorizationInterceptor;
import com.zoop.auth.dto.SettingsResponse;
import com.zoop.auth.service.MemberSettingsService;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.common.request.RequestIdFilter;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/me/settings")
public class MemberSettingsController {
    private final MemberSettingsService service;

    public MemberSettingsController(MemberSettingsService service) {
        this.service = service;
    }

    @GetMapping
    @Operation(summary = "회원 설정 조회")
    public ResponseEntity<SettingsResponse> get(HttpServletRequest request) {
        return ResponseEntity.ok(service.get(principal(request), RequestIdFilter.currentId(request)));
    }

    @PutMapping
    @Operation(summary = "초기 설정과 관심 종목 저장")
    public ResponseEntity<SettingsResponse> update(@RequestBody JsonNode body, HttpServletRequest request) {
        return ResponseEntity.ok(service.update(principal(request), body, RequestIdFilter.currentId(request)));
    }

    private static MemberPrincipal principal(HttpServletRequest request) {
        return (MemberPrincipal) request.getAttribute(MemberAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE);
    }
}
