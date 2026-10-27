package com.zoop.chat.tool;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.List;

import com.zoop.chat.service.ChatMemberScope;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;

/** D-AI-02 Q07 reads: portfolio.scope.read lists the job's own member's companies, never another member's. */
class PortfolioScopeReadToolTest {
    private final List<String> asked = new ArrayList<>();
    private List<ChatMemberScope.Company> companies = List.of();
    private RuntimeException failure;

    private final ChatMemberScope scope = new ChatMemberScope(null, null) {
        @Override
        public List<Company> of(String memberId) {
            asked.add(memberId);
            if (failure != null) throw failure;
            return companies;
        }
    };
    private final PortfolioScopeReadTool tool = new PortfolioScopeReadTool(scope);

    @Test
    void theRunsMemberCompaniesAreItemsLabelledByWhyTheyAreTheirs() {
        companies = List.of(new ChatMemberScope.Company("KRX:005930", "삼성전자", true, true),
                new ChatMemberScope.Company("NASDAQ:NVDA", "NVIDIA", false, true));
        var out = tool.read(new ChatToolScope("job-1", "gv-1", null, "member-a"), self());
        assertEquals(List.of("member-a"), asked);
        assertEquals(List.of("삼성전자 (보유·관심)", "NVIDIA (관심)"), out.items().stream().map(ChatToolItem::label).toList());
        assertTrue(out.items().stream().allMatch(i -> "company".equals(i.kind()) && i.evidenceIds().isEmpty()));
        assertTrue(out.evidenceIds().isEmpty(), "the member's own list is no public evidence");
        assertFalse(out.truncated());
    }

    @Test
    void moreThanAStageFansOutToIsCutInOrder() {
        companies = new ArrayList<>();
        for (int i = 0; i < 7; i++) companies.add(new ChatMemberScope.Company("KRX:00000" + i, "기업 " + i, i < 2, i >= 2));
        var out = tool.read(new ChatToolScope("job-1", "gv-1", null, "member-a"), self());
        assertEquals(List.of("KRX:000000", "KRX:000001", "KRX:000002", "KRX:000003", "KRX:000004"),
                out.items().stream().map(ChatToolItem::id).toList(), "holdings first, then the watchlist");
        assertTrue(out.truncated());
    }

    @Test
    void onlyTheInjectedMemberIsReadAndAnOutageIsNeverAnEmptyList() {
        assertThrows(IllegalArgumentException.class, () -> tool.read(new ChatToolScope("job-1", "gv-1", null), self()));
        assertThrows(IllegalArgumentException.class, () -> tool.read(new ChatToolScope("job-1", "gv-1", null, "member-a"),
                new ChatToolRequest("portfolio.scope.read", List.of("member-b"), 20)));
        assertTrue(asked.isEmpty(), "nothing is read for a member the server did not inject");

        failure = new DataAccessResourceFailureException("down");
        assertThrows(ChatToolUnavailable.class, () -> tool.read(new ChatToolScope("job-1", "gv-1", null, "member-a"), self()));
        failure = new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        assertThrows(ChatToolUnavailable.class, () -> tool.read(new ChatToolScope("job-1", "gv-1", null, "member-a"), self()));
    }

    private static ChatToolRequest self() {
        return new ChatToolRequest("portfolio.scope.read", List.of(ChatCapability.MEMBER_SELF), 20);
    }
}
