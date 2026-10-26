package com.zoop.admin.review;

import com.zoop.admin.auth.config.AdminAuthorizationInterceptor;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.common.request.RequestIdFilter;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * A-ADM-03 candidate decision (#133, FS067-02): an administrator's final approval or rejection of one HOLD relation of a
 * candidate, sent to the AI source and settled by {@link ReviewDecisionService}. Kept apart from the read controller.
 */
@RestController
@RequestMapping("/api/v1/admin/pipeline/candidates")
public class AnalysisCandidateDecisionController {
    private final ReviewDecisionService decisions;

    public AnalysisCandidateDecisionController(ReviewDecisionService decisions) {
        this.decisions = decisions;
    }

    @PostMapping("/{candidateId}/decision")
    @Operation(operationId = "decideAnalysisCandidate", summary = "후보 거부 또는 운영자 최종 승인")
    public ReviewDecision.Response decide(@PathVariable String candidateId,
            @RequestHeader("Idempotency-Key") String idempotencyKey, @Valid @RequestBody ReviewDecision.Request body,
            HttpServletRequest request) {
        return decisions.decide(candidateId, body, idempotencyKey, principal(request), RequestIdFilter.currentId(request));
    }

    private static AdminPrincipal principal(HttpServletRequest request) {
        Object principal = request.getAttribute(AdminAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE);
        if (principal instanceof AdminPrincipal admin) return admin;
        throw new IllegalStateException("AdminAuthorizationInterceptor must run before controller");
    }
}
