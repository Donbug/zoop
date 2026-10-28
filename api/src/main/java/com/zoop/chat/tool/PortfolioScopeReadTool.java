package com.zoop.chat.tool;

import java.util.HashSet;
import java.util.List;
import java.util.Set;

import com.zoop.chat.service.ChatMemberScope;
import com.zoop.common.exception.CustomException;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Component;
import org.springframework.transaction.TransactionException;

/**
 * {@code portfolio.scope.read} (Q07 "my stocks", decisions of 2026-10-27): the run's member's own companies
 * ({@link ChatMemberScope}: holdings of the connected mock account, then the watchlist), as company items whose label says
 * whether each is held or watched. The member comes from the server-injected {@link ChatToolScope#memberId()}; a plan
 * names no member, so neither a plan nor a model can read another member's companies.
 *
 * <p>Its targets are either {@link ChatCapability#MEMBER_SELF} alone, for the member's companies (at most
 * {@link #MAX_COMPANIES}, in that order, which is as many as a dependent stage may fan out to; more is {@code truncated}),
 * or the companies a question names, for those of them that are the member's (checked against all of the member's
 * companies, in the member's order, never cut). It passes on no evidence: the member's own list is not a public source. A
 * store that cannot be read is {@link ChatToolUnavailable}, never an empty list.
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
        boolean self = request.targets().equals(List.of(ChatCapability.MEMBER_SELF));
        // Anything else is catalog company ids (KRX:005930), never another member.
        boolean catalog = request.targets().stream().allMatch(t -> t.indexOf(':') > 0 && !t.startsWith("member:"));
        if (run.memberId() == null || !self && !catalog) {
            throw new IllegalArgumentException("a member-scope read reads the run's own member only");
        }
        List<ChatMemberScope.Company> companies;
        try {
            companies = scope.of(run.memberId());
        } catch (CustomException | DataAccessException | TransactionException unavailable) {
            throw new ChatToolUnavailable("the member's companies cannot be read", unavailable);
        }
        Set<String> named = self ? Set.of() : new HashSet<>(request.targets());
        List<ChatMemberScope.Company> read = self ? companies.stream().limit(MAX_COMPANIES).toList()
                : companies.stream().filter(c -> named.contains(c.id())).toList();
        List<ChatToolItem> items = read.stream()
                .map(c -> new ChatToolItem(c.id(), "company", c.name() + " (" + c.relation() + ")", List.of(c.id()),
                        List.of()))
                .toList();
        return new ChatToolOutput("member-scope", items, List.of(), self && companies.size() > MAX_COMPANIES, false);
    }
}
