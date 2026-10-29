package com.zoop.admin.briefings;

import com.zoop.admin.auth.config.AdminAuthorizationInterceptor;
import com.zoop.admin.auth.service.AdminPrincipal;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.node.ObjectNode;

/** A-ADM-04 / FS070-01. Reads never claim, generate, publish or change a round. */
@RestController
@RequestMapping("/api/v1/admin/briefings")
public class AdminBriefingController {
    private final AdminBriefingService service;

    public AdminBriefingController(AdminBriefingService service) { this.service = service; }

    @GetMapping
    @Operation(operationId = "listAdminBriefingRounds", summary = "브리핑 회차 운영 상태 목록")
    public ObjectNode list(@RequestParam(required = false) String from, @RequestParam(required = false) String to,
            @RequestParam(required = false) String cursor, @RequestParam(required = false) Integer limit,
            HttpServletRequest request) {
        AdminPrincipal admin = (AdminPrincipal) request.getAttribute(AdminAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE);
        return service.list(admin.adminId(), from, to, cursor, limit);
    }

    @GetMapping("/{roundId}")
    @Operation(operationId = "getAdminBriefingRound", summary = "브리핑 생성·검증·발행 상태 조회")
    public ObjectNode detail(@PathVariable String roundId) { return service.detail(roundId); }
}
