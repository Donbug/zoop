package com.zoop.chat.service;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

class ChatCompanyProfilesTest {
    private final JsonMapper mapper = JsonMapper.builder().build();

    @Test
    void theQuoteIsTheCatalogTextAndItsIdFollowsThatText() {
        ObjectNode profile = mapper.createObjectNode().put("businessSummary", "메모리 반도체 기업이다.")
                .put("representative", "대표").put("foundedDate", "1969-01-13").put("websiteUrl", "https://example.com");
        var quote = ChatCompanyProfiles.quote("KRX:005930", "삼성전자", profile).orElseThrow();
        assertEquals("삼성전자(KRX:005930) 사업 개요: 메모리 반도체 기업이다. 대표: 대표. 설립일: 1969-01-13. "
                + "홈페이지: https://example.com.", quote.text());
        assertEquals("삼성전자 기업 개요", quote.title());
        assertEquals("https://example.com", quote.url());
        assertTrue(quote.evidenceId().matches("ev-[0-9a-f]{64}"), "it has the evidence id shape the model stages accept");
        assertEquals(quote, ChatCompanyProfiles.quote("KRX:005930", "삼성전자", profile).orElseThrow());

        profile.put("businessSummary", "바뀐 개요.");
        assertNotEquals(quote.evidenceId(), ChatCompanyProfiles.quote("KRX:005930", "삼성전자", profile).orElseThrow()
                .evidenceId(), "changed text is a different quote");
    }

    @Test
    void aCompanyWithoutABusinessSummaryHasNoQuote() {
        ObjectNode profile = mapper.createObjectNode().put("representative", "대표").put("businessSummary", " ");
        assertTrue(ChatCompanyProfiles.quote("KRX:005930", "삼성전자", profile).isEmpty());
    }
}
