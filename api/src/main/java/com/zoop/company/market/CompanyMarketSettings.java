package com.zoop.company.market;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "zoop.market")
public record CompanyMarketSettings(String quoteProvider, String tossClientId, String tossClientSecret,
        String tossBaseUrl, String metricsProvider, String naverDomesticUrl, String naverWorldUrl,
        String naverAutocompleteUrl, java.time.Duration timeout) {
    public CompanyMarketSettings {
        quoteProvider = quoteProvider == null ? "toss" : quoteProvider;
        metricsProvider = metricsProvider == null ? "naver" : metricsProvider;
        tossBaseUrl = tossBaseUrl == null ? "https://openapi.tossinvest.com" : tossBaseUrl;
        naverDomesticUrl = naverDomesticUrl == null ? "https://m.stock.naver.com" : naverDomesticUrl;
        naverWorldUrl = naverWorldUrl == null ? "https://api.stock.naver.com" : naverWorldUrl;
        naverAutocompleteUrl = naverAutocompleteUrl == null ? "https://ac.stock.naver.com" : naverAutocompleteUrl;
        timeout = timeout == null ? java.time.Duration.ofSeconds(5) : timeout;
    }
}
