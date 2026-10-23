package com.zoop.admin.graph;

import com.zoop.admin.auth.config.AdminAuthorizationInterceptor;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.graph.GraphVersionAdminResponse.ActivateResponse;
import com.zoop.admin.graph.GraphVersionAdminResponse.GraphVersionList;
import com.zoop.common.request.RequestIdFilter;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/admin/graph/versions")
public class AdminGraphVersionController {
    private final AdminGraphVersionService service;

    public AdminGraphVersionController(AdminGraphVersionService service) {
        this.service = service;
    }

    @GetMapping
    @Operation(operationId = "listGraphVersions", summary = "공개 그래프 버전 목록 조회")
    public GraphVersionList list(@RequestParam(required = false) String cursor,
            @RequestParam(required = false) Integer limit) {
        return service.list(cursor, limit);
    }

    @PostMapping("/{versionId}/activate")
    @Operation(operationId = "activateGraphVersion", summary = "기존 공개 버전 활성화")
    public ActivateResponse activate(@PathVariable String versionId,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @Valid @RequestBody GraphVersionActivateRequest body, HttpServletRequest request) {
        return service.activate(versionId, body, idempotencyKey, principal(request), RequestIdFilter.currentId(request));
    }

    private static AdminPrincipal principal(HttpServletRequest request) {
        Object principal = request.getAttribute(AdminAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE);
        if (principal instanceof AdminPrincipal admin) return admin;
        throw new IllegalStateException("AdminAuthorizationInterceptor must run before controller");
    }
}
