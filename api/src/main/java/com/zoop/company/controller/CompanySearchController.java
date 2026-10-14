package com.zoop.company.controller;

import java.time.Instant;

import com.zoop.company.dto.CompanyListResponse;
import com.zoop.company.service.CompanySearchApiService;
import com.zoop.common.request.RequestIdFilter;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.constraints.Min;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@Validated
@RestController
@RequestMapping("/api/v1/companies")
public class CompanySearchController {
    private final CompanySearchApiService service;

    public CompanySearchController(CompanySearchApiService service) {
        this.service = service;
    }

    @GetMapping
    public CompanyListResponse searchCompanies(
            @RequestParam(required = false) String q,
            @RequestParam(required = false) String cursor,
            @RequestParam(required = false) @Min(1) Integer limit,
            @RequestParam(required = false) String graphVersion,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) Instant asOf,
            HttpServletRequest request) {
        return service.search(q, cursor, limit, graphVersion, asOf, RequestIdFilter.currentId(request));
    }
}
