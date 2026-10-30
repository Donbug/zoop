package com.zoop.briefing.usage;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.nio.file.*;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;

/** Operator-only, no-network reconciliation of original metadata-only receipts already registered in artifacts. */
public final class BriefingUsageArchiveCommand {
    public static void main(String[] args)throws Exception{
        if(args.length!=2)throw new IllegalArgumentException("Use manifest.json operator-admin-id");
        Path path=Path.of(args[0]);if(Files.isSymbolicLink(path)||Files.size(path)>1024*1024)throw new IllegalArgumentException("Manifest unavailable");
        byte[] manifestBytes=Files.readAllBytes(path);String manifestSha=Canonical.sha256(manifestBytes);
        var manifest=StrictJson.parseObject(manifestBytes).exactly(Set.of("schemaVersion","rounds"));
        if(!manifest.string("schemaVersion").equals("briefing-usage-archive-v1"))throw new IllegalArgumentException("Archive contract");
        var source=new DriverManagerDataSource(required("DB_URL"),required("DB_USERNAME"),required("DB_PASSWORD"));
        var jdbc=new JdbcTemplate(source);var tx=new TransactionTemplate(new DataSourceTransactionManager(source));
        var files=ArtifactFileStore.at(Path.of(required("BRIEFING_USAGE_ARTIFACT_ROOT")));
        int[] imported={0};
        tx.executeWithoutResult(status->{
            var admin=jdbc.queryForMap("SELECT email FROM admins WHERE id=? AND status='active' AND role='admin'",args[1]);
            for(JsonNode specification:manifest.array("rounds")){
                String round=specification.path("roundId").asText(),resultId=specification.path("resultArtifactId").asText();
                var rows=jdbc.queryForList("SELECT public_snapshot FROM briefing_rounds WHERE id=? AND published_at IS NOT NULL FOR UPDATE",round);
                if(rows.isEmpty())throw new IllegalArgumentException("Published round required");
                var snapshot=StrictJson.parseObject(rows.getFirst().get("public_snapshot").toString()).node();
                if(!resultId.equals(snapshot.path("replay").path("resultArtifactId").asText()))throw new IllegalArgumentException("Result is not bound to this publication");
                JsonNode result=artifact(jdbc,files,resultId,null);Set<String> digests=new HashSet<>();collect(result,digests);
                for(JsonNode reference:specification.path("calls")){
                    String receiptId=reference.path("receiptArtifactId").asText();
                    JsonNode receipt=artifact(jdbc,files,receiptId,"ai_call_receipt");
                    String digest=receipt.path("requestDigest").asText();
                    if(!digest.matches("[a-f0-9]{64}")||!digests.contains(digest)||!receipt.path("responseSha256").asText().matches("[a-f0-9]{64}"))throw new IllegalArgumentException("Receipt is not bound to the published result");
                    String execution="brf-archive-"+Canonical.sha256(digest+"\n"+receipt.path("responseSha256").asText());
                    var prior=jdbc.queryForList("SELECT a.round_id,e.receipt_artifact_id FROM ai_executions e JOIN briefing_attempts a ON a.id=e.briefing_attempt_id WHERE e.id=?",execution);
                    if(!prior.isEmpty()){
                        if(!round.equals(prior.getFirst().get("round_id"))||!receiptId.equals(prior.getFirst().get("receipt_artifact_id")))throw new IllegalArgumentException("Receipt already belongs to another scope");
                        continue;
                    }
                    String stage=receipt.path("stage").asText(),model=receipt.path("model").asText();
                    if(!stage.matches("[A-Za-z0-9_.-]{1,128}")||!model.matches("[A-Za-z0-9_.:/-]{1,128}"))throw new IllegalArgumentException("Receipt identifiers");
                    String state=receipt.path("status").asText();
                    if(!Set.of("completed","failed","unknown").contains(state))throw new IllegalArgumentException("Receipt state");
                    Instant finished=Instant.parse(receipt.path("finishedAt").asText());if(finished.isAfter(Instant.now().plusSeconds(60)))throw new IllegalArgumentException("Receipt time");
                    String attempt="brfh-"+Canonical.sha256(round+":"+resultId);
                    if(jdbc.queryForObject("SELECT count(*) FROM briefing_attempts WHERE id=?",Integer.class,attempt)==0){
                        int number=jdbc.queryForObject("SELECT COALESCE(max(attempt_no),0)+1 FROM briefing_attempts WHERE round_id=?",Integer.class,round);
                        jdbc.update("""
                            INSERT INTO briefing_attempts(id,round_id,attempt_no,request_key,purpose,trigger,admin_id,admin_email_snapshot,owner_token,status,stages,started_at,finished_at,lease_until)
                            VALUES(?,?,?,?,'history','admin',?,?,?,'completed',jsonb_build_object('purpose','history','inputSha256',CAST(? AS text),'outcome','available','historyImport',jsonb_build_object('coverage','partial','originalAttemptNoKnown',false)),NULL,clock_timestamp(),clock_timestamp())
                            """,attempt,round,number,attempt,args[1],admin.get("email"),UUID.randomUUID().toString(),Canonical.sha256(resultId));
                    }
                    boolean sent=receipt.path("httpStatus").asInt(0)>0;
                    Long input=token(receipt,"inputTokens"),output=token(receipt,"outputTokens");
                    String feature=stage.contains("outlook")||stage.startsWith("company_")?"briefing-outlook":"briefing";
                    jdbc.update("""
                        INSERT INTO ai_executions(id,feature,execution_mode,status,briefing_attempt_id,ai_job_id,ai_attempt_id,stage,attempt_no,provider,model,started_at,finished_at,transmission_confirmed,input_tokens,output_tokens,receipt_artifact_id,actual_cost,estimated_cost,recording_origin)
                        VALUES(?,?,'live',?,?,?, ?,?,1,'openai',?,NULL,?,?,?,?,?,NULL,NULL,'archive')
                        """,execution,feature,state.equals("completed")?"succeeded":state,attempt,"archive:"+digest,receipt.path("responseSha256").asText(),stage,model,Timestamp.from(finished),sent?Boolean.TRUE:null,input,output,receiptId);
                    imported[0]++;
                }
            }
            if(imported[0]>0)jdbc.update("""
                INSERT INTO audit_logs(actor_kind,admin_id,actor_id,actor_email_snapshot,action,target_type,target_id,outcome,purpose,reason,request_id,detail,occurred_at)
                VALUES('admin',?,?,?,'briefing.usage_archive','briefing_usage_archive',?,'succeeded','usage_reconciliation','Verified metadata-only receipt reconciliation',?,jsonb_build_object('importedReceipts',CAST(? AS integer),'coverage','partial'),clock_timestamp())
                """,args[1],args[1],admin.get("email"),manifestSha,"archive-"+UUID.randomUUID(),imported[0]);
        });
        System.out.println("{\"importedReceipts\":"+imported[0]+",\"newModelCalls\":0,\"coverage\":\"partial\"}");
    }
    private static JsonNode artifact(JdbcTemplate jdbc,ArtifactFileStore files,String id,String kind){
        var row=jdbc.queryForMap("SELECT kind,storage_uri,sha256,bytes FROM artifacts WHERE id=?",id);
        if(kind!=null&&!kind.equals(row.get("kind")))throw new IllegalArgumentException("Artifact kind");
        return StrictJson.parseObject(files.readVerified(row.get("storage_uri").toString(),row.get("sha256").toString(),((Number)row.get("bytes")).longValue())).node();
    }
    private static void collect(JsonNode node,Set<String> values){
        if(node.isObject())for(var name:node.propertyNames()){var value=node.get(name);if(name.endsWith("RequestDigest")&&value.isTextual())values.add(value.asText());else collect(value,values);}
        else if(node.isArray())for(var value:node)collect(value,values);
    }
    private static Long token(JsonNode receipt,String name){
        JsonNode v=receipt.get(name);if(!receipt.path("usageKnown").asBoolean(false)||v==null||v.isNull())return null;
        if(!v.isIntegralNumber()||!v.canConvertToLong()||v.asLong()<0)throw new IllegalArgumentException("Invalid usage");return v.asLong();
    }
    private static String required(String key){String value=System.getenv(key);if(value==null||value.isBlank())throw new IllegalArgumentException("Missing "+key);return value;}
}
