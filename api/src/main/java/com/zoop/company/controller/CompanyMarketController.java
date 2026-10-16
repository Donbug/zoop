package com.zoop.company.controller;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.company.market.NaverMetricsClient;
import com.zoop.company.market.TossMarketClient;
import com.zoop.company.market.dto.CompanyMetricsResponse;
import com.zoop.company.market.dto.CompanyQuoteResponse;
import com.zoop.company.repository.CompanyProfileRow;
import com.zoop.company.repository.CompanySearchRepository;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/companies/{id}")
public class CompanyMarketController {
    private final CompanySearchRepository repository;
    private final TossMarketClient toss;
    private final NaverMetricsClient metrics;

    public CompanyMarketController(CompanySearchRepository repository, TossMarketClient toss, NaverMetricsClient metrics) {
        this.repository = repository; this.toss = toss; this.metrics = metrics;
    }

    @GetMapping("/quote")
    public CompanyQuoteResponse quote(@PathVariable String id,
            @RequestParam(required = false) String asOf,
            @RequestParam(required = false) String graphVersion,
            HttpServletRequest request) {
        if (asOf != null || graphVersion != null) throw new CustomException(ErrorCode.INVALID_REQUEST);
        CompanyProfileRow company = company(id);
        if (company.exchangeCode() == null || company.ticker() == null) {
            return CompanyQuoteResponse.unavailable(id, "unsupported_symbol", "이 기업은 상장 종목 시세를 제공하지 않아요.");
        }
        return toss.quote(id, company.exchangeCode(), company.ticker());
    }

    @GetMapping("/metrics")
    public CompanyMetricsResponse metrics(@PathVariable String id,
            @RequestParam(required = false) String asOf,
            @RequestParam(required = false) String graphVersion,
            HttpServletRequest request) {
        if (asOf != null || graphVersion != null) throw new CustomException(ErrorCode.INVALID_REQUEST);
        CompanyProfileRow company = company(id);
        if (company.exchangeCode() == null || company.ticker() == null) {
            return CompanyMetricsResponse.unavailable(id, "unsupported_symbol", "이 기업은 상장 종목 지표를 제공하지 않아요.");
        }
        return metrics.metrics(id, company.exchangeCode(), company.ticker());
    }

    private CompanyProfileRow company(String id) {
        return repository.findProfile(id).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
    }
}
