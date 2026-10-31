package com.zoop.briefing.personal;
import com.zoop.auth.config.MemberAuthorizationInterceptor;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.common.request.RequestIdFilter;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.*;
import tools.jackson.databind.node.ObjectNode;

@RestController
@Tag(name="briefings")
public class PersonalBriefingController {
    private final PersonalBriefingService service;
    public PersonalBriefingController(PersonalBriefingService service){this.service=service;}
    @GetMapping("/api/v1/briefings/{id}/personalized/issues")
    @Operation(operationId="getPersonalizedBriefingIssues",summary="보유·관심 종목 관련 이슈 최대 3개",
        description="회원 본인의 현재 보유·관심 종목과 회차의 전체 적격 후보를 사용합니다. 공통 발행 원문은 변경하지 않습니다. 중요도·새 정보 우선, 같은 사건 중복 제외, 이전 이슈+기업 단위 추적. 저장본이 없으면 pool_unavailable입니다. AI·시세 공급자를 호출하지 않습니다.")
    @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode="200",description="개인화 선정 결과와 가용 상태",
        content=@io.swagger.v3.oas.annotations.media.Content(schema=@io.swagger.v3.oas.annotations.media.Schema(implementation=PersonalBriefingHttpSchemas.Selection.class)))
    public ObjectNode get(@PathVariable String id,HttpServletRequest request,jakarta.servlet.http.HttpServletResponse response){
        response.setHeader("Cache-Control","no-store");
        response.setHeader("Vary","Cookie");
        return service.get(id,(MemberPrincipal)request.getAttribute(MemberAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE),RequestIdFilter.currentId(request));
    }
}
