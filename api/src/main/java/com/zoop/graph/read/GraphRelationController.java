package com.zoop.graph.read;

import com.zoop.common.request.RequestIdFilter;
import com.zoop.graph.read.dto.EdgeDetail;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** OpenAPI {@code getCompanyRelation}. */
@RestController
@RequestMapping("/api/v1/graph/edges/{id}")
public class GraphRelationController {
    private final GraphRelationService service;

    public GraphRelationController(GraphRelationService service) {
        this.service = service;
    }

    @GetMapping
    @Operation(summary = "기업 간 관계와 근거 조회",
            description = "그래프 간선 하나의 상세입니다. getGraph와 같은 규칙으로 공개 버전 하나를 고정해 읽으며(round·asOf·graphVersion), "
                    + "그 읽기에서 보이지 않는 간선(다른 버전, asOf 이후, 현재 공개 제외)은 404입니다. relationIds는 이 간선으로 묶인 원천 관계, "
                    + "basis는 구조 근거(사업 관계 유형·국가·근거 기사 URL)입니다. 승인된 관계는 verification=ALLOW, "
                    + "SHARES_ISSUE 파생 연결은 not_applicable이며 via에 공유 이슈와 그 근거를 담습니다. "
                    + "버전 없음 409, 잘못된 입력 422, 스냅샷 읽기 실패 503입니다.")
    public EdgeDetail getCompanyRelation(@PathVariable String id,
            @RequestParam(required = false) String round,
            @RequestParam(required = false) String graphVersion,
            @RequestParam(required = false) String asOf,
            HttpServletRequest request) {
        return service.getRelation(id, round, graphVersion, asOf, RequestIdFilter.currentId(request));
    }
}
