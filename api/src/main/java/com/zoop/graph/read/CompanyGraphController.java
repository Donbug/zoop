package com.zoop.graph.read;

import com.zoop.common.request.RequestIdFilter;
import com.zoop.graph.read.dto.GraphResponse;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** OpenAPI {@code getCompanyGraphAsOf}. */
@RestController
@RequestMapping("/api/v1/companies/{id}/graph")
public class CompanyGraphController {
    private final GraphQueryService service;

    public CompanyGraphController(GraphQueryService service) {
        this.service = service;
    }

    @GetMapping
    @Operation(summary = "기업·기준 시점 중심 관계 그래프 조회",
            description = "타임라인에서 고른 시각(asOf, RFC 3339 오프셋 필수)에 공개돼 있던 기업·이슈 관계만 반환합니다. "
                    + "그 시점에 활성이던 공개 버전 하나를 고정하고(graphVersion을 주면 일치해야 함), 이후 공개된 문서·관계는 섞지 않습니다. "
                    + "depth는 기준 기업에서 실제 연결선 수(1: 기업과 그 이슈, 2: 그 이슈의 다른 기업·후속 이슈까지, 기본 1)이며 "
                    + "SHARES_ISSUE 파생선은 세지 않습니다. 기준 기업은 관계 0건이어도 유지하고, 카탈로그에 없으면 404입니다. "
                    + "그 시점의 공개 버전이 없으면 409, 잘못된 입력 422, 스냅샷 읽기 실패 503이며 빈 그래프로 대체하지 않습니다.")
    public GraphResponse getCompanyGraphAsOf(@PathVariable String id,
            @RequestParam(required = false) String asOf,
            @RequestParam(required = false) Integer depth,
            @RequestParam(required = false) String graphVersion,
            HttpServletRequest request) {
        return service.getCompanyGraphAsOf(id, asOf, depth, graphVersion, RequestIdFilter.currentId(request));
    }
}
