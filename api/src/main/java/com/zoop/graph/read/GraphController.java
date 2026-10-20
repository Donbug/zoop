package com.zoop.graph.read;

import com.zoop.auth.config.MemberAuthorizationInterceptor;
import com.zoop.auth.service.MemberSessionService;
import com.zoop.common.request.RequestIdFilter;
import com.zoop.graph.read.dto.GraphResponse;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * OpenAPI {@code getGraph}. All mode is public; personal mode needs a member session (none 401, guest 403) and reads
 * only that member's own holdings and watchlist. {@code personalFilter} is ignored in all mode.
 */
@RestController
@RequestMapping("/api/v1/graph")
public class GraphController {
    private final GraphQueryService service;
    private final MemberSessionService sessions;
    private final PersonalCompanies personalCompanies;

    public GraphController(GraphQueryService service, MemberSessionService sessions, PersonalCompanies personalCompanies) {
        this.service = service;
        this.sessions = sessions;
        this.personalCompanies = personalCompanies;
    }

    @GetMapping
    @Operation(summary = "전체·개인화·시점별 관계 그래프 조회",
            description = "기업/이슈 노드와 관계 간선을 반환합니다. 요청마다 공개 버전 하나를 고정하며, 생략하면 현재 활성 버전, "
                    + "asOf를 주면 그 시점에 활성이던 버전, graphVersion을 주면 공개된 적 있는 그 버전을 읽습니다(asOf와 함께면 일치해야 함). "
                    + "companyId는 기준 기업(관계 0건이어도 유지, 카탈로그에 없으면 404), depth는 기준 기업에서의 hop 수입니다(생략 시 연결된 전체). "
                    + "mode=all은 공개 경로이며 개인 정보를 담지 않습니다. mode=personal은 회원 세션이 필요하고(없으면 401, 비회원 403) "
                    + "본인의 모의 보유·관심 종목을 기준 기업으로 삼아 holding/watch를 표시합니다. personalFilter(all·holdings·watchlist)로 "
                    + "범위를 좁히며, 기준 기업이 없으면 emptyReason=no_personal_stocks입니다. 개인화 모드는 round를 받지 않습니다(422). "
                    + "버전 없음 409, 잘못된 입력 422, 스냅샷 읽기 실패 503이며 오류를 빈 그래프로 대체하지 않습니다. "
                    + "목표 명세는 docs/api/openapi.yaml을 참고하세요.")
    public GraphResponse getGraph(@RequestParam(required = false) String mode,
            @RequestParam(required = false) String companyId,
            @RequestParam(required = false) Integer depth,
            @RequestParam(required = false) String round,
            @RequestParam(required = false) String graphVersion,
            @RequestParam(required = false) String asOf,
            @RequestParam(required = false) String personalFilter,
            HttpServletRequest request) {
        PersonalCompanies.Ids personal = "personal".equals(mode)
                ? personalCompanies.of(sessions.requireMember(MemberAuthorizationInterceptor.sessionToken(request)))
                : null;
        return service.getGraph(mode, companyId, depth, round, graphVersion, asOf, personalFilter, personal,
                RequestIdFilter.currentId(request));
    }
}
