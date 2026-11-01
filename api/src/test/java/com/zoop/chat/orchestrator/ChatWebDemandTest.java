package com.zoop.chat.orchestrator;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.chat.dto.Citation;
import com.zoop.chat.tool.ChatToolItem;
import com.zoop.chat.tool.ChatToolResult;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.Test;

/** D-AI-02: the words that ask for a source outside ZOOP. */
class ChatWebDemandTest {
    @Test
    void aRequestForAnOutsideSourceIsReadFromTheRequirementsWords() {
        for (String words : List.of("SK하이닉스 외신 보도 알려줘", "삼성전자 소식을 외부 출처로 확인해줘", "웹에서 찾아줘",
                "웹 검색해 줘", "해외 언론 반응", "인터넷에서 확인해줘", "언론 보도 기준으로 알려줘")) {
            assertTrue(ChatWebDemand.asksExternalSource(words), words);
        }
    }

    @Test
    void companyNamesAndRequestsAgainstTheWebAreNoRequest() {
        for (String words : List.of("SK하이닉스 최근 사건", "네이버와 구글 관계", "웹 검색 말고 줍 자료로만", "외부 자료 없이 답해줘",
                "웹에서 찾지 마", "외부 감사인")) {
            assertFalse(ChatWebDemand.asksExternalSource(words), words);
        }
    }

    @Test
    void coverageChecksTheRequestedTargetPeriodFieldAndCitation() {
        Instant askedAt = Instant.parse("2026-10-21T03:00:00Z");
        ChatToolResult read = result("KRX:000660", "ev-1", "SK하이닉스 실적");
        Citation old = citation("2026-10-01T03:00:00Z", "영업이익만 발표");

        var missing = ChatWebDemand.coverage("SK하이닉스 최근 7일 매출", askedAt, List.of("KRX:000660"),
                List.of(read), id -> Optional.of(old));

        assertTrue(missing.targets());
        assertFalse(missing.period(), "the article is outside the written period");
        assertFalse(missing.fields(), "the requested revenue field is absent");
        assertTrue(missing.citation());
        assertTrue(missing.incomplete());

        Citation current = citation("2026-10-20T03:00:00Z", "분기 revenue 3조원");
        var complete = ChatWebDemand.coverage("SK하이닉스 최근 7일 매출", askedAt, List.of("KRX:000660"),
                List.of(read), id -> Optional.of(current));
        assertTrue(complete.targets() && complete.period() && complete.fields() && complete.citation());
        assertFalse(complete.incomplete());
    }

    @Test
    void unreadableInternalEvidenceDoesNotBecomePermissionForReplacementSearch() {
        var coverage = ChatWebDemand.coverage("최근 7일 매출", Instant.parse("2026-10-21T03:00:00Z"),
                List.of("KRX:000660"), List.of(result("KRX:000660", "ev-private", "기업")),
                id -> Optional.empty());

        assertTrue(coverage.period() && coverage.fields(), "unknown refused contents are not declared missing");
        assertFalse(coverage.incomplete());
    }

    @Test
    void aResultWithoutEvidenceLeavesTheCitationRequirementUnmet() {
        ChatToolResult read = result("KRX:000660", null, "SK하이닉스 매출");
        var coverage = ChatWebDemand.coverage("SK하이닉스 매출", Instant.parse("2026-10-21T03:00:00Z"),
                List.of("KRX:000660"), List.of(read), id -> Optional.empty());

        assertFalse(coverage.citation());
        assertTrue(coverage.incomplete());
    }

    private static ChatToolResult result(String company, String evidence, String label) {
        List<String> ids = evidence == null ? List.of() : List.of(evidence);
        return new ChatToolResult("chat-tool/v1", "tc-1", "company.read", "v1",
                List.of(new ChatToolItem(company, "company", label, List.of(company), ids)), ids, false, false, null);
    }

    private static Citation citation(String publishedAt, String quote) {
        return new Citation("article", "ev-1", quote, "art-1", "v1", null, null, 0,
                quote.codePointCount(0, quote.length()), "실적 기사", "언론사", Instant.parse(publishedAt),
                "https://example.invalid/article");
    }
}
