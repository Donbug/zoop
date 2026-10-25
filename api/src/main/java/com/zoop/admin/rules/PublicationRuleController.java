package com.zoop.admin.rules;

import com.zoop.admin.auth.config.AdminAuthorizationInterceptor;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.rules.PublicationRuleResponse.RuleList;
import com.zoop.admin.rules.PublicationRuleResponse.SwitchRequest;
import com.zoop.admin.rules.PublicationRuleResponse.SwitchResponse;
import com.zoop.common.request.RequestIdFilter;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Admin publication rules (#132 list, #133 switch). */
@RestController
@RequestMapping("/api/v1/admin/pipeline/rules")
public class PublicationRuleController {
    private final PublicationRuleService service;

    public PublicationRuleController(PublicationRuleService service) {
        this.service = service;
    }

    @GetMapping
    @Operation(operationId = "listPublicationRules", summary = "공개 검증 규칙 조회")
    public RuleList list(@RequestParam(required = false) String cursor, @RequestParam(required = false) Integer limit,
            HttpServletRequest request) {
        return service.list(principal(request).adminId(), cursor, limit);
    }

    @PutMapping("/{ruleId}")
    @Operation(operationId = "setPublicationRule", summary = "검증 규칙 목표 상태 설정")
    public SwitchResponse set(@PathVariable String ruleId, @Valid @RequestBody SwitchRequest body,
            HttpServletRequest request) {
        return service.set(ruleId, body, principal(request), RequestIdFilter.currentId(request));
    }

    private static AdminPrincipal principal(HttpServletRequest request) {
        Object principal = request.getAttribute(AdminAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE);
        if (principal instanceof AdminPrincipal admin) return admin;
        throw new IllegalStateException("AdminAuthorizationInterceptor must run before controller");
    }
}
