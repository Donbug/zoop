package com.zoop.briefing.personal;

import com.zoop.briefing.query.BriefingGraphContentAuthority;
import com.zoop.briefing.storage.BriefingRound;
import com.zoop.common.exception.CustomException;
import com.zoop.document.evidence.config.DocumentReadProperties;
import java.time.Clock;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.json.JsonMapper;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/** D-BRF-01/02: explicit and retained deliveries must keep main's current graph authority. */
class PersonalCandidateGraphScopeTest {
    @Test void eachRoundUsesItsOwnGraphAndRevokedCandidateNeverReachesDocumentRead() {
        var jdbc=mock(JdbcTemplate.class); var authority=mock(BriefingGraphContentAuthority.class);
        var access=new PersonalCandidateAccess(jdbc,new DocumentReadProperties(null,null,null),Clock.systemUTC(),authority);
        var current=mock(BriefingRound.class); var previous=mock(BriefingRound.class);
        when(current.graphVersion()).thenReturn("gv-current"); when(previous.graphVersion()).thenReturn("gv-previous");
        var context=mock(BriefingGraphContentAuthority.Context.class);
        when(authority.context(anyString(),eq("request"))).thenReturn(context);
        var candidate=JsonMapper.builder().build().createObjectNode().put("issueId","synthetic-issue");
        assertFalse(access.readableForRound(candidate,current,"request"));
        assertFalse(access.readableForRound(candidate,previous,"request"));
        verify(authority).context("gv-current","request"); verify(authority).context("gv-previous","request");
        verify(context,times(2)).allowsCandidate(candidate); verifyNoInteractions(jdbc);
    }
    @Test void unavailableGraphCannotFallBackToSavedCandidatePermission() {
        var jdbc=mock(JdbcTemplate.class); var authority=mock(BriefingGraphContentAuthority.class);
        var access=new PersonalCandidateAccess(jdbc,new DocumentReadProperties(null,null,null),Clock.systemUTC(),authority);
        var round=mock(BriefingRound.class); when(round.graphVersion()).thenReturn("gv-missing");
        when(authority.context(eq("gv-missing"),anyString())).thenThrow(new CustomException(com.zoop.common.exception.ErrorCode.SOURCE_UNAVAILABLE));
        var candidate=JsonMapper.builder().build().createObjectNode().put("verified",true);
        assertThrows(CustomException.class,()->access.readableForRound(candidate,round,"request"));
        verifyNoInteractions(jdbc);
    }
    @Test void retainedMarkerCannotSuppressAnUnavailableNativeGraph() {
        var jdbc=mock(JdbcTemplate.class);var authority=mock(BriefingGraphContentAuthority.class);
        var access=new PersonalCandidateAccess(jdbc,new DocumentReadProperties(null,null,null),Clock.systemUTC(),authority);
        var round=mock(BriefingRound.class);when(round.graphVersion()).thenReturn("gv-revoked");
        var json=JsonMapper.builder().build();var snapshot=json.createObjectNode();
        snapshot.putObject("retainedBasis").put("artifactId","unregistered");
        when(round.publicSnapshot()).thenReturn(snapshot);
        when(authority.context(eq("gv-revoked"),anyString())).thenThrow(new CustomException(com.zoop.common.exception.ErrorCode.SOURCE_UNAVAILABLE));
        assertThrows(CustomException.class,()->access.readableForRound(json.createObjectNode(),round,"request"));
        verify(authority).context("gv-revoked","request");verifyNoInteractions(jdbc);
    }
}
