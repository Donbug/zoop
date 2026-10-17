package com.zoop.portfolio.service;

import java.math.BigDecimal;

import com.zoop.company.market.TossMarketClient;
import com.zoop.portfolio.model.MockHolding;
import org.springframework.stereotype.Component;

@Component
public class TossPortfolioQuoteProvider implements PortfolioQuoteProvider {
    private final TossMarketClient client;

    public TossPortfolioQuoteProvider(TossMarketClient client) {
        this.client = client;
    }

    @Override
    public QuoteResult quote(MockHolding holding) {
        int separator = holding.companyId().indexOf(':');
        if (separator < 1) return QuoteResult.unavailable("unsupported_symbol");
        var response = client.quote(holding.companyId(), holding.companyId().substring(0, separator), holding.ticker());
        if (!"available".equals(response.status()) || response.quote() == null) {
            return QuoteResult.unavailable(response.reasonCode());
        }
        var quote = response.quote();
        return QuoteResult.available(BigDecimal.valueOf(quote.price()), quote.currency(), quote.asOf(),
                response.source().name());
    }
}
