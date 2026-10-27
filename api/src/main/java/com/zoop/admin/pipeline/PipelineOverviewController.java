package com.zoop.admin.pipeline;

import com.zoop.admin.pipeline.PipelineOverviewResponse.Overview;
import io.swagger.v3.oas.annotations.Operation;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/admin/pipeline")
public class PipelineOverviewController {
    private final PipelineOverviewService service;

    public PipelineOverviewController(PipelineOverviewService service) {
        this.service = service;
    }

    @GetMapping("/overview")
    @Operation(operationId = "getPipelineOverview", summary = "수집·분석·공개 반영 상태 조회")
    public Overview overview() {
        return service.overview();
    }
}
