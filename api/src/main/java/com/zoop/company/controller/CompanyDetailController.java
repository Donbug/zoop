package com.zoop.company.controller;

import com.zoop.common.request.RequestIdFilter;
import com.zoop.company.service.CompanyDetailService;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/companies")
public class CompanyDetailController {
    private final CompanyDetailService service;

    public CompanyDetailController(CompanyDetailService service) { this.service = service; }

    @GetMapping("/{id}")
    public CompanyDetailService.CompanyDetail getCompany(@PathVariable String id,
            @RequestParam(required = false) String round,
            @RequestParam(required = false) String graphVersion,
            @RequestParam(required = false) String asOf,
            HttpServletRequest request) {
        return service.getCompany(id, round, graphVersion, asOf, RequestIdFilter.currentId(request));
    }
}
