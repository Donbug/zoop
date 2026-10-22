package com.zoop.briefing.controller;

import java.time.LocalDate;

import com.zoop.briefing.query.BriefingQueryService;
import com.zoop.common.request.RequestIdFilter;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.node.ObjectNode;

@RestController
@RequestMapping("/api/v1/briefings")
@Tag(name = "briefings", description = "공개된 회차의 저장 원문·이력·고정 그래프 기준 조회")
public class BriefingController {
    private final BriefingQueryService service;

    public BriefingController(BriefingQueryService service) { this.service = service; }

    @GetMapping
    @Operation(operationId = "getBriefing", summary = "공개 브리핑 회차 조회",
            description = "날짜를 생략하면 해당 구분의 DB 최신 회차를 조회합니다. 발행 당시 원문을 복원하며 재생성하지 않습니다. 생성 시작은 09:20·17:30 KST입니다.")
    @ApiResponse(responseCode = "200", description = "회차 상태와 저장된 공개 내용",
            content = @Content(mediaType = "application/json", schema = @Schema(implementation = BriefingHttpSchemas.BriefingResponse.class)))
    public ObjectNode getBriefing(
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate date,
            @RequestParam(required = false) @Schema(allowableValues = {"morning", "evening"}) String edition,
            HttpServletRequest request) {
        return service.get(date, edition, RequestIdFilter.currentId(request));
    }

    @GetMapping("/rounds")
    @Operation(operationId = "listBriefingRounds", summary = "공개 브리핑 이력 조회",
            description = "발행·제공 중단 회차의 메타데이터를 최신순으로 반환합니다. nextCursor와 같은 limit으로 다음 페이지를 조회합니다.")
    @ApiResponse(responseCode = "200", description = "공개 회차 이력",
            content = @Content(mediaType = "application/json", schema = @Schema(implementation = BriefingHttpSchemas.BriefingRoundsResponse.class)))
    public ObjectNode listBriefingRounds(@RequestParam(required = false) String cursor,
            @RequestParam(required = false) @Schema(minimum = "1", maximum = "100", defaultValue = "20") Integer limit) {
        return service.history(cursor, limit);
    }

    @GetMapping("/{id}/graph")
    @Operation(operationId = "getBriefingGraphBasis", summary = "발행 당시 그래프 기준 조회",
            description = "회차의 고정 버전을 반환합니다. 고정 그래프 조회가 준비되지 않았으면 unavailable이며 최신 그래프로 대체하지 않습니다.")
    @ApiResponse(responseCode = "200", description = "고정 그래프 기준과 가용 상태",
            content = @Content(mediaType = "application/json", schema = @Schema(implementation = BriefingHttpSchemas.BriefingGraphBasis.class)))
    public ObjectNode getBriefingGraphBasis(@PathVariable String id, HttpServletRequest request) {
        return service.graphBasis(id, RequestIdFilter.currentId(request));
    }

    @GetMapping("/{roundId}/items/{eventId}")
    @Operation(operationId = "getBriefingItemDetail", summary = "회차에 고정된 브리핑 항목과 근거 조회",
            description = "해당 발행 회차에 선정된 항목의 저장된 주장·선정 근거·정확 인용·동일 버전 원문 문맥을 복원합니다. 현재 원문 권한을 다시 검증하며 재생성하거나 최신 원문으로 바꾸지 않습니다.")
    @ApiResponse(responseCode = "200", description = "회차에 고정된 항목 상세",
            content = @Content(mediaType = "application/json", schema = @Schema(implementation = BriefingHttpSchemas.BriefingItemDetail.class)))
    @ApiResponse(responseCode = "404", description = "회차·항목 또는 저장된 상세가 없음")
    @ApiResponse(responseCode = "503", description = "현재 권한·원문 버전·저장 상세 검증 불가 또는 제공 중단")
    public ObjectNode getBriefingItemDetail(@PathVariable String roundId, @PathVariable String eventId,
            HttpServletRequest request) {
        return service.getItem(roundId, eventId, RequestIdFilter.currentId(request));
    }
}
