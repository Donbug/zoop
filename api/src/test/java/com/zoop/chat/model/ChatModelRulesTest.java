package com.zoop.chat.model;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;

import com.zoop.chat.model.CompanyNameResolver.Company;
import com.zoop.chat.model.CompanyNameResolver.Entry;
import com.zoop.chat.model.CompanyNameResolver.Mention;
import org.junit.jupiter.api.Test;

/** The provisional deterministic rules: requirement splitting and exact catalog name matching. */
class ChatModelRulesTest {
    private static final Company SAMSUNG = new Company("c-samsung", "삼성전자", "005930");
    private static final Company SAMSUNG_GROUP = new Company("c-samsung-cnt", "삼성물산", "028260");
    private static final Company HANMI_PHARM = new Company("c-hanmi-pharm", "한미약품", "128940");
    private static final Company HANMI_SCIENCE = new Company("c-hanmi-science", "한미사이언스", "008930");
    private static final Company SK = new Company("c-skhynix", "SK하이닉스", "000660");

    private static final List<Entry> CATALOG = List.of(
            new Entry("삼성전자", SAMSUNG), new Entry("삼성", SAMSUNG), new Entry("삼성", SAMSUNG_GROUP),
            new Entry("삼성물산", SAMSUNG_GROUP), new Entry("한미", HANMI_PHARM), new Entry("한미", HANMI_SCIENCE),
            new Entry("sk하이닉스", SK), new Entry("하이닉스", SK));

    @Test
    void splitsOnlyAtUnambiguousBoundaries() {
        assertEquals(List.of("PER이 뭐야", "삼성전자 관련 사건 알려줘"),
                ChatRequirementSplitter.split("PER이 뭐야? 삼성전자 관련 사건 알려줘").stream().map(ChatRequirementSplitter.Piece::text).toList());
        assertEquals(List.of("r1", "r2"), ChatRequirementSplitter.split("A사 공급망 그리고 B사 공시").stream()
                .map(ChatRequirementSplitter.Piece::id).toList());
        assertEquals(1, ChatRequirementSplitter.split("삼성전자에 공급하고 실적이 좋은 기업은?").size());
        assertEquals(List.of("?"), ChatRequirementSplitter.split("?").stream().map(ChatRequirementSplitter.Piece::text).toList());
    }

    @Test
    void theLongestExactNameWinsAndAliasesOfOneCompanyAreOneMention() {
        List<Mention> mentions = CompanyNameResolver.match("삼성전자와 SK하이닉스, 하이닉스 비교", CATALOG);
        assertEquals(List.of("삼성전자", "SK하이닉스"), mentions.stream().map(Mention::text).toList());
        assertEquals(List.of(SAMSUNG), mentions.get(0).companies());
        assertEquals(List.of(SK), mentions.get(1).companies());
        assertTrue(mentions.stream().noneMatch(Mention::ambiguous));
    }

    @Test
    void aNameSharedByCompaniesIsAmbiguousAndNothingMatchesPartially() {
        List<Mention> shared = CompanyNameResolver.match("한미 관련 공시", CATALOG);
        assertEquals(1, shared.size());
        assertTrue(shared.getFirst().ambiguous());
        assertEquals("한미약품 (128940)", shared.getFirst().companies().getFirst().label());

        assertTrue(CompanyNameResolver.match("하이 닉스 전망", CATALOG).isEmpty());
        assertFalse(CompanyNameResolver.match("삼성 전망", CATALOG).isEmpty());
    }
}
