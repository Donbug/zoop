package com.zoop.portfolio.controller;

import tools.jackson.databind.JsonNode;
import com.zoop.auth.config.MemberAuthorizationInterceptor;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.request.RequestIdFilter;
import com.zoop.portfolio.dto.ConnectionResponse;
import com.zoop.portfolio.dto.MockPortfolioListResponse;
import com.zoop.portfolio.dto.MockProfileResponse;
import com.zoop.portfolio.dto.PortfolioResponse;
import com.zoop.portfolio.service.PortfolioService;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/portfolio")
public class PortfolioController {
    private final PortfolioService service;

    public PortfolioController(PortfolioService service) {
        this.service = service;
    }

    @GetMapping("/mock-portfolios")
    @Operation(summary = "가상 계좌 프로필 목록")
    public MockPortfolioListResponse listProfiles(@RequestParam(required = false) String cursor,
            @RequestParam(required = false) Integer limit, HttpServletRequest request) {
        return service.listProfiles(cursor, limit, RequestIdFilter.currentId(request));
    }

    @GetMapping("/mock-portfolios/{id}")
    @Operation(summary = "가상 계좌 프로필 조회")
    public MockProfileResponse getProfile(@PathVariable String id, HttpServletRequest request) {
        return service.getProfile(id, RequestIdFilter.currentId(request));
    }

    @PostMapping("/connections")
    @Operation(summary = "가상 계좌 연결",
            description = "프로젝트 고정 Mock 프로필만 연결한다. 실제 증권사 계정·인증정보를 사용하지 않는다.")
    public ResponseEntity<ConnectionResponse> connect(@RequestBody JsonNode body,
            @RequestHeader("Idempotency-Key") String idempotencyKey, HttpServletRequest request) {
        if (body == null || !body.isObject() || body.size() != 1 || !body.has("mockPortfolioId")
                || !body.get("mockPortfolioId").isTextual()) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        var response = service.connect(principal(request), body.get("mockPortfolioId").textValue(),
                idempotencyKey, RequestIdFilter.currentId(request));
        return ResponseEntity.status(HttpStatus.CREATED).body(response);
    }

    @DeleteMapping("/connections/{id}")
    @Operation(summary = "가상 계좌 연결 해제")
    public ResponseEntity<Void> disconnect(@PathVariable String id, HttpServletRequest request) {
        service.disconnect(principal(request), id);
        return ResponseEntity.noContent().build();
    }

    @GetMapping
    @Operation(summary = "모의 보유 정보 조회")
    public PortfolioResponse getMyPortfolio(HttpServletRequest request) {
        return service.getMyPortfolio(principal(request), RequestIdFilter.currentId(request));
    }

    private static MemberPrincipal principal(HttpServletRequest request) {
        return (MemberPrincipal) request.getAttribute(MemberAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE);
    }
}
