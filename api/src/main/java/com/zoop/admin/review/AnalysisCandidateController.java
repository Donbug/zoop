package com.zoop.admin.review;

import com.zoop.admin.auth.config.AdminAuthorizationInterceptor;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.review.AnalysisCandidates.CandidateDetail;
import com.zoop.admin.review.AnalysisCandidates.CandidateList;
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

/**
 * A-ADM-03 candidate tab (#132, #133): the review targets the sync projected, one candidate read again from the AI source, and an
 * administrator's decision on one of its relations.
 */
@RestController
@RequestMapping("/api/v1/admin/pipeline/candidates")
public class AnalysisCandidateController {
    private final AnalysisCandidateService service;
    private final ReviewDecisionService decisions;

    public AnalysisCandidateController(AnalysisCandidateService service, ReviewDecisionService decisions) {
        this.service = service;
        this.decisions = decisions;
    }

    @GetMapping
    @Operation(operationId = "listAnalysisCandidates", summary = "검수 후보 목록 조회")
    public CandidateList list(@RequestParam(required = false) String status,
            @RequestParam(required = false) String decision, @RequestParam(required = false) Boolean active,
            @RequestParam(required = false) Boolean published, @RequestParam(required = false) Boolean rule,
            @RequestParam(required = false) String q, @RequestParam(required = false) String cursor,
            @RequestParam(required = false) Integer limit, HttpServletRequest request) {
        return service.list(principal(request).adminId(), status, decision, active, published, rule, q, cursor, limit,
                RequestIdFilter.currentId(request));
    }

    @GetMapping("/{candidateId}")
    @Operation(operationId = "getAnalysisCandidate", summary = "후보 근거와 검증 결과 조회")
    public CandidateDetail get(@PathVariable String candidateId, HttpServletRequest request) {
        return service.get(candidateId, RequestIdFilter.currentId(request));
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
