package com.zoop.briefing.personal;
import com.zoop.common.json.StrictJson;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;
import java.util.*;
@Repository
public class SelectedGenerationRepository {
    private final JdbcTemplate jdbc;
    private final JsonMapper json=JsonMapper.builder().build();
    public SelectedGenerationRepository(JdbcTemplate jdbc){this.jdbc=jdbc;}
    public Optional<JsonNode> analysis(String roundId,String issueId,String inputSha){
        return jdbc.query("SELECT view FROM briefing_shared_issue_analyses WHERE round_id=? AND issue_id=? AND input_sha256=? AND view_sha256=encode(sha256(convert_to(view::text,'UTF8')),'hex')",
            (r,i)->StrictJson.parseObject(r.getString(1)).node(),roundId,issueId,inputSha).stream().findFirst();
    }
    public String enqueue(String member,String round,String selection,JsonNode choice,JsonNode snapshot){
        var prior=jdbc.query("SELECT id FROM briefing_selected_generation_jobs WHERE member_id=? AND round_id=? AND selection_version=? ORDER BY attempt_no DESC LIMIT 1",(r,i)->r.getString(1),member,round,selection);
        if(!prior.isEmpty())return prior.getFirst();
        String id="selgen-"+UUID.randomUUID();
        jdbc.update("INSERT INTO briefing_selected_generation_jobs(id,member_id,round_id,selection_version,choice,request_snapshot,request_sha256) VALUES (?,?,?,?,?::jsonb,?::jsonb,encode(sha256(convert_to((?::jsonb)::text,'UTF8')),'hex')) ON CONFLICT(member_id,round_id,selection_version,attempt_no) DO NOTHING",
            id,member,round,selection,choice.toString(),snapshot.toString(),snapshot.toString());
        return jdbc.queryForObject("SELECT id FROM briefing_selected_generation_jobs WHERE member_id=? AND round_id=? AND selection_version=? ORDER BY attempt_no DESC LIMIT 1",String.class,member,round,selection);
    }
    public String retry(String member,String round,String previousId){
        var old=jdbc.query("SELECT selection_version,attempt_no,status FROM briefing_selected_generation_jobs WHERE id=? AND member_id=? AND round_id=? FOR UPDATE",(r,i)->List.of(r.getString(1),r.getInt(2),r.getString(3)),previousId,member,round);
        if(old.isEmpty())throw new com.zoop.common.exception.CustomException(com.zoop.common.exception.ErrorCode.RESOURCE_NOT_FOUND);
        var row=old.getFirst();
        if(!Set.of("partial","withheld").contains(row.get(2)) || (Integer)row.get(1)>=2)throw new com.zoop.common.exception.CustomException(com.zoop.common.exception.ErrorCode.JOB_NOT_RETRYABLE);
        String id="selgen-"+UUID.randomUUID();
        jdbc.update("INSERT INTO briefing_selected_generation_jobs(id,member_id,round_id,selection_version,choice,request_snapshot,request_sha256,attempt_no,retry_of) SELECT ?,member_id,round_id,selection_version,choice,request_snapshot,request_sha256,attempt_no+1,id FROM briefing_selected_generation_jobs WHERE id=? AND member_id=? ON CONFLICT(member_id,round_id,selection_version,attempt_no) DO NOTHING",id,previousId,member);
        return jdbc.queryForObject("SELECT id FROM briefing_selected_generation_jobs WHERE member_id=? AND round_id=? AND selection_version=? AND attempt_no=2",String.class,member,round,row.get(0));
    }
    public Optional<ObjectNode> job(String member,String round,String id){
        return jdbc.query("SELECT id,selection_version,choice,request_snapshot,status,outcome,created_at,finished_at,attempt_no FROM briefing_selected_generation_jobs WHERE member_id=? AND round_id=? AND id=? AND request_sha256=encode(sha256(convert_to(request_snapshot::text,'UTF8')),'hex')",(r,i)->{
            var out=json.createObjectNode().put("id",r.getString(1)).put("selectionVersion",r.getString(2));
            out.set("choice",StrictJson.parseObject(r.getString(3)).node());out.set("request",StrictJson.parseObject(r.getString(4)).node());out.put("status",r.getString(5));
            out.set("outcome",r.getString(6)==null?json.nullNode():StrictJson.parseObject(r.getString(6)).node());
            out.put("attempt",r.getInt(9));out.put("createdAt",r.getTimestamp(7).toInstant().toString());out.put("finishedAt",r.getTimestamp(8)==null?null:r.getTimestamp(8).toInstant().toString());return out;
        },member,round,id).stream().findFirst();
    }
}
