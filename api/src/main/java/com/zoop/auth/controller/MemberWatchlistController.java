package com.zoop.auth.controller;

import tools.jackson.databind.JsonNode;
import com.zoop.auth.config.MemberAuthorizationInterceptor;
import com.zoop.auth.dto.SettingsResponse;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.auth.service.MemberSettingsService;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.request.RequestIdFilter;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/me/watchlist")
public class MemberWatchlistController {
    private final MemberSettingsService service;

    public MemberWatchlistController(MemberSettingsService service) {
        this.service = service;
    }

    @PutMapping("/{id}")
    @Operation(summary = "관심 종목 목표 상태 설정")
    public ResponseEntity<SettingsResponse> setCompany(@PathVariable String id,
            @RequestBody JsonNode body, HttpServletRequest request) {
        if (body == null || !body.isObject() || body.size() != 1 || !body.has("watched")
                || !body.get("watched").isBoolean()) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        return ResponseEntity.ok(service.setWatchlistCompany(principal(request), id,
                body.get("watched").booleanValue(), RequestIdFilter.currentId(request)));
    }

    private static MemberPrincipal principal(HttpServletRequest request) {
        return (MemberPrincipal) request.getAttribute(MemberAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE);
    }
}
