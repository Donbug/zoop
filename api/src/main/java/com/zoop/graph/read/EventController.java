package com.zoop.graph.read;

import com.zoop.common.request.RequestIdFilter;
import com.zoop.graph.read.dto.EventDetail;
import com.zoop.graph.read.dto.EventListResponse;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** OpenAPI {@code listEvents} and {@code getEvent}. */
@RestController
@RequestMapping("/api/v1/events")
public class EventController {
    private final EventListService service;
    private final EventDetailService details;

    public EventController(EventListService service, EventDetailService details) {
        this.service = service;
        this.details = details;
    }

    @GetMapping
    @Operation(summary = "기업·기간별 사건 타임라인 조회",
            description = "공개 그래프 버전 하나를 고정해 사건 목록을 반환합니다(asOf·graphVersion은 그래프 조회와 같은 규칙). "
                    + "companyId가 있으면 기업 시점 그래프와 같은 실제 연결선 수 depth(1 기본, 2) 안의 사건, 없으면 전체 사건이며 depth는 무시합니다. "
                    + "from/to는 KST 날짜(그날 전체) 또는 오프셋이 있는 시각(to는 그 시각 포함, 가격 조회와 같음)입니다. 승인된 사건 시각이 있는 사건은 그 기간(연·월·일은 KST 기준 그 기간 전체, "
                    + "시각은 그 시각)이 [from, to]와 겹치면 items에, 사건 시각이 없는 사건은 최신 기사 공개일(KST)이 범위 안이면 unknownTimeItems에 "
                    + "최신순으로 들어갑니다. from/to가 없으면 모든 사건이 items입니다. items(최신 사건순) 다음에 unknownTimeItems가 이어지는 한 순서에 "
                    + "limit·cursor를 적용해 두 배열을 합쳐 limit개씩 끝까지 받습니다. asOf를 생략해도 모든 페이지가 첫 페이지의 metadata.asOf를 유지합니다. relationTypes는 요청 기업과 사건 사이의 직접 간선 유형만입니다. "
                    + "reportedAt은 기사 공개 시각이 날짜만 있으면 null입니다(시각을 지어내지 않음). "
                    + "assertionStatus는 AI 인계 이슈의 사건 상태(occurred·announced·planned·forecast·cancelled·unknown)를 그대로 담고, 없으면 null입니다. "
                    + "없는 기업 404, 잘못된 입력 422, 잘못된 커서 422 INVALID_CURSOR, 고정 버전 없음 409, 스냅샷 읽기 실패 503입니다.")
    public EventListResponse listEvents(@RequestParam(required = false) String companyId,
            @RequestParam(required = false) Integer depth,
            @RequestParam(required = false) String from,
            @RequestParam(required = false) String to,
            @RequestParam(required = false) String cursor,
            @RequestParam(required = false) Integer limit,
            @RequestParam(required = false) String graphVersion,
            @RequestParam(required = false) String asOf) {
        return service.list(companyId, depth, from, to, cursor, limit, graphVersion, asOf);
    }

    @GetMapping("/{id}")
    @Operation(operationId = "getEvent", summary = "사건 상세와 근거 참조 조회",
            description = "공개 그래프 버전 하나를 고정해(round·asOf·graphVersion은 그래프 조회와 같은 규칙) 그 버전에서 보이는 사건 하나를 반환합니다. "
                    + "관계·기업·기사·선후 사건(follows)은 스냅샷에서, 원본 언급(mentions)·운영자 필드 판정(fieldDecisions)·출처 지지도(sourceSupport)는 "
                    + "수입한 버전의 receipt(AI 인계 묶음)에서 읽습니다. 수입한 버전은 근거마다 현재 공개 게이트(기사 접근·source grant)를 다시 적용해 "
                    + "읽을 수 없는 근거에 기대는 언급·기사·관계를 빼고, 대표 언급의 근거가 모두 가려지면 404입니다. 운영자가 보류·거절한 언급의 "
                    + "시각·기간은 null입니다. summary는 아직 생산자가 없어 unavailable이고 approval은 null입니다. 그 버전에서 보이지 않는 사건 404, "
                    + "잘못된 입력 422, 고정 버전 없음 409, 스냅샷·receipt 읽기 실패와 이전 인계 묶음 스키마 503입니다.")
    public EventDetail getEvent(@PathVariable String id, @RequestParam(required = false) String round,
            @RequestParam(required = false) String graphVersion, @RequestParam(required = false) String asOf,
            HttpServletRequest request) {
        return details.get(id, round, graphVersion, asOf, RequestIdFilter.currentId(request));
    }
}
