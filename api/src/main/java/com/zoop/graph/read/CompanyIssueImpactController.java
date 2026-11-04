package com.zoop.graph.read;

import com.zoop.common.request.RequestIdFilter;
import com.zoop.graph.read.dto.ImpactPath;
import com.zoop.graph.read.dto.CompanyIssueImpactAssessment;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** OpenAPI {@code getCompanyIssueImpact}. */
@RestController
@RequestMapping("/api/v1/companies/{id}/issues/{issueId}/impact")
public class CompanyIssueImpactController {
    private final CompanyIssueImpactService service;
    private final CompanyIssueImpactAssessmentService assessmentService;

    public CompanyIssueImpactController(CompanyIssueImpactService service, CompanyIssueImpactAssessmentService assessmentService) {
        this.service = service;
        this.assessmentService = assessmentService;
    }

    @GetMapping
    @Operation(operationId = "getCompanyIssueImpact", summary = "기업 맥락 이슈 영향 경로 조회",
            description = "고정된 공개 그래프에서 보이는 기업·이슈와 직접 INVOLVES 관계만 경로로 반환합니다. 관계가 없으면 빈 steps이며, 숨겨진 구조 경로나 추정 단계를 만들지 않습니다.")
    public ImpactPath getCompanyIssueImpact(@PathVariable String id, @PathVariable String issueId,
            @RequestParam(required = false) String round, @RequestParam(required = false) String graphVersion,
            @RequestParam(required = false) String asOf, HttpServletRequest request) {
        return service.getImpact(id, issueId, round, graphVersion, asOf, RequestIdFilter.currentId(request));
    }

    @GetMapping("/assessment")
    @Operation(operationId = "getCompanyIssueImpactAssessment", summary = "기업·이슈의 검증된 S3 영향 판정 조회",
            description = "선택한 공개 스냅샷의 직접 INVOLVES 관계에 기록된 검증 인용 효과만 반환합니다. 관계별 판정을 합산하지 않고, 제안 문구나 가격 예측을 반환하지 않습니다.")
    public CompanyIssueImpactAssessment getCompanyIssueImpactAssessment(@PathVariable String id, @PathVariable String issueId,
            @RequestParam(required = false) String round, @RequestParam(required = false) String graphVersion,
            @RequestParam(required = false) String asOf, HttpServletRequest request) {
        return assessmentService.get(id, issueId, round, graphVersion, asOf, RequestIdFilter.currentId(request));
    }
}
