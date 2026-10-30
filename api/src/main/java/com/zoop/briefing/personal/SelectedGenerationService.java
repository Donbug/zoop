package com.zoop.briefing.personal;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.common.exception.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;
import java.util.*;
@Service
public class SelectedGenerationService {
    public record Request(ExplicitBriefingService.Choice choice,String selectionVersion) {}
    private final ExplicitBriefingService selections;
    private final PersonalBriefingRepository pools;
    private final SelectedGenerationRepository jobs;
    private final boolean enabled;
    private final JsonMapper json=JsonMapper.builder().build();
    public SelectedGenerationService(ExplicitBriefingService selections,PersonalBriefingRepository pools,SelectedGenerationRepository jobs,
            @Value("${zoop.briefing.selected-generation-enabled:false}")boolean enabled){this.selections=selections;this.pools=pools;this.jobs=jobs;this.enabled=enabled;}
    @Transactional(timeout=10)
    public ObjectNode create(String roundId,MemberPrincipal member,Request request,String requestId){
        if(member==null)throw new CustomException(ErrorCode.AUTH_REQUIRED);
        if(request==null||request.selectionVersion()==null)throw new CustomException(ErrorCode.INVALID_REQUEST);
        var selection=selections.select(roundId,member,request.choice(),requestId);
        if(!request.selectionVersion().equals(selection.path("selectionVersion").asString()))throw new CustomException(ErrorCode.REVISION_CONFLICT);
        if(!enabled && selection.path("pendingAnalysisCount").asInt()>0)throw new CustomException(ErrorCode.MODEL_UNAVAILABLE);
        var pool=pools.pool(roundId).orElseThrow(()->new CustomException(ErrorCode.SOURCE_UNAVAILABLE));
        if(!pool.path("inputSha256").equals(selection.path("poolVersion")))throw new CustomException(ErrorCode.REVISION_CONFLICT);
        var snapshot=json.createObjectNode().put("roundId",roundId).put("cutoff",selection.path("dataAsOf").asString()).put("poolVersion",pool.path("inputSha256").asString())
            .put("selectionVersion",request.selectionVersion());
        snapshot.set("selection",selection.deepCopy());var ids=snapshot.putArray("selectedIssueIds");var inputs=snapshot.putArray("inputs");
        for(var selected:selection.path("presentation").path("items")){
            String id=selected.path("eventId").asString();ids.add(id);
            var candidate=pool.path("candidates").valueStream().filter(c->id.equals(c.path("issueId").asString())).findFirst().orElseThrow(()->new CustomException(ErrorCode.REVISION_CONFLICT));
            var input=candidate.path("analysisInput");
            if(candidate.path("sharedView").isObject() || jobs.analysis(roundId,id,input.path("inputSha256").asString()).isPresent())continue;
            if(!input.isObject() || !input.path("roundId").asString().equals(roundId) || !input.path("issueId").asString().equals(id))throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
            inputs.add(input.deepCopy());
        }
        String id=jobs.enqueue(member.memberId(),roundId,request.selectionVersion(),selection.path("choice"),snapshot);
        return get(roundId,id,member,requestId);
    }
    @Transactional(timeout=10)
    public ObjectNode retry(String roundId,String previousId,MemberPrincipal member,String requestId){
        var previous=get(roundId,previousId,member,requestId);
        if(!enabled || "stale".equals(previous.path("status").asString()))throw new CustomException(ErrorCode.JOB_NOT_RETRYABLE);
        return get(roundId,jobs.retry(member.memberId(),roundId,previousId),member,requestId);
    }
    public ObjectNode get(String roundId,String id,MemberPrincipal member,String requestId){
        if(member==null)throw new CustomException(ErrorCode.AUTH_REQUIRED);
        var job=jobs.job(member.memberId(),roundId,id).orElseThrow(()->new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
        var choice=json.treeToValue(job.path("choice"),ExplicitBriefingService.Choice.class);
        var latest=selections.select(roundId,member,choice,requestId);
        if(!job.path("selectionVersion").equals(latest.path("selectionVersion")))job.put("status","stale");
        else job.set("selection",latest);
        // The input and provider receipts remain private; only this member sees this job.
        job.remove("request");return job;
    }
}
