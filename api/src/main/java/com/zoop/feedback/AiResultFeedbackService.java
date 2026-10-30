package com.zoop.feedback;

import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.chat.service.ChatService;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.document.evidence.service.EvidenceService;
import java.sql.Timestamp;
import java.time.Clock;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/** Membership + current public read guards remain the authority for a feedback target. */
@Service
public class AiResultFeedbackService {
    static final Set<String> FEATURES=Set.of("chatbot_answer","news_summary");
    final JdbcTemplate jdbc;final ChatService chat;final EvidenceService evidence;final ObjectMapper mapper;final Clock clock;
    public AiResultFeedbackService(JdbcTemplate jdbc,ChatService chat,EvidenceService evidence,ObjectMapper mapper,Clock clock){this.jdbc=jdbc;this.chat=chat;this.evidence=evidence;this.mapper=mapper;this.clock=clock;}
    record Target(String version,String job,String evidence){}
    Target target(String member,String feature,String id){
        if(feature.equals("chatbot_answer")){
            var rows=jdbc.queryForList("SELECT j.id FROM chat_jobs j JOIN chat_sessions s ON s.id=j.session_id WHERE j.message_id=? AND s.member_id=?",id,member);
            if(rows.isEmpty())throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
            var result=chat.getJob(new MemberPrincipal(member,"feedback-read"),rows.getFirst().get("id").toString());
            String version=result.feedbackVersion();
            if(version==null || result.result()==null || !id.equals(result.result().messageId()))throw new CustomException(ErrorCode.VERSION_UNAVAILABLE);
            return new Target(version,result.id(),null);
        }
        var result=evidence.read(id,null,null,null,null,"feedback-read");
        if(result.documentSummary()==null || result.resultVersion()==null || !result.resultVersion().equals(result.documentSummary().path("resultVersion").asText()))throw new CustomException(ErrorCode.VERSION_UNAVAILABLE);
        return new Target(result.resultVersion(),null,id);
    }
    ObjectNode put(MemberPrincipal member,String feature,String id,String version,String value,String reason){
        // Lock the parent member to serialize the first concurrent vote as well as updates.
        var owners=jdbc.queryForList("SELECT status FROM members WHERE id=? FOR UPDATE",member.memberId());
        if(owners.isEmpty()||!"active".equals(owners.getFirst().get("status")))throw new CustomException(ErrorCode.MEMBER_BLOCKED);
        var old=jdbc.queryForList("SELECT * FROM ai_result_feedback WHERE member_id=? AND feature=? AND target_id=? FOR UPDATE",member.memberId(),feature,id);
        if(value.equals("none")&&!old.isEmpty()){
            if(!version.equals(old.getFirst().get("target_version")))throw new CustomException(ErrorCode.VERSION_UNAVAILABLE);
            jdbc.update("UPDATE ai_result_feedback SET value='none',reason=NULL,updated_at=? WHERE id=? AND value<>'none'",Timestamp.from(clock.instant()),old.getFirst().get("id"));
        }else{
            Target target=target(member.memberId(),feature,id);
            if(!version.equals(target.version()))throw new CustomException(ErrorCode.VERSION_UNAVAILABLE);
            Timestamp now=Timestamp.from(clock.instant());
            jdbc.update("""
                INSERT INTO ai_result_feedback(id,member_id,feature,target_id,target_version,chat_job_id,evidence_id,value,reason,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(member_id,feature,target_id) DO UPDATE
                SET target_version=excluded.target_version,value=excluded.value,reason=excluded.reason,updated_at=excluded.updated_at
                WHERE (ai_result_feedback.target_version,ai_result_feedback.value,ai_result_feedback.reason)
                    IS DISTINCT FROM (excluded.target_version,excluded.value,excluded.reason)
                """,UUID.randomUUID().toString(),member.memberId(),feature,id,version,target.job(),target.evidence(),value,reason,now,now);
        }
        return out(jdbc.queryForMap("SELECT * FROM ai_result_feedback WHERE member_id=? AND feature=? AND target_id=?",member.memberId(),feature,id));
    }
    List<Map<String,Object>> currentRows(String member,java.time.Instant asOf){
        List<Object> args=new ArrayList<>();args.add(Timestamp.from(asOf));
        String filter=member==null?"":" AND f.member_id=?";if(member!=null)args.add(member);
        var rows=jdbc.queryForList("SELECT f.*,m.email AS owner_email,m.display_name AS owner_name FROM ai_result_feedback f JOIN members m ON m.id=f.member_id WHERE f.updated_at<=? AND m.status='active'"+filter,args.toArray());
        List<Map<String,Object>> current=new ArrayList<>();
        for(var row:rows){
            try{
                Target target=target(row.get("member_id").toString(),row.get("feature").toString(),row.get("target_id").toString());
                if(target.version().equals(row.get("target_version")))current.add(row);
            }catch(CustomException e){
                if(!Set.of(ErrorCode.RESOURCE_NOT_FOUND,ErrorCode.EVIDENCE_UNAVAILABLE,ErrorCode.VERSION_UNAVAILABLE,ErrorCode.ACCESS_DENIED,ErrorCode.MEMBER_BLOCKED).contains(e.getErrorCode()))throw e;
            }
        }
        return current;
    }
    ObjectNode out(Map<String,Object> row){return mapper.createObjectNode().put("feature",row.get("feature").toString()).put("targetId",row.get("target_id").toString()).put("targetVersion",row.get("target_version").toString()).put("value",row.get("value").toString()).put("reason",(String)row.get("reason"));}
}
