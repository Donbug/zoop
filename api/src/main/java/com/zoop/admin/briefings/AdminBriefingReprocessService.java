package com.zoop.admin.briefings;

import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.briefing.usage.BriefingUsageLedger;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.time.Duration;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

@Service
public class AdminBriefingReprocessService {
    final JdbcTemplate jdbc;final BriefingReprocessPolicy policy;final PlatformTransactionManager transactions;
    final ObjectMapper mapper;final AdminBriefingService reads;
    public AdminBriefingReprocessService(JdbcTemplate jdbc,BriefingReprocessPolicy policy,PlatformTransactionManager transactions,ObjectMapper mapper,AdminBriefingService reads){
        this.jdbc=jdbc;this.policy=policy;this.transactions=transactions;this.mapper=mapper;this.reads=reads;
    }
    @Transactional
    public ObjectNode submit(String id,String rawReason,String key,AdminPrincipal admin,String requestId){
        String reason=rawReason.strip();
        if(reason.isBlank() || reason.length()>500 || reason.chars().anyMatch(Character::isISOControl))throw new CustomException(ErrorCode.INVALID_REQUEST);
        String hash=Canonical.sha256(reason);
        var round=jdbc.queryForList("SELECT * FROM briefing_rounds WHERE id=? FOR UPDATE",id);
        if(round.isEmpty())throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        var same=jdbc.queryForList("SELECT request_hash,response FROM briefing_reprocess_jobs WHERE admin_id=? AND round_id=? AND request_key=?",admin.adminId(),id,key);
        if(!same.isEmpty()){
            if(!hash.equals(same.getFirst().get("request_hash")))throw new CustomException(ErrorCode.VERSION_UNAVAILABLE);
            return (ObjectNode)mapper.readTree(same.getFirst().get("response").toString());
        }
        String blocked=policy.blocked(id);
        if(blocked!=null)throw new CustomException(policy.enabled?ErrorCode.VERSION_UNAVAILABLE:ErrorCode.SOURCE_UNAVAILABLE);
        var input=jdbc.queryForMap("SELECT p.*,a.storage_uri,a.sha256,a.bytes FROM briefing_reprocess_inputs p JOIN artifacts a ON a.id=p.input_artifact_id WHERE p.round_id=? AND p.enabled",id);
        // Verify the actual immutable input before recording a runnable job.
        byte[] bytes=ArtifactFileStore.at(policy.root).readVerified((String)input.get("storage_uri"),(String)input.get("sha256"),((Number)input.get("bytes")).longValue());
        if(bytes.length>4*1024*1024)throw new CustomException(ErrorCode.INVALID_REQUEST);
        StrictJson.parseObject(bytes);
        var r=round.getFirst();String job="brfr-"+UUID.randomUUID();
        ObjectNode claim=mapper.createObjectNode().put("op","claim").put("requestKey",job).put("purpose","generation").put("trigger","admin")
            .put("adminId",admin.adminId()).put("inputArtifactId",(String)input.get("input_artifact_id")).put("inputDigest",(String)input.get("sha256"));
        ObjectNode identity=claim.putObject("round").put("id",id).put("date",r.get("round_date").toString()).put("edition",r.get("edition").toString())
            .put("scheduledAt",((java.sql.Timestamp)r.get("scheduled_at")).toInstant().toString()).put("windowTo",((java.sql.Timestamp)r.get("window_to")).toInstant().toString());
        identity.put("windowFrom",r.get("window_from")==null?null:((java.sql.Timestamp)r.get("window_from")).toInstant().toString());
        var ledger=new BriefingUsageLedger(new NamedParameterJdbcTemplate(jdbc),transactions,policy.root,Duration.ofSeconds(900),true);
        var attempt=ledger.execute(StrictJson.Obj.of(claim));
        ObjectNode response=reads.detail(id);
        jdbc.update("""
            INSERT INTO briefing_reprocess_jobs(id,round_id,attempt_id,admin_id,request_key,request_hash,reason,operation,input_artifact_id,max_calls,authorization_ref,status,response)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,'queued',?::jsonb)
            """,job,id,attempt.path("attemptId").asText(),admin.adminId(),key,hash,reason,input.get("operation"),input.get("input_artifact_id"),input.get("max_calls"),input.get("authorization_ref"),response.toString());
        jdbc.update("""
            INSERT INTO audit_logs(actor_kind,admin_id,actor_id,actor_email_snapshot,action,target_type,target_id,outcome,purpose,reason,request_id,detail,occurred_at)
            VALUES('admin',?,?,?,'briefing.reprocess','briefing_round',?,'succeeded','briefing_reprocessing',?,?,jsonb_build_object('attemptId',CAST(? AS text)),clock_timestamp())
            """,admin.adminId(),admin.adminId(),admin.email(),id,reason,requestId,attempt.path("attemptId").asText());
        return response;
    }
}
