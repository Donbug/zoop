package com.zoop.chat.tool;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import static org.junit.jupiter.api.Assertions.*;

/**
 * D-AI-02 web search tool (web search design 3, 5 and 6): only checked public queries leave, hits are bounded and checked,
 * an outage is never an empty result, and the tool is never planned or exposed.
 */
class ChatWebSearchToolTest {
    private static final Instant NOW = Instant.parse("2026-10-30T01:00:00Z");
    private static final Clock CLOCK = Clock.fixed(NOW, ZoneOffset.UTC);
    private static final ChatToolScope SCOPE = new ChatToolScope("job-1", "gv-1", null, "member-a");

    @ParameterizedTest
    @ValueSource(strings = {"HBM", "SK하이닉스 HBM", "EUV 수출 규제", "삼성전자 2026-10-29 실적", "HBM  공급\t계약"})
    void aPublicPhraseIsSentNormalized(String query) {
        var checked = ChatWebQueryPolicy.checked(query);
        assertTrue(checked.isPresent(), query);
        assertFalse(checked.get().contains("  ") || checked.get().contains("\t"), "single spaces: " + checked.get());
    }

    @ParameterizedTest
    @ValueSource(strings = {"a", "member@example.com 문의", "https://example.com HBM", "www.zoop 검색", "010-1234-5678",
            "계좌 1234567890", "내 종목 수익률", "삼성전자 보유 수량", "SK하이닉스 평단", "관심종목 뉴스", "주민번호",
            "HBM\u0007"})
    void anythingAboutTheMemberIsRefusedNotEdited(String query) {
        assertEquals(Optional.empty(), ChatWebQueryPolicy.checked(query), query);
    }

    @Test
    void aQueryIsAShortPhrase() {
        assertTrue(ChatWebQueryPolicy.checked("가".repeat(ChatWebQueryPolicy.MAX_LENGTH)).isPresent());
        assertEquals(Optional.empty(), ChatWebQueryPolicy.checked("가".repeat(ChatWebQueryPolicy.MAX_LENGTH + 1)));
    }

    @Test
    void theSyntheticProviderGivesItsFixtureHitsAsBoundedWebResultsWithNoEvidence() {
        var tool = new ChatWebSearchTool(new SyntheticWebSearchProvider(), CLOCK);
        var output = tool.read(SCOPE, new ChatToolRequest("web.search", List.of("HBM"), 5));

        assertEquals("web:synthetic", output.dataVersion());
        assertEquals(2, output.webResults().size());
        assertTrue(output.evidenceIds().isEmpty(), "a web hit is no ZOOP evidence");
        assertFalse(output.truncated());
        var first = output.webResults().getFirst();
        assertTrue(first.id().startsWith("web-") && first.id().length() == 36, first.id());
        assertEquals("news.example.com", first.domain());
        assertEquals("synthetic", first.provider());
        assertEquals(NOW, first.searchedAt());
        assertEquals(Instant.parse("2026-10-01T00:00:00Z"), first.publishedAt());
        assertNull(output.webResults().get(1).publishedAt(), "no publication time is not made up");
        assertEquals(List.of("web_result", "web_result"), output.items().stream().map(ChatToolItem::kind).toList());
        assertEquals(output.webResults().stream().map(ChatWebResult::id).toList(),
                output.items().stream().map(ChatToolItem::id).toList());

        var none = tool.read(SCOPE, new ChatToolRequest("web.search", List.of("없는 검색어"), 5));
        assertTrue(none.webResults().isEmpty() && !none.truncated(), "nothing found within the query");
        assertThrows(ChatToolUnavailable.class,
                () -> tool.read(SCOPE, new ChatToolRequest("web.search", List.of("장애 시험"), 5)));
    }

    @Test
    void aQueryThatMayNotLeaveNeverReachesTheProvider() {
        var provider = new Scripted(List.of());
        var tool = new ChatWebSearchTool(provider, CLOCK);
        assertThrows(IllegalArgumentException.class,
                () -> tool.read(SCOPE, new ChatToolRequest("web.search", List.of("내 종목 수익률"), 5)));
        assertThrows(IllegalArgumentException.class,
                () -> tool.read(SCOPE, new ChatToolRequest("web.search", List.of("HBM", "EUV"), 5)),
                "one query per call: more would get around the web budget");
        assertTrue(provider.queries.isEmpty());
    }

    @Test
    void unusableHitsAreDroppedAndTheRestBoundedDedupedAndCut() {
        String longSnippet = "가".repeat(ChatWebResult.MAX_SNIPPET + 20);
        var provider = new Scripted(List.of(
                new ChatWebSearchProvider.Hit("javascript:alert(1)", "스크립트", "x", null),
                new ChatWebSearchProvider.Hit("ftp://files.example.com/a", "파일", "x", null),
                new ChatWebSearchProvider.Hit("https://user:pw@news.example.com/a", "계정", "x", null),
                new ChatWebSearchProvider.Hit("https://news.example.com/b", " ", "제목 없음", null),
                new ChatWebSearchProvider.Hit("https://news.example.com/c", "기사 C", longSnippet, null),
                new ChatWebSearchProvider.Hit("https://news.example.com/c", "기사 C 다시", "같은 쪽", null),
                new ChatWebSearchProvider.Hit("https://news.example.com/d", "기사 D", null, null)));
        provider.more = true;
        var output = new ChatWebSearchTool(provider, CLOCK)
                .read(SCOPE, new ChatToolRequest("web.search", List.of("HBM"), 20));

        assertEquals(List.of("https://news.example.com/c", "https://news.example.com/d"),
                output.webResults().stream().map(ChatWebResult::url).toList());
        assertEquals(ChatWebResult.MAX_SNIPPET, output.webResults().getFirst().snippet().codePointCount(0,
                output.webResults().getFirst().snippet().length()));
        assertEquals("", output.webResults().get(1).snippet());
        assertTrue(output.truncated(), "the provider had more");
        assertEquals(List.of(ChatWebSearchTool.MAX_HITS), provider.limits, "at most five per query");
    }

    @Test
    void aFixtureHitOutsideTheExampleDomainsIsRefusedAtStartup() {
        var refused = assertThrows(IllegalStateException.class,
                () -> new SyntheticWebSearchProvider("chat-web-fixtures/not-example.json"));
        assertTrue(refused.getMessage().contains("example domain"), refused.getMessage());
    }

    @Test
    void theRegistryRunsTheWebSearchButNeverOffersItToAPlanOrMcp() {
        var registry = new ChatToolRegistry(List.of(new ChatWebSearchTool(new SyntheticWebSearchProvider(), CLOCK)));
        assertTrue(registry.bind("web.search").isPresent());
        assertEquals("web-search", registry.bind("web.search").get().capability().group());
        assertFalse(registry.bound().contains("web.search"));
        assertTrue(ChatCapability.WEB_SEARCH.web());
        assertFalse(ChatCapability.COMPANY_READ.web());
    }

    /** A provider that records what it was asked and returns fixed hits. */
    private static final class Scripted implements ChatWebSearchProvider {
        final List<ChatWebSearchProvider.Hit> hits;
        final List<String> queries = new ArrayList<>();
        final List<Integer> limits = new ArrayList<>();
        boolean more;

        Scripted(List<ChatWebSearchProvider.Hit> hits) {
            this.hits = hits;
        }

        @Override
        public String id() {
            return "scripted";
        }

        @Override
        public Page search(String query, int limit) {
            queries.add(query);
            limits.add(limit);
            return new Page(hits, more);
        }
    }
}
