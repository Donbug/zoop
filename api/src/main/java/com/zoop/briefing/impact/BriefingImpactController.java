package com.zoop.briefing.impact;

import com.zoop.common.request.RequestIdFilter;
import com.zoop.graph.read.BriefingImpactService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/briefings")
public class BriefingImpactController {
    private final BriefingImpactService service;
    private final BriefingImpactReviewService reviews;
    public BriefingImpactController(BriefingImpactService service, BriefingImpactReviewService reviews) { this.service = service; this.reviews=reviews; }

    @GetMapping("/{roundId}/items/{eventId}/impact-reviews")
    @Operation(operationId="getBriefingItemImpactReviews", summary="보존된 실제 인용으로 나중에 수행한 S3 재평가",
            description="원래 발행 당시 평가와 구분합니다. 고정된 입력/발행 해시·실행 receipt·현재 원문 권한을 검증하며 조회 시 AI 호출·기록 변경은 없습니다.")
    @ApiResponse(responseCode="200",description="사후 재평가 또는 명시적 미저장",
            content=@Content(mediaType="application/json",schema=@Schema(implementation=BriefingImpacts.class)))
    public BriefingImpacts reviews(@PathVariable String roundId,@PathVariable String eventId,
            @RequestParam(required=false) String graphVersion,HttpServletRequest request) {
        return reviews.get(roundId,eventId,graphVersion,RequestIdFilter.currentId(request));
    }

    @GetMapping("/{roundId}/items/{eventId}/impacts")
    @Operation(operationId = "getBriefingItemImpacts", summary = "회차 이슈의 기업별 S3 영향 평가·검증 근거",
            description = "발행 회차의 고정 그래프 receipt를 읽고 현재 권한을 재검증합니다. 검증된 인용별 효과만 표시하며 충돌 행을 합치거나 신규 AI를 호출하지 않습니다. 미저장·판단 유보·검증 실패를 구분합니다.")
    @ApiResponse(responseCode = "200", description = "저장된 평가 또는 명시적 미제공 상태",
            content = @Content(mediaType = "application/json", schema = @Schema(implementation = BriefingImpacts.class)))
    @ApiResponse(responseCode = "404", description = "회차 또는 선정 이슈 없음")
    @ApiResponse(responseCode = "422", description = "회차와 요청 그래프 버전 불일치")
    @ApiResponse(responseCode = "503", description = "현재 권한·저장본·receipt 검증 불가")
    public BriefingImpacts get(@PathVariable String roundId, @PathVariable String eventId,
            @RequestParam(required = false) String graphVersion, HttpServletRequest request) {
        return service.get(roundId, eventId, graphVersion, RequestIdFilter.currentId(request));
    }
}
