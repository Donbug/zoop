package com.zoop.briefing.personal;
import org.junit.jupiter.api.Test;
import com.zoop.common.exception.CustomException;
import java.util.*;
import tools.jackson.databind.JsonNode;
import static org.junit.jupiter.api.Assertions.*;
class ExplicitSelectionTest {
    final PersonalSelectionTest fixtures=new PersonalSelectionTest();
    @Test void requiresExplicitNonemptyUniqueKnownSizeAndValidCountPreferences(){
        for(var c:List.of(new ExplicitBriefingService.Choice(List.of(),3,0,3),
                new ExplicitBriefingService.Choice(List.of("A","A"),3,0,3),new ExplicitBriefingService.Choice(List.of("A"),4,0,3),
                new ExplicitBriefingService.Choice(List.of("A"),2,3,3),new ExplicitBriefingService.Choice(List.of("A"),3,0,0)))
            assertThrows(CustomException.class,()->ExplicitBriefingService.validate(c));
        assertEquals(Set.of("A"),ExplicitBriefingService.validate(new ExplicitBriefingService.Choice(List.of("A"),null,null,null)));
    }
    @Test void independentEventsSameCompanyAreAllowedUntilExplicitCapAndDuplicatesNeverFillMinimum(){
        var a=fixtures.candidate("a","contract",3,"A","contract");var b=fixtures.candidate("b","factory",2,"A","factory");
        var c=fixtures.candidate("c","capital",2,"A","capital");var dup=fixtures.candidate("d","contract",3,"A","reprint");
        var all=List.<JsonNode>of(a,b,c,dup);
        assertEquals(List.of(a,b,c),ExplicitBriefingService.select(all,Set.of("A"),3,3));
        assertEquals(List.of(a),ExplicitBriefingService.select(all,Set.of("A"),3,1));
        assertEquals(List.of(a,b),ExplicitBriefingService.select(all,Set.of("A"),2,3));
    }
    @Test void commonPolicySkipsSharedOrMissingPricesInAnEqualImportanceGroup(){
        var a=fixtures.candidate("a","a",2,"A","a");var b=fixtures.candidate("b","b",2,"A","b");
        for(var row:List.of(a,b)){row.putObject("relationSignal").put("value",1);var signal=row.putObject("priceSignal").put("status","observed").put("value",row==a?"1":"9");signal.putArray("basis").add("same-session");signal.putArray("keys").addArray().add("A").add("same-window");}
        assertEquals(List.of(a,b),ExplicitBriefingService.select(List.of(b,a),Set.of("A"),3,3));
        ((tools.jackson.databind.node.ObjectNode)b.path("priceSignal")).putArray("keys").addArray().add("A").add("other-window");
        assertEquals(List.of(b,a),ExplicitBriefingService.select(List.of(a,b),Set.of("A"),3,3));
        a.putObject("priceSignal").put("status","unobserved");
        assertEquals(List.of(a,b),ExplicitBriefingService.select(List.of(b,a),Set.of("A"),3,3));
    }
}
