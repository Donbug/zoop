package com.zoop.company.market.dto;

import java.time.Instant;
import java.util.List;

public record CompanyQuoteResponse(String status, String companyId, Source source, QuoteValues quote,
        String reasonCode, String reason) {
    public static CompanyQuoteResponse unavailable(String id, String code, String reason) {
        return new CompanyQuoteResponse("unavailable", id, null, null, code, reason);
    }
    public static CompanyQuoteResponse available(String id, Source source, QuoteValues quote) {
        return new CompanyQuoteResponse("available", id, source, quote, null, null);
    }
    public record Source(String provider, String name, boolean official, String delayNote, String symbol, String url) { }
    public record QuoteValues(String currency, double price, Instant asOf, Double previousClose, Double change,
            Double changeRate, Double dayHigh, Double dayLow, Double volume, Double fiftyTwoWeekHigh,
            Double fiftyTwoWeekLow, Double marketCap, Double sharesOutstanding, List<String> derived) { }
}
