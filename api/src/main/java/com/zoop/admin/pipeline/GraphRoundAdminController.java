package com.zoop.admin.pipeline;

import com.zoop.admin.pipeline.GraphRoundAdminResponse.GraphRoundDetail;
import com.zoop.admin.pipeline.GraphRoundAdminResponse.GraphRoundList;
import io.swagger.v3.oas.annotations.Operation;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** The round-level view of A-ADM-03 (#55): rounds and their timelines, read-only. Retry and manual start follow with the scheduler. */
@RestController
@RequestMapping("/api/v1/admin/pipeline/rounds")
public class GraphRoundAdminController {
    private final GraphRoundAdminService service;

    public GraphRoundAdminController(GraphRoundAdminService service) {
        this.service = service;
    }

    @GetMapping
    @Operation(operationId = "listGraphRounds", summary = "그래프 정기 회차 목록 조회")
    public GraphRoundList list(@RequestParam(required = false) String stage, @RequestParam(required = false) String cursor,
            @RequestParam(required = false) Integer limit) {
        return service.list(stage, cursor, limit);
    }

    @GetMapping("/{roundId}")
    @Operation(operationId = "getGraphRound", summary = "그래프 정기 회차 상세·이력 조회")
    public GraphRoundDetail get(@PathVariable String roundId) {
        return service.get(roundId);
    }
}
