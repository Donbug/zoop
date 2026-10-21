package com.zoop.admin.audit;

import com.zoop.admin.auth.config.AdminAuthorizationInterceptor;
import com.zoop.admin.auth.service.AdminPrincipal;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/admin")
public class AdminAuditController {
    private final AdminAuditQueryService queries;

    public AdminAuditController(AdminAuditQueryService queries) {
        this.queries = queries;
    }

    @GetMapping("/audit-log")
    @Operation(operationId = "listAuditRecords", summary = "운영 감사 기록 조회")
    public AuditPage list(@RequestParam(required = false) String action,
            @RequestParam(required = false) String actor,
            @RequestParam(required = false) String targetType,
            @RequestParam(required = false) String q,
            @RequestParam(required = false) String cursor,
            @RequestParam(required = false) Integer limit,
            HttpServletRequest request) {
        Object principal = request.getAttribute(AdminAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE);
        if (!(principal instanceof AdminPrincipal admin)) {
            throw new IllegalStateException("AdminAuthorizationInterceptor must run before controller");
        }
        return queries.list(admin.adminId(), action, actor, targetType, q, cursor, limit);
    }
}
