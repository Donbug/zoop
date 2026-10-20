package com.zoop.company.market.dto;

import java.util.List;

/** OpenAPI {@code PriceSeries} (status=available) or {@code PriceSeriesUnavailable} (status=unavailable). */
public record CompanyPriceResponse(String status, String companyId, String period, CompanyQuoteResponse.Source source,
        String currency, String interval, List<Point> points, String reasonCode, String reason) {
    public static CompanyPriceResponse unavailable(String id, String period, String code, String reason) {
        return new CompanyPriceResponse("unavailable", id, period, null, null, null, null, code, reason);
    }
    public static CompanyPriceResponse available(String id, String period, CompanyQuoteResponse.Source source,
            String currency, String interval, List<Point> points) {
        return new CompanyPriceResponse("available", id, period, source, currency, interval, List.copyOf(points), null, null);
    }
    /** One bar; {@code time} is ISO 8601 with the exchange offset. Oldest first in {@link #points()}. */
    public record Point(String time, double open, double high, double low, double close, Double volume) { }
}
