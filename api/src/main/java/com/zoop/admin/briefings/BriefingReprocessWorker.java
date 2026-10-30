package com.zoop.admin.briefings;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.sql.Timestamp;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/** Durable dispatch to the existing recorded producer. No client command, shell, prompt, or key is accepted. */
@Component
@ConditionalOnProperty(name="zoop.briefing.reprocess.enabled",havingValue="true")
public class BriefingReprocessWorker {
    final JdbcTemplate jdbc;final BriefingReprocessPolicy policy;final ObjectMapper mapper;final TransactionTemplate tx;
    private final AtomicBoolean busy=new AtomicBoolean();
    public BriefingReprocessWorker(JdbcTemplate jdbc,BriefingReprocessPolicy policy,ObjectMapper mapper,PlatformTransactionManager manager){
        this.jdbc=jdbc;this.policy=policy;this.mapper=mapper;this.tx=new TransactionTemplate(manager);
    }
    @Scheduled(fixedDelayString="${zoop.briefing.reprocess.poll-ms:2000}",initialDelayString="${zoop.briefing.reprocess.initial-delay-ms:2000}")
    public void tick(){
        if(!busy.compareAndSet(false,true))return;
        try{
            recover();
            var jobs=tx.execute(s->{
                var rows=jdbc.queryForList("SELECT id FROM briefing_reprocess_jobs WHERE status='queued' ORDER BY created_at,id LIMIT 1 FOR UPDATE SKIP LOCKED");
                if(!rows.isEmpty())jdbc.update("UPDATE briefing_reprocess_jobs SET status='running' WHERE id=?",rows.getFirst().get("id"));
                return rows;
            });
            if(jobs!=null && !jobs.isEmpty())run((String)jobs.getFirst().get("id"));
        }catch(RuntimeException ignored){/* Never log a provider body, SQL value, prompt or credential. Durable rows retain bounded failure codes. */}
        finally{busy.set(false);}
    }
    private void run(String id){
        Process process=null;
        try{
            var job=jdbc.queryForMap("""
                SELECT j.*,a.owner_token,a.attempt_no,r.round_date,r.edition,r.scheduled_at,r.window_from,r.window_to,
                    f.storage_uri,f.sha256,f.bytes FROM briefing_reprocess_jobs j JOIN briefing_attempts a ON a.id=j.attempt_id
                    JOIN briefing_rounds r ON r.id=j.round_id JOIN artifacts f ON f.id=j.input_artifact_id WHERE j.id=?
                """,id);
            byte[] input=ArtifactFileStore.at(policy.root).readVerified((String)job.get("storage_uri"),(String)job.get("sha256"),((Number)job.get("bytes")).longValue());
            Path directory=directory(id),output=directory.resolve("output"),usage=output.resolve("usage");
            mkdir(output);mkdir(usage);
            var claim=mapper.createObjectNode().put("attemptId",job.get("attempt_id").toString()).put("ownerToken",job.get("owner_token").toString())
                .put("roundId",job.get("round_id").toString()).put("attemptNo",((Number)job.get("attempt_no")).intValue());
            immutable(usage.resolve("attempt.json"),Canonical.bytes(claim));
            immutable(directory.resolve("input.json"),input);
            ObjectNode spec=mapper.createObjectNode().put("schemaVersion","briefing-recorded-producer-v1").put("operation",job.get("operation").toString())
                .put("requestKey",id).put("trigger","admin").put("adminId",job.get("admin_id").toString())
                .put("inputArtifactId",job.get("input_artifact_id").toString()).put("inputFile","input.json").put("inputSha256",job.get("sha256").toString())
                .put("maxCalls",((Number)job.get("max_calls")).intValue()).put("authorizationRef",job.get("authorization_ref").toString());
            var round=spec.putObject("round").put("id",job.get("round_id").toString()).put("date",job.get("round_date").toString()).put("edition",job.get("edition").toString())
                .put("scheduledAt",instant(job,"scheduled_at")).put("windowTo",instant(job,"window_to")).put("windowFrom",instant(job,"window_from"));
            byte[] specBytes=Canonical.bytes(spec);immutable(directory.resolve("job.json"),specBytes);
            List<String> command=new ArrayList<>(policy.command);command.add(directory.resolve("job.json").toString());command.add(output.toString());
            var builder=new ProcessBuilder(command).directory(directory.toFile()).redirectOutput(ProcessBuilder.Redirect.DISCARD).redirectError(ProcessBuilder.Redirect.DISCARD);
            builder.environment().put("BRIEFING_USAGE_ARTIFACT_ROOT",policy.root.toString());
            process=builder.start();
            if(!process.waitFor(900,TimeUnit.SECONDS)){terminate(process);throw new IllegalStateException("timeout");}
            if(process.exitValue()!=0)throw new IllegalStateException("producer_failed");
            complete(id,output.resolve("result.json"),Canonical.sha256(specBytes));
        }catch(Exception failure){
            if(process!=null && process.isAlive())terminate(process);
            fail(id,"reprocess_worker_failed");
        }
    }
    private void complete(String id,Path path,String jobSha){
        if(!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS))throw new IllegalStateException("result_missing");
        try{
            if(Files.size(path)>16*1024*1024)throw new IllegalStateException("result_too_large");
            byte[] bytes=Files.readAllBytes(path);var result=StrictJson.parseObject(bytes);
            if(!jobSha.equals(result.string("jobSha256")))throw new IllegalStateException("result_binding");
            var job=jdbc.queryForMap("SELECT j.*,a.status AS attempt_status,a.stages FROM briefing_reprocess_jobs j JOIN briefing_attempts a ON a.id=j.attempt_id WHERE j.id=?",id);
            if(!"completed".equals(job.get("attempt_status")) || !result.string("outcome").equals(StrictJson.parseObject(job.get("stages").toString()).string("outcome")))throw new IllegalStateException("attempt_incomplete");
            String artifact="brf-result-"+Canonical.sha256(id);
            try(var store=ArtifactFileStore.at(policy.root).open()){
                var file=store.put("briefing_reprocess_results",artifact+".json",bytes);
                tx.executeWithoutResult(s->{
                    jdbc.update("INSERT INTO artifacts(id,kind,storage_uri,sha256,bytes,media_type,created_at) VALUES(?,'analysis_result',?,?,?,'application/json',clock_timestamp()) ON CONFLICT(id) DO NOTHING",artifact,file.uri(),file.sha256(),file.bytes());
                    if(result.string("outcome").equals("available"))jdbc.update("UPDATE briefing_rounds SET stages=jsonb_set(stages,'{save}',jsonb_build_object('status','done','at',clock_timestamp(),'resultArtifactId',CAST(? AS text))) WHERE id=? AND published_at IS NULL",artifact,job.get("round_id"));
                    jdbc.update("UPDATE briefing_reprocess_jobs SET status=?,finished_at=clock_timestamp(),failure_code=? WHERE id=? AND status='running'",result.string("outcome").equals("available")?"completed":"failed",result.string("outcome").equals("available")?null:"verification_withheld",id);
                });
            }
        }catch(java.io.IOException error){throw new IllegalStateException("result_unavailable");}
    }
    /** A terminated worker never blindly resends an ambiguous live call. The next manual request gets a new attempt. */
    private void recover(){
        var jobs=jdbc.queryForList("SELECT j.id,a.status,a.lease_until FROM briefing_reprocess_jobs j JOIN briefing_attempts a ON a.id=j.attempt_id WHERE j.status='running'");
        for(var j:jobs){
            if(Set.of("completed","failed","cancelled").contains(j.get("status"))){
                try{
                    Path dir=directory(j.get("id").toString());
                    complete(j.get("id").toString(),dir.resolve("output/result.json"),Canonical.sha256(Files.readAllBytes(dir.resolve("job.json"))));
                }catch(Exception e){fail(j.get("id").toString(),"reprocess_result_unavailable");}
            }else if(((Timestamp)j.get("lease_until")).toInstant().isBefore(java.time.Instant.now()))fail(j.get("id").toString(),"reprocess_worker_lease_expired");
        }
    }
    private void fail(String id,String code){
        tx.executeWithoutResult(s->{
            var refs=jdbc.queryForList("SELECT round_id FROM briefing_reprocess_jobs WHERE id=?",id);if(refs.isEmpty())return;
            jdbc.queryForList("SELECT id FROM briefing_rounds WHERE id=? FOR UPDATE",refs.getFirst().get("round_id"));
            var rows=jdbc.queryForList("SELECT j.*,a.status AS attempt_status,a.owner_token,a.stages FROM briefing_reprocess_jobs j JOIN briefing_attempts a ON a.id=j.attempt_id WHERE j.id=? FOR UPDATE OF j,a",id);if(rows.isEmpty())return;
            var row=rows.getFirst();
            if(Set.of("queued","running","verifying").contains(row.get("attempt_status"))){
                jdbc.update("UPDATE ai_executions SET status='unknown',error_code=? WHERE briefing_attempt_id=? AND status='running' AND receipt_artifact_id IS NULL",code,row.get("attempt_id"));
                jdbc.update("UPDATE briefing_attempts SET status='failed',finished_at=clock_timestamp(),failure_reason=?,stages=stages||jsonb_build_object('outcome','failed','failureStage','admin_worker') WHERE id=?",code,row.get("attempt_id"));
                jdbc.update("UPDATE briefing_rounds SET status='failed',failure_reason=?,generation_token=NULL,lease_until=NULL WHERE id=? AND published_at IS NULL AND generation_token=?",code,row.get("round_id"),row.get("owner_token"));
            }
            jdbc.update("UPDATE briefing_reprocess_jobs SET status='failed',finished_at=clock_timestamp(),failure_code=? WHERE id=? AND status IN ('queued','running')",code,id);
        });
    }
    private Path directory(String id)throws java.io.IOException{
        if(!id.matches("brfr-[0-9a-f-]{36}"))throw new IllegalArgumentException("job_id");
        Path parent=policy.root.resolve("admin_reprocessing");mkdir(parent);Path result=parent.resolve(id);mkdir(result);return result;
    }
    private static void mkdir(Path p)throws java.io.IOException{
        if(!Files.exists(p,LinkOption.NOFOLLOW_LINKS))Files.createDirectory(p,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        if(Files.isSymbolicLink(p) || !Files.isDirectory(p) || !Files.getPosixFilePermissions(p).equals(PosixFilePermissions.fromString("rwx------")))throw new IllegalStateException("private_directory_required");
    }
    private static void immutable(Path p,byte[] data)throws java.io.IOException{
        if(Files.exists(p,LinkOption.NOFOLLOW_LINKS)){
            if(Files.isSymbolicLink(p)||!Files.isRegularFile(p)||!Arrays.equals(Files.readAllBytes(p),data))throw new IllegalStateException("job_identity_conflict");return;
        }
        Files.write(p,data,StandardOpenOption.CREATE_NEW);Files.setPosixFilePermissions(p,PosixFilePermissions.fromString("rw-------"));
    }
    private static String instant(Map<String,Object> row,String key){return row.get(key)==null?null:((Timestamp)row.get(key)).toInstant().toString();}
    private static void terminate(Process p){p.descendants().forEach(ProcessHandle::destroy);p.destroy();try{if(!p.waitFor(5,TimeUnit.SECONDS))p.destroyForcibly();}catch(InterruptedException e){Thread.currentThread().interrupt();}}
}
