package com.zoop.company.controller;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.company.market.NaverMetricsClient;
import com.zoop.company.market.TossMarketClient;
import com.zoop.company.market.dto.CompanyMetricsResponse;
import com.zoop.company.market.dto.CompanyPriceResponse;
import com.zoop.company.market.dto.CompanyQuoteResponse;
import com.zoop.company.repository.CompanyProfileRow;
import com.zoop.company.repository.CompanySearchRepository;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeParseException;
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

    @GetMapping("/prices")
    @Operation(summary = "기간별 가격 차트 조회",
            description = "period(1d·1w·1m·1y, 기본 1m)별로 봉 해상도가 고정됩니다(1d=5분, 1w=1시간, 1m=일봉, 1y=주봉). "
                    + "공급자가 그 해상도를 주지 않으면 다른 해상도를 집계·보간하지 않고 200 unavailable(no_data)입니다. "
                    + "현재 토스증권은 1분·일봉만 제공해 1m만 가격이 오고 나머지는 no_data입니다. "
                    + "from/to는 KST 날짜(그날 전체) 또는 오프셋이 있는 시각이며 일봉은 KST 날짜로 비교합니다. from 생략 시 한 달 전부터입니다. "
                    + "키 미설정은 not_connected, 비상장은 unsupported_symbol, 기간 내 거래 없음은 no_data(모두 200)이고 "
                    + "공급자 인증·네트워크·형식 장애는 503 SOURCE_UNAVAILABLE입니다. asOf·graphVersion은 받지 않습니다(422).")
    public CompanyPriceResponse prices(@PathVariable String id,
            @RequestParam(required = false) String period,
            @RequestParam(required = false) String from,
            @RequestParam(required = false) String to,
            @RequestParam(required = false) String asOf,
            @RequestParam(required = false) String graphVersion,
            HttpServletRequest request) {
        if (asOf != null || graphVersion != null) throw new CustomException(ErrorCode.INVALID_REQUEST);
        String resolved = period == null ? "1m" : period;
        if (!TossMarketClient.PERIOD_INTERVAL.containsKey(resolved)) throw new CustomException(ErrorCode.INVALID_REQUEST);
        LocalDate fromDay = kstDay(from), toDay = kstDay(to);
        if (fromDay != null && toDay != null && fromDay.isAfter(toDay)) throw new CustomException(ErrorCode.INVALID_REQUEST);
        CompanyProfileRow company = company(id);
        if (company.exchangeCode() == null || company.ticker() == null) {
            return CompanyPriceResponse.unavailable(id, resolved, "unsupported_symbol", "이 기업은 상장 종목 시세를 제공하지 않아요.");
        }
        return toss.prices(id, company.exchangeCode(), company.ticker(), resolved, fromDay, toDay);
    }

    /** A bare date is that KST day; a date-time must carry its offset (contract) and is read as its KST day. */
    private static LocalDate kstDay(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            if (value.length() == 10) return LocalDate.parse(value);
            return OffsetDateTime.parse(value).atZoneSameInstant(ZoneId.of("Asia/Seoul")).toLocalDate();
        } catch (DateTimeParseException exception) {
            throw new CustomException(ErrorCode.INVALID_REQUEST, exception);
        }
    }

    private CompanyProfileRow company(String id) {
        return repository.findProfile(id).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
    }
}
