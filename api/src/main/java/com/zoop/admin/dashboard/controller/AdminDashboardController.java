package com.zoop.admin.dashboard.controller;

import com.zoop.admin.dashboard.dto.AdminDashboardResponse;
import com.zoop.admin.dashboard.service.AdminDashboardService;
import com.zoop.common.request.RequestIdFilter;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/admin")
public class AdminDashboardController {
    private final AdminDashboardService dashboard;

    public AdminDashboardController(AdminDashboardService dashboard) {
        this.dashboard = dashboard;
    }

    @GetMapping("/dashboard")
    @Operation(operationId = "getAdminDashboard", summary = "운영 대시보드 조회")
    public AdminDashboardResponse getAdminDashboard(HttpServletRequest request) {
        return dashboard.getDashboard(RequestIdFilter.currentId(request));
    }
}
