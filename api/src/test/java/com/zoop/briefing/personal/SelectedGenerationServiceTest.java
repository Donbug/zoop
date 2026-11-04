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
    @Test void unlistedMemberCannotQueuePaidWorkEvenWhenGenerationIsEnabled(){
        when(selection.select("r",owner,choice,"req")).thenReturn(json.createObjectNode().put("selectionVersion","s").put("pendingAnalysisCount",1));
        var service=new SelectedGenerationService(selection,pools,repo,true,new PersonalBriefingAudience("allowed-account",true));
        assertThrows(CustomException.class,()->service.create("r",owner,new SelectedGenerationService.Request(choice,"s"),"req"));
        verifyNoInteractions(repo,pools);
    }
    @Test void prioritySelectionQueuesVersionedInputsEvenWhenLegacyCoreListIsEmpty(){
        var value=json.createObjectNode().put("roundId","r").put("dataAsOf","2026-11-04T00:20:00Z").put("selectionVersion","s").put("poolVersion","p").put("pendingAnalysisCount",1);
        value.set("choice",json.valueToTree(choice));var presentation=value.putObject("presentation");presentation.putArray("items");presentation.putObject("personalPriority").putArray("items").addObject().put("issueId","relative");
        var pool=json.createObjectNode().put("inputSha256","p").put("priorityContract",PriorityPersonalAssembler.VERSION);
        var c=pool.putArray("candidates").addObject().put("issueId","relative");
        c.putObject("priorityAnalysisInput").put("roundId","r").put("issueId","relative").put("inputSha256","new-sha");
        when(selection.select("r",owner,choice,"req")).thenReturn(value);when(pools.pool("r")).thenReturn(Optional.of(pool));
        when(repo.enqueue(eq("owner"),eq("r"),eq("s"),any(),any())).thenReturn("job");
        var job=json.createObjectNode().put("id","job").put("selectionVersion","s");job.set("choice",json.valueToTree(choice));when(repo.job("owner","r","job")).thenReturn(Optional.of(job));
        new SelectedGenerationService(selection,pools,repo,true).create("r",owner,new SelectedGenerationService.Request(choice,"s"),"req");
        var snapshot=org.mockito.ArgumentCaptor.forClass(tools.jackson.databind.JsonNode.class);
        verify(repo).enqueue(eq("owner"),eq("r"),eq("s"),any(),snapshot.capture());
        assertEquals("relative",snapshot.getValue().at("/selectedIssueIds/0").asString());
        assertEquals("new-sha",snapshot.getValue().at("/inputs/0/inputSha256").asString());
        assertEquals(PriorityPersonalAssembler.VERSION,snapshot.getValue().path("priorityContract").asString());
    }
}
