package com.zoop.briefing.personal;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.common.exception.CustomException;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
class SelectedGenerationServiceTest {
    final JsonMapper json=JsonMapper.builder().build();
    final ExplicitBriefingService selection=mock(ExplicitBriefingService.class);
    final PersonalBriefingRepository pools=mock(PersonalBriefingRepository.class);
    final SelectedGenerationRepository repo=mock(SelectedGenerationRepository.class);
    final MemberPrincipal owner=new MemberPrincipal("owner","session");
    final ExplicitBriefingService.Choice choice=new ExplicitBriefingService.Choice(List.of("A"),3,0,3);
    @Test void aChangedSelectionNeverEnqueuesOrSendsFrozenSources(){
        var value=json.createObjectNode().put("selectionVersion","current");when(selection.select("r",owner,choice,"req")).thenReturn(value);
        var service=new SelectedGenerationService(selection,pools,repo,true);
        assertThrows(CustomException.class,()->service.create("r",owner,new SelectedGenerationService.Request(choice,"old"),"req"));
        verifyNoInteractions(repo,pools);
    }
    @Test void otherMemberCannotInspectJobOrItsPrivateScope(){
        var service=new SelectedGenerationService(selection,pools,repo,true);
        when(repo.job("owner","r","job")).thenReturn(Optional.empty());
        assertThrows(CustomException.class,()->service.get("r","job",owner,"req"));verifyNoInteractions(selection);
    }
    @Test void changedRoundPoolReturnsStaleWithoutASelectionAndHidesPrivateRequest(){
        var job=json.createObjectNode().put("id","job").put("status","ready").put("selectionVersion","old");job.set("choice",json.valueToTree(choice));job.putObject("request").put("private","kept-in-db");
        when(repo.job("owner","r","job")).thenReturn(Optional.of(job));when(selection.select("r",owner,choice,"req")).thenReturn(json.createObjectNode().put("selectionVersion","new"));
        var result=new SelectedGenerationService(selection,pools,repo,true).get("r","job",owner,"req");
        assertEquals("stale",result.path("status").asString());assertFalse(result.has("request"));assertFalse(result.has("selection"));
    }
    @Test void missingAnalysisDoesNotStartPaidGenerationWithoutOperatorEnablement(){
        when(selection.select("r",owner,choice,"req")).thenReturn(json.createObjectNode().put("selectionVersion","s").put("pendingAnalysisCount",1));
        assertThrows(CustomException.class,()->new SelectedGenerationService(selection,pools,repo,false).create("r",owner,new SelectedGenerationService.Request(choice,"s"),"req"));verifyNoInteractions(repo);
    }
}
