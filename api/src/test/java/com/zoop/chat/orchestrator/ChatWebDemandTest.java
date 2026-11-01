package com.zoop.chat.orchestrator;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
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
}
