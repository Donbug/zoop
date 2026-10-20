package com.zoop.graph.read;

import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.auth.service.MemberSettingsService;
import com.zoop.portfolio.service.PortfolioService;
import java.util.List;
import org.springframework.stereotype.Component;

/** The member's own companies for personal graph mode: mock portfolio holdings and the watchlist. */
@Component
public class PersonalCompanies {
    private final PortfolioService portfolio;
    private final MemberSettingsService settings;

    public PersonalCompanies(PortfolioService portfolio, MemberSettingsService settings) {
        this.portfolio = portfolio;
        this.settings = settings;
    }

    public record Ids(List<String> holdings, List<String> watchlist) {
        public Ids {
            holdings = List.copyOf(holdings);
            watchlist = List.copyOf(watchlist);
        }

        /** personalFilter: {@code all} (holdings first, then watchlist), {@code holdings} or {@code watchlist}. */
        List<String> select(String filter) {
            return switch (filter) {
                case "holdings" -> holdings;
                case "watchlist" -> watchlist;
                default -> java.util.stream.Stream.concat(holdings.stream(), watchlist.stream()).distinct().toList();
            };
        }
    }

    public Ids of(MemberPrincipal member) {
        return new Ids(portfolio.heldCompanyIds(member), settings.get(member, null).watchlistIds());
    }
}
