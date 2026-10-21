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
import java.time.Instant;
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
                    + "토스증권은 1분·일봉만 제공해 1d·1w는 1분봉, 1y는 일봉을 거래소 현지 시각 구간으로 집계합니다(점의 time은 구간 시작). "
                    + "from/to는 KST 날짜(그날 전체) 또는 오프셋이 있는 시각(to는 그 시각 포함)이며, 각 점은 [from, to]와 겹치는 구간(5분·1시간·거래소 하루·월요일 시작 주) 하나입니다. "
                    + "1d는 거래소 장 운영 캘린더의 정규 세션(평소 KRX 09:00–15:30, 미국 09:30–16:00 ET, 조기 마감 반영) 중 to가 속한 세션이고, 장 시작 전·휴장일이면 직전 거래일 세션입니다. 정상 세션에 봉이 없으면 no_data입니다. 1d는 from을 받지 않습니다(422). "
                    + "to 생략 시 지금까지, from 생략 시 to에서 기간(7일·한 달·1년)만큼 전부터입니다. 응답 range에 실제 구간을 담습니다. "
                    + "범위는 기간 하나까지이며, from이 to에서 기간만큼 전보다 앞서면 422입니다. "
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
        // 1d is the exchange session the server picks for to, so a client from has nothing to mean.
        if ("1d".equals(resolved) && from != null) throw new CustomException(ErrorCode.INVALID_REQUEST);
        Instant start = from == null ? null : bound(from, false), end = to == null ? null : bound(to, true);
        if (start != null && end != null && !start.isBefore(end)) throw new CustomException(ErrorCode.INVALID_REQUEST);
        // One period at most: a longer range would let one public request read days of minute bars from the provider.
        if (start != null && start.isBefore(TossMarketClient.periodStart(resolved, end != null ? end.minusNanos(1) : Instant.now()))) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        CompanyProfileRow company = company(id);
        if (company.exchangeCode() == null || company.ticker() == null) {
            return CompanyPriceResponse.unavailable(id, resolved, "unsupported_symbol", "이 기업은 상장 종목 시세를 제공하지 않아요.");
        }
        return toss.prices(id, company.exchangeCode(), company.ticker(), resolved, start, end);
    }

    /**
     * A bare date is that whole KST day (to: up to the next day); a date-time must carry its offset (contract). An exact
     * to includes that instant, so the chart can send a point's own time back and get that point again.
     */
    private static Instant bound(String value, boolean end) {
        try {
            if (value.length() == 10) return LocalDate.parse(value).plusDays(end ? 1 : 0).atStartOfDay(ZoneId.of("Asia/Seoul")).toInstant();
            Instant at = OffsetDateTime.parse(value).toInstant();
            return end ? at.plusNanos(1) : at;
        } catch (DateTimeParseException exception) {
            throw new CustomException(ErrorCode.INVALID_REQUEST, exception);
        }
    }

    private CompanyProfileRow company(String id) {
        return repository.findProfile(id).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
    }
}
