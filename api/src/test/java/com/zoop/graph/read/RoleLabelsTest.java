package com.zoop.graph.read;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import org.junit.jupiter.api.Test;

class RoleLabelsTest {
    @Test
    void knownEnglishRolesAreTranslatedAndCombined() {
        assertEquals("발행사", RoleLabels.label("issuer"));
        assertEquals("투자사", RoleLabels.label(" Investor "));
        assertEquals("투자사·투자 대상", RoleLabels.label("investor/investee"));
        assertEquals("구축사·주최자", RoleLabels.label("builder and host"));
        assertEquals("주최자", RoleLabels.label("host, of the launch event"));
    }

    @Test
    void koreanIsKeptAndShortened() {
        assertEquals("공급", RoleLabels.label("공급"));
        assertEquals("가나다라마바사아자차카타파…", RoleLabels.label("가나다라마바사아자차카타파하거너"));
    }

    @Test
    void unknownPhrasesAreNotGuessed() {
        assertNull(RoleLabels.label("supplier"));
        assertNull(RoleLabels.label("investor and supplier"));
        assertNull(RoleLabels.label(null));
        // Detail text falls back to the article's own words; the edge label falls back to a generic phrase.
        assertEquals("supplier", RoleLabels.display("supplier"));
    }
}
