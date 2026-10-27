package com.zoop.graph.read;

import com.zoop.common.request.RequestIdFilter;
import com.zoop.graph.read.dto.CompanyIssueImpactResponse;
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

    public CompanyIssueImpactController(CompanyIssueImpactService service) {
        this.service = service;
    }

    @GetMapping
    @Operation(summary = "기업 맥락 이슈 영향 경로 조회",
            description = "선택한 공개 그래프에서 이슈와 기업의 연결을 조회합니다. INVOLVES가 STRUCTURALLY_RELATED_TO보다 우선합니다. "
                    + "구조 사업 사슬과 영향 판정은 각각 제공 가능한 상태를 구분하며, 미생산 판정을 추정하지 않습니다. "
                    + "공개 연결 없음은 200 none, 대상 미공개는 404, 버전 없음은 409, 잘못된 입력은 422입니다.")
    public CompanyIssueImpactResponse getCompanyIssueImpact(@PathVariable String id, @PathVariable String issueId,
            @RequestParam(required = false) String round, @RequestParam(required = false) String graphVersion,
            @RequestParam(required = false) String asOf, HttpServletRequest request) {
        return service.getImpactPath(id, issueId, round, graphVersion, asOf, RequestIdFilter.currentId(request));
    }
}
