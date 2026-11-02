package com.zoop.briefing.personal;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;
import java.util.Optional;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/** Entirely authored receipt envelopes, not external provider output. */
class PersonalAiReadTest {
    final JsonMapper json=JsonMapper.builder().build();
    JsonNode fixture() throws Exception {try(var in=getClass().getResourceAsStream("/briefing/personal-ai-authored.json")){return json.readTree(in);}}
    PersonalAiRepository.Saved saved(JsonNode f){var s=f.path("saved");return new PersonalAiRepository.Saved(s.path("input"),s.path("result"),s.path("proof"));}
    @Test void acceptsExactReceiptBoundRevisionAndNeverReturnsItToAnotherMemberOrBasis() throws Exception {
        var f=fixture();var s=saved(f);var repo=mock(PersonalAiRepository.class);var basis=PersonalAiRead.basis(f.path("selection"));
        when(repo.find("owner","r",basis)).thenReturn(Optional.of(s));
        var read=new PersonalAiRead(repo);assertEquals("available",read.read("owner",f.path("selection")).path("status").asString());
        assertEquals("unavailable",read.read("other",f.path("selection")).path("status").asString());
        var changed=(ObjectNode)f.path("selection").deepCopy();((ObjectNode)changed.path("basis")).putArray("watchlist").add("OTHER");
        assertEquals("unavailable",read.read("owner",changed).path("status").asString());
        assertEquals("PASS",s.result().path("status").asString());
    }
    @Test void rejectsEditedDraftEvenIfSelectionIsTheSame() throws Exception {
        var f=fixture();((ObjectNode)f.at("/saved/result/draft/issues/i0/companies/C/businessImpact")).put("text","위조 해석");
        assertThrows(IllegalArgumentException.class,()->PersonalAiRead.validate(saved(f),PersonalAiRead.basis(f.path("selection"))));
    }
    @Test void rejectsChangedReceiptAndASecondCompanyEvent() throws Exception {
        var f=fixture();((ObjectNode)f.at("/saved/proof/0")).put("response","{}");
        assertThrows(IllegalArgumentException.class,()->PersonalAiRead.validate(saved(f),PersonalAiRead.basis(f.path("selection"))));
        var again=fixture();((ObjectNode)again.at("/saved/input/issues/0")).put("issueId","different-event-same-company");
        assertThrows(IllegalArgumentException.class,()->PersonalAiRead.validate(saved(again),PersonalAiRead.basis(again.path("selection"))));
    }
}
