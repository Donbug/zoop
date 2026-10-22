package com.zoop.admin.jobs;

import com.zoop.admin.auth.config.AdminAuthorizationInterceptor;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.jobs.AnalysisJobResponse.JobCreated;
import com.zoop.admin.jobs.AnalysisJobResponse.JobList;
import com.zoop.admin.jobs.AnalysisJobResponse.JobOut;
import com.zoop.common.request.RequestIdFilter;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

/** Admin analysis jobs (#132 list/get, #133 cancel/retry). {@code createAnalysisJob} waits for the job worker. */
@RestController
@RequestMapping("/api/v1/admin/jobs")
public class AnalysisJobController {
    private final AnalysisJobService service;

    public AnalysisJobController(AnalysisJobService service) {
        this.service = service;
    }

    @GetMapping
    @Operation(operationId = "listAnalysisJobs", summary = "분석·수집·재검증 작업 목록 조회")
    public JobList list(@RequestParam(required = false) String status) {
        return service.list(status);
    }

    @GetMapping("/{jobId}")
    @Operation(operationId = "getAnalysisJob", summary = "분석 작업 상세 조회")
    public JobOut get(@PathVariable String jobId) {
        return service.get(jobId);
    }

    @PostMapping("/{jobId}/retry")
    @ResponseStatus(HttpStatus.ACCEPTED)
    @Operation(operationId = "retryAnalysisJob", summary = "허용된 분석 작업 재시도")
    public JobCreated retry(@PathVariable String jobId, @RequestHeader("Idempotency-Key") String idempotencyKey,
            @Valid @RequestBody JobReasonRequest body, HttpServletRequest request) {
        return service.retry(jobId, body, idempotencyKey, principal(request), RequestIdFilter.currentId(request));
    }

    @PostMapping("/{jobId}/cancel")
    @Operation(operationId = "cancelAnalysisJob", summary = "분석 작업 명시적 취소")
    public JobOut cancel(@PathVariable String jobId, @RequestHeader("Idempotency-Key") String idempotencyKey,
            @Valid @RequestBody JobReasonRequest body, HttpServletRequest request) {
        return service.cancel(jobId, body, idempotencyKey, principal(request), RequestIdFilter.currentId(request));
    }

    private static AdminPrincipal principal(HttpServletRequest request) {
        Object principal = request.getAttribute(AdminAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE);
        if (principal instanceof AdminPrincipal admin) return admin;
        throw new IllegalStateException("AdminAuthorizationInterceptor must run before controller");
    }
}
