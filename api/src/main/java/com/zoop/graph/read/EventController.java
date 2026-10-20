package com.zoop.graph.read;

import com.zoop.graph.read.dto.EventListResponse;
import io.swagger.v3.oas.annotations.Operation;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** OpenAPI {@code listEvents}. */
@RestController
@RequestMapping("/api/v1/events")
public class EventController {
    private final EventListService service;

    public EventController(EventListService service) {
        this.service = service;
    }

    @GetMapping
    @Operation(summary = "기업·기간별 사건 타임라인 조회",
            description = "공개 그래프 버전 하나를 고정해 사건 목록을 반환합니다(asOf·graphVersion은 그래프 조회와 같은 규칙). "
                    + "companyId가 있으면 기업 시점 그래프와 같은 실제 연결선 수 depth(1 기본, 2) 안의 사건, 없으면 전체 사건이며 depth는 무시합니다. "
                    + "from/to는 KST 날짜(그날 전체) 또는 오프셋이 있는 시각(to는 그 시각 포함, 가격 조회와 같음)입니다. 승인된 사건 시각이 있는 사건은 그 기간(연·월·일은 KST 기준 그 기간 전체, "
                    + "시각은 그 시각)이 [from, to]와 겹치면 items에, 사건 시각이 없는 사건은 최신 기사 공개일(KST)이 범위 안이면 unknownTimeItems에 "
                    + "최신순으로 들어갑니다. from/to가 없으면 모든 사건이 items입니다. items는 최신 사건순이며 limit·cursor로 나눠 받고, "
                    + "unknownTimeItems는 첫 페이지에만 담습니다. relationTypes는 요청 기업과 사건 사이의 직접 간선 유형만입니다. "
                    + "reportedAt은 기사 공개 시각이 날짜만 있으면 null입니다(시각을 지어내지 않음). "
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
}
