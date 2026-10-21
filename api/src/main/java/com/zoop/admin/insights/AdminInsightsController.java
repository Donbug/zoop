package com.zoop.admin.insights;

import com.zoop.common.request.RequestIdFilter;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/admin/insights")
public class AdminInsightsController {
    private final AdminInsightsService insights;
    public AdminInsightsController(AdminInsightsService insights) { this.insights = insights; }

    @GetMapping("/overview")
    @Operation(operationId = "getInsightsOverview", summary = "사용 통계 개요 조회")
    public AdminInsightsService.Overview overview(HttpServletRequest request) {
        return insights.overview(RequestIdFilter.currentId(request));
    }

    @GetMapping("/summary")
    @Operation(operationId = "getInsightsSummary", summary = "사용 통계와 산식 조회")
    public AdminInsightsService.Summary summary(@RequestParam(defaultValue = "7d") String window,
            HttpServletRequest request) {
        return insights.summary(window, RequestIdFilter.currentId(request));
    }

    @GetMapping("/companies")
    @Operation(operationId = "listCompanyInsights", summary = "기업별 활동 집계 조회")
    public AdminInsightsService.CompanyRanking companies(@RequestParam(defaultValue = "7d") String window,
            @RequestParam(required = false) String cursor, @RequestParam(required = false) Integer limit,
            HttpServletRequest request) {
        return insights.companies(window, cursor, limit, RequestIdFilter.currentId(request));
    }

    @GetMapping("/companies/{company_id}")
    @Operation(operationId = "getCompanyInsights", summary = "기업별 일별 활동 조회")
    public AdminInsightsService.CompanyDetail company(@PathVariable("company_id") String companyId,
            @RequestParam(defaultValue = "7d") String window, HttpServletRequest request) {
        return insights.company(companyId, window, RequestIdFilter.currentId(request));
    }
}
