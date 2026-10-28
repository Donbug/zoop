package com.zoop.chat.tool;

import java.util.List;

import com.zoop.chat.service.ChatMemberScope;
import com.zoop.common.exception.CustomException;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Component;
import org.springframework.transaction.TransactionException;

/**
 * {@code portfolio.scope.read} (Q07 "my stocks", decision of 2026-10-27): the run's member's own companies
 * ({@link ChatMemberScope}: holdings of the connected mock account, then the watchlist), as company items whose label says
 * whether each is held or watched. The member comes from the server-injected {@link ChatToolScope#memberId()}; the only
 * target it accepts is {@link ChatCapability#MEMBER_SELF}, so neither a plan nor a model can name another member.
 *
 * <p>At most {@link #MAX_COMPANIES} companies are passed on, in that order, which is as many as a dependent stage may fan out
 * to; more is {@code truncated}. It passes on no evidence: the member's own list is not a public source. A store that
 * cannot be read is {@link ChatToolUnavailable}, never an empty list.
 */
@Component
public class PortfolioScopeReadTool implements ChatTool {
    static final int MAX_COMPANIES = ChatToolRequest.MAX_TARGETS;

    private final ChatMemberScope scope;

    public PortfolioScopeReadTool(ChatMemberScope scope) {
        this.scope = scope;
    }

    @Override
    public ChatCapability capability() {
        return ChatCapability.PORTFOLIO_SCOPE_READ;
    }

    @Override
    public ChatToolOutput read(ChatToolScope run, ChatToolRequest request) {
        if (run.memberId() == null || !request.targets().equals(List.of(ChatCapability.MEMBER_SELF))) {
            throw new IllegalArgumentException("a member-scope read reads the run's own member only");
        }
        List<ChatMemberScope.Company> companies;
        try {
            companies = scope.of(run.memberId());
        } catch (CustomException | DataAccessException | TransactionException unavailable) {
            throw new ChatToolUnavailable("the member's companies cannot be read", unavailable);
        }
        List<ChatToolItem> items = companies.stream().limit(MAX_COMPANIES)
                .map(c -> new ChatToolItem(c.id(), "company", c.name() + " (" + c.relation() + ")", List.of(c.id()),
                        List.of()))
                .toList();
        return new ChatToolOutput("member-scope", items, List.of(), companies.size() > MAX_COMPANIES, false);
    }
}
