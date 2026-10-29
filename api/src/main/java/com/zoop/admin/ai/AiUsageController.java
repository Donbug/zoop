package com.zoop.admin.ai;

import io.swagger.v3.oas.annotations.Operation;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** The admin authorization interceptor protects this route with admin:all. */
@RestController
@RequestMapping("/api/v1/admin/ai-usage")
public class AiUsageController {
    private final AiUsageService usage;

    public AiUsageController(AiUsageService usage) {
        this.usage = usage;
    }

    @GetMapping
    @Operation(operationId = "getAiUsage", summary = "AI 사용량·비용·오류 조회")
    public AiUsageResponse get(@RequestParam(required = false) String window) {
        return usage.getUsage(window);
    }
}
