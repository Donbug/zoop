package com.zoop.briefing.usage;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.function.Supplier;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.StrictJson;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

/** FS068 producer boundary. Each observation commits independently of model/result processing. No model is called here. */
public final class BriefingUsageLedger {
    private static final Set<String> ACTIVE = Set.of("queued", "running", "verifying");
    private final NamedParameterJdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final ArtifactFileStore files;
    private final int leaseSeconds;

    public BriefingUsageLedger(NamedParameterJdbcTemplate jdbc, PlatformTransactionManager manager, Path artifactRoot,
            Duration lease) {
        this(jdbc, manager, artifactRoot, lease, false);
    }

    /** Admin admission joins its audit/idempotency transaction; model observations retain independent commits. */
    public BriefingUsageLedger(NamedParameterJdbcTemplate jdbc, PlatformTransactionManager manager, Path artifactRoot,
            Duration lease, boolean joinTransaction) {
        this.jdbc = jdbc;
        this.tx = new TransactionTemplate(manager);
        tx.setPropagationBehavior(joinTransaction ? TransactionDefinition.PROPAGATION_REQUIRED : TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        this.files = ArtifactFileStore.at(artifactRoot);
        this.leaseSeconds = Math.toIntExact(lease.toSeconds());
        require(leaseSeconds >= 30 && leaseSeconds <= 900, "invalid_lease");
    }

    public ObjectNode execute(StrictJson.Obj command) {
        return switch (command.string("op")) {
            case "claim" -> claim(command);
            case "heartbeat" -> heartbeat(command);
            case "model_start" -> modelStart(command);
            case "model_finish" -> modelFinish(command);
            case "local" -> local(command);
            case "finish" -> finish(command);
            default -> throw new Rejected("unknown_ledger_operation");
        };
    }

    private ObjectNode claim(StrictJson.Obj c) {
        c.exactly(Set.of("op","round","requestKey","purpose","trigger","adminId","inputArtifactId","inputDigest"));
        require(StrictJson.SHA256.matcher(c.string("inputDigest")).matches(),"invalid_input_digest");
        StrictJson.Obj r = c.object("round").exactly(Set.of("id","date","edition","scheduledAt","windowFrom","windowTo"));
        String rid = identifier(r.string("id")), requestKey = identifier(c.string("requestKey"));
        String purpose = choice(c.string("purpose"), Set.of("generation","outlook"));
        String trigger = choice(c.string("trigger"), Set.of("scheduler","admin"));
        String admin = c.stringOrNull("adminId"), input = c.stringOrNull("inputArtifactId");
        LocalDate date = LocalDate.parse(r.string("date"));
        String edition = choice(r.string("edition"), Set.of("morning","evening"));
        Instant scheduled = Instant.parse(r.string("scheduledAt")), end = Instant.parse(r.string("windowTo"));
        Instant from = r.isNull("windowFrom") ? null : Instant.parse(r.string("windowFrom"));
        require(end.equals(scheduled) && (from == null || from.isBefore(end)), "invalid_round_window");
        require(scheduled.atOffset(java.time.ZoneOffset.ofHours(9)).toLocalDate().equals(date), "invalid_round_date");
        return tx.execute(status -> {
            // Same request keys serialize even before a round exists. Hash collisions only serialize extra work.
            jdbc.queryForObject("SELECT pg_advisory_xact_lock(hashtext(:key)) IS NULL", params("key",requestKey), Boolean.class);
            jdbc.update("""
                INSERT INTO briefing_rounds(id,round_date,edition,scheduled_at,window_from,window_to,open_start)
                VALUES(:id,:date,:edition,:scheduled,:from,:end,:open) ON CONFLICT DO NOTHING
                """, params("id",rid,"date",date,"edition",edition,"scheduled",at(scheduled),"from",at(from),"end",at(end),"open",from==null));
            Map<String,Object> round = round(rid);
            require(date.equals(round.get("round_date")) || date.toString().equals(round.get("round_date").toString()), "round_identity_conflict");
            require(edition.equals(round.get("edition")) && scheduled.equals(instant(round,"scheduled_at"))
                && end.equals(instant(round,"window_to")) && java.util.Objects.equals(from,instant(round,"window_from")), "round_identity_conflict");
            List<Map<String,Object>> same = jdbc.queryForList("SELECT * FROM briefing_attempts WHERE request_key=:key", params("key",requestKey));
            if (!same.isEmpty()) {
                Map<String,Object> a = same.getFirst();
                require(rid.equals(a.get("round_id")) && purpose.equals(a.get("purpose")) && trigger.equals(a.get("trigger"))
                    && java.util.Objects.equals(admin,a.get("admin_id")) && java.util.Objects.equals(input,a.get("input_artifact_id")), "request_identity_conflict");
                require(c.string("inputDigest").equals(StrictJson.parseObject(a.get("stages").toString()).string("inputSha256")),"request_identity_conflict");
                return attempt(a,true);
            }
            Instant now = now();
            List<Map<String,Object>> active = jdbc.queryForList("SELECT * FROM briefing_attempts WHERE round_id=:id AND status IN ('queued','running','verifying') FOR UPDATE", params("id",rid));
            if (!active.isEmpty()) {
                Map<String,Object> old = active.getFirst();
                require(!instant(old,"lease_until").isAfter(now), "round_already_running");
                List<String> lastStage=jdbc.query("SELECT stage FROM ai_executions WHERE briefing_attempt_id=:id ORDER BY started_at DESC,id DESC LIMIT 1",
                    params("id",old.get("id")),(rs,n)->rs.getString(1));
                outcome(old,"failed",lastStage.isEmpty()?"claim":lastStage.getFirst());
                close(old,"failed","lease_expired","failed",now);
                // Running observations survive process loss. Late real receipts can still complete the same rows.
                jdbc.update("UPDATE ai_executions SET status='unknown',error_code='worker_lease_expired' WHERE briefing_attempt_id=:id AND status='running' AND receipt_artifact_id IS NULL",params("id",old.get("id")));
            }
            boolean published = round.get("published_at") != null;
            require(!published || purpose.equals("outlook"), "published_round_generation_forbidden");
            require(!"suspended".equals(round.get("status")), "round_suspended");
            String email = null;
            if (trigger.equals("admin")) {
                require(admin != null, "admin_required");
                List<String> emails=jdbc.query("SELECT email FROM admins WHERE id=:id",params("id",admin),(rs,n)->rs.getString(1));
                require(emails.size()==1,"admin_required"); email=emails.getFirst();
            }
            int number = jdbc.queryForObject("SELECT COALESCE(MAX(attempt_no),0)+1 FROM briefing_attempts WHERE round_id=:id",params("id",rid),Integer.class);
            String id="brfa-"+UUID.randomUUID(), owner=UUID.randomUUID().toString(); Instant lease=now.plusSeconds(leaseSeconds);
            ObjectNode initial=StrictJson.newObject().put("purpose",purpose).put("inputSha256",c.string("inputDigest"));
            if(purpose.equals("outlook"))initial.putObject("outlook").put("requestedAt",now.toString()).put("outcome","pending");
            jdbc.update("""
                INSERT INTO briefing_attempts(id,round_id,attempt_no,request_key,purpose,trigger,admin_id,admin_email_snapshot,
                    owner_token,status,stages,input_artifact_id,started_at,lease_until)
                VALUES(:id,:round,:number,:key,:purpose,:trigger,:admin,:email,:owner,'running',:stages::jsonb,:input,:now,:lease)
                """,params("id",id,"round",rid,"number",number,"key",requestKey,"purpose",purpose,"trigger",trigger,
                    "admin",admin,"email",email,"owner",owner,"stages",json(initial),
                    "input",input,"now",at(now),"lease",at(lease)));
            if (purpose.equals("generation")) jdbc.update("""
                UPDATE briefing_rounds SET status='generating',attempt_no=:number,generation_token=:owner,lease_until=:lease,
                    failure_reason=NULL WHERE id=:id
                """,params("id",rid,"number",number,"owner",owner,"lease",at(lease)));
            return attempt(find(id,false),false);
        });
    }

    private ObjectNode heartbeat(StrictJson.Obj c) {
        c.exactly(Set.of("op","attemptId","ownerToken"));
        return tx.execute(status -> {
            Map<String,Object> a = owned(c); Instant lease=now().plusSeconds(leaseSeconds);
            jdbc.update("UPDATE briefing_attempts SET lease_until=:lease WHERE id=:id",params("lease",at(lease),"id",a.get("id")));
            if ("generation".equals(a.get("purpose"))) jdbc.update("UPDATE briefing_rounds SET lease_until=:lease WHERE id=:id",params("lease",at(lease),"id",a.get("round_id")));
            return StrictJson.newObject().put("leaseUntil",lease.toString());
        });
    }

    private ObjectNode modelStart(StrictJson.Obj c) {
        c.exactly(Set.of("op","attemptId","ownerToken","callId","stage","feature","provider","model","promptVersion","retryUnit","reasoningEffort"));
        String call=identifier(c.string("callId")), stage=identifier(c.string("stage"));
        String feature=choice(c.string("feature"),Set.of("briefing","briefing-outlook"));
        String provider=identifier(c.string("provider")), model=identifier(c.string("model")), prompt=identifier(c.string("promptVersion"));
        String retry=c.stringOrNull("retryUnit"); if(retry!=null) identifier(retry);
        String reasoning=c.stringOrNull("reasoningEffort"); if(reasoning!=null) identifier(reasoning);
        return tx.execute(status -> {
            Map<String,Object> a=owned(c); String id=executionId((String)a.get("id"),call);
            if ("outlook".equals(a.get("purpose"))) require(feature.equals("briefing-outlook"),"wrong_attempt_feature");
            boolean repeated=jdbc.queryForObject("""
                SELECT count(*) FROM briefing_attempts a WHERE round_id=:round AND purpose=:purpose AND attempt_no<:number
                AND EXISTS (SELECT 1 FROM ai_executions e WHERE e.briefing_attempt_id=a.id AND e.execution_mode='live')
                """,
                params("round",a.get("round_id"),"purpose",a.get("purpose"),"number",a.get("attempt_no")),Integer.class)>0;
            String unit = retry!=null ? a.get("id")+":"+retry : repeated ? (String)a.get("id") : null;
            MapSqlParameterSource p=params("id",id,"feature",feature,"attempt",a.get("id"),"job","briefing-direct:"+a.get("id"),
                "call",call,"stage",stage,"number",a.get("attempt_no"),"provider",provider,"model",model,"prompt",prompt,"retry",unit,"reasoning",reasoning);
            int created=jdbc.update("""
                INSERT INTO ai_executions(id,feature,execution_mode,status,briefing_attempt_id,ai_job_id,ai_attempt_id,stage,
                    attempt_no,provider,model,prompt_version,reasoning_effort,started_at,retry_unit_id)
                VALUES(:id,:feature,'live','running',:attempt,:job,:call,:stage,:number,:provider,:model,:prompt,:reasoning,clock_timestamp(),:retry)
                ON CONFLICT(id) DO NOTHING
                """,p);
            Map<String,Object> e=execution(id,false);
            require(e.get("stage").equals(stage) && e.get("feature").equals(feature) && e.get("model").equals(model)
                && e.get("provider").equals(provider) && e.get("prompt_version").equals(prompt)
                && java.util.Objects.equals(reasoning,e.get("reasoning_effort"))
                && java.util.Objects.equals(unit,e.get("retry_unit_id")),"call_identity_conflict");
            stage(a,stage,feature,"running",(String)e.get("ai_job_id"));
            return StrictJson.newObject().put("executionId",id).put("created",created==1).put("status",(String)e.get("status")).put("startedAt",instant(e,"started_at").toString());
        });
    }

    private ObjectNode modelFinish(StrictJson.Obj c) {
        c.exactly(Set.of("op","attemptId","ownerToken","callId","status","transmissionConfirmed","inputTokens",
            "outputTokens","finishedAt","errorCode","responseSha256","estimate","reportedModel"));
        String state=choice(c.string("status"),Set.of("succeeded","failed","cancelled","unknown"));
        String error=c.stringOrNull("errorCode"); if(error!=null) require(error.matches("[a-z_]{1,80}"),"invalid_error_code");
        String response=c.stringOrNull("responseSha256"); if(response!=null) require(StrictJson.SHA256.matcher(response).matches(),"invalid_response_digest");
        String reported=c.stringOrNull("reportedModel"); if(reported!=null) identifier(reported);
        Long in=token(c.raw("inputTokens")), out=token(c.raw("outputTokens"));
        Boolean sent=c.isNull("transmissionConfirmed")?null:c.bool("transmissionConfirmed");
        require(!state.equals("succeeded") || Boolean.TRUE.equals(sent),"success_requires_transmission");
        Instant finished=Instant.parse(c.string("finishedAt"));
        String id=executionId(identifier(c.string("attemptId")),identifier(c.string("callId")));
        // Content-free, strictly projected receipt. No arbitrary message, body, prompt, path or provider error is accepted.
        ObjectNode projected=StrictJson.newObject().put("schemaVersion","briefing-usage-receipt-v1").put("executionId",id)
            .put("status",state).put("finishedAt",finished.toString());
        projected.set("transmissionConfirmed",c.raw("transmissionConfirmed")); projected.set("inputTokens",c.raw("inputTokens"));
        projected.set("outputTokens",c.raw("outputTokens")); projected.set("errorCode",c.raw("errorCode"));
        projected.set("responseSha256",c.raw("responseSha256"));
        projected.set("reportedModel",c.raw("reportedModel"));
        BigDecimal estimate=null; String currency=null; ObjectNode basis=null;
        if(!c.isNull("estimate")) {
            StrictJson.Obj q=c.object("estimate").exactly(Set.of("currency","priceVersion","inputPerMillion","outputPerMillion"));
            currency=q.string("currency");require(currency.matches("[A-Z]{3}"),"invalid_currency");
            identifier(q.string("priceVersion")); BigDecimal ir=decimal(q.raw("inputPerMillion")),or=decimal(q.raw("outputPerMillion"));
            require(in!=null && out!=null && ir!=null && or!=null,"unknown_estimate_usage");
            estimate=ir.multiply(BigDecimal.valueOf(in)).add(or.multiply(BigDecimal.valueOf(out))).divide(BigDecimal.valueOf(1_000_000));
            basis=(ObjectNode)q.node().deepCopy(); projected.set("estimateBasis",basis);
        } else projected.putNull("estimateBasis");
        byte[] raw=StrictJson.write(projected); String hash=ArtifactFileStore.sha256(raw), artifact="brf-usage-"+hash;
        BigDecimal amount=estimate; String money=currency; ObjectNode prices=basis;
        ArtifactFileStore.StoredFile file;
        try(ArtifactFileStore.Session session=files.open()) {file=session.put("briefing_usage",hash+".json",raw);}
        return tx.execute(status -> {
                Map<String,Object> before=find(identifier(c.string("attemptId")),false);
                round((String)before.get("round_id"));
                Map<String,Object> a=find(identifier(c.string("attemptId")),true);
                require(a.get("owner_token").equals(c.string("ownerToken")),"wrong_owner");
                Map<String,Object> e=execution(id,true);
                require(e.get("briefing_attempt_id").equals(a.get("id")) && e.get("execution_mode").equals("live"),"wrong_execution_owner");
                require(!finished.isBefore(instant(e,"started_at").minusSeconds(60)) && !finished.isAfter(now().plusSeconds(60)),"invalid_receipt_time");
                // Cross-host clock skew cannot become a fabricated zero/negative duration. Keep the original in the receipt.
                Instant comparableEnd=finished.isBefore(instant(e,"started_at"))?null:finished;
                if(e.get("receipt_artifact_id")!=null) {
                    require(artifact.equals(e.get("receipt_artifact_id")),"receipt_identity_conflict");
                    return StrictJson.newObject().put("executionId",id).put("reused",true);
                }
                require(Set.of("running","unknown").contains(e.get("status")),"execution_already_finished");
                jdbc.update("""
                    INSERT INTO artifacts(id,kind,storage_uri,sha256,bytes,media_type,created_at)
                    VALUES(:id,'ai_call_receipt',:uri,:sha,:bytes,'application/json',clock_timestamp()) ON CONFLICT(id) DO NOTHING
                    """,params("id",artifact,"uri",file.uri(),"sha",hash,"bytes",file.bytes()));
                jdbc.update("""
                    UPDATE ai_executions SET status=:status,transmission_confirmed=:sent,input_tokens=:input,output_tokens=:output,
                        finished_at=:finished,error_code=:error,error_message=NULL,receipt_artifact_id=:receipt,
                        estimated_cost=:estimate,actual_cost=NULL,currency=:currency,cost_basis=:basis::jsonb,model=COALESCE(:model,model)
                    WHERE id=:id
                    """,params("status",state,"sent",sent,"input",in,"output",out,"finished",at(comparableEnd),"error",error,
                        "receipt",state.equals("unknown")?null:artifact,"estimate",amount,"currency",money,
                        "basis",prices==null?null:json(prices),"model",reported,"id",id));
                if(ACTIVE.contains(a.get("status")) && instant(a,"lease_until").isAfter(now()))
                    stage(a,(String)e.get("stage"),(String)e.get("feature"),state,(String)e.get("ai_job_id"));
                return StrictJson.newObject().put("executionId",id).put("observationArtifactId",artifact).put("reused",false);
            });
    }

    private ObjectNode local(StrictJson.Obj c) {
        c.exactly(Set.of("op","attemptId","ownerToken","eventId","stage","feature","mode"));
        String mode=choice(c.string("mode"),Set.of("replay","save_only")),stage=identifier(c.string("stage"));
        String feature=choice(c.string("feature"),Set.of("briefing","briefing-outlook")),event=identifier(c.string("eventId"));
        return tx.execute(status -> {
            Map<String,Object> a=owned(c); if("outlook".equals(a.get("purpose"))) require(feature.equals("briefing-outlook"),"wrong_attempt_feature");
            String id=executionId((String)a.get("id"),mode+":"+event);
            jdbc.update("""
                INSERT INTO ai_executions(id,feature,execution_mode,status,briefing_attempt_id,stage,attempt_no,
                    started_at,finished_at,transmission_confirmed)
                VALUES(:id,:feature,:mode,'succeeded',:attempt,:stage,:number,clock_timestamp(),clock_timestamp(),false)
                ON CONFLICT(id) DO NOTHING
                """,params("id",id,"feature",feature,"mode",mode,"attempt",a.get("id"),"stage",stage,"number",a.get("attempt_no")));
            Map<String,Object> e=execution(id,false);
            require(mode.equals(e.get("execution_mode")) && stage.equals(e.get("stage")) && feature.equals(e.get("feature")),"local_identity_conflict");
            stage(a,stage,feature,"reused",null); return StrictJson.newObject().put("executionId",id);
        });
    }

    private ObjectNode finish(StrictJson.Obj c) {
        c.exactly(Set.of("op","attemptId","ownerToken","outcome","failureStage","failureReason"));
        String outcome=choice(c.string("outcome"),Set.of("available","withheld","failed","cancelled"));
        String failureStage=c.stringOrNull("failureStage"), reason=c.stringOrNull("failureReason");
        if(failureStage!=null) identifier(failureStage);
        if(reason!=null) require(reason.matches("[a-z_]{1,80}"),"invalid_failure_reason");
        return tx.execute(status -> {
            Map<String,Object> a=owned(c);
            int running=jdbc.queryForObject("SELECT count(*) FROM ai_executions WHERE briefing_attempt_id=:id AND status='running'",params("id",a.get("id")),Integer.class);
            require(running==0,"model_still_running");
            if(outcome.equals("available"))require(jdbc.queryForObject("SELECT count(*) FROM ai_executions WHERE briefing_attempt_id=:id AND status='unknown'",params("id",a.get("id")),Integer.class)==0,"unresolved_model_call");
            outcome(a,outcome,failureStage);
            close(a,Set.of("available","withheld").contains(outcome)?"completed":outcome,reason,
                outcome.equals("available")?"scheduled":"failed",now());
            return StrictJson.newObject().put("attemptId",(String)a.get("id")).put("outcome",outcome);
        });
    }

    /** The existing validated publisher runs inside the same transaction as ownership fencing and terminal recording. */
    public <T> T publish(String attemptId,String ownerToken,Supplier<T> validatedPublisher) {
        return tx.execute(status -> {
            StrictJson.Obj owner=StrictJson.Obj.of(StrictJson.newObject().put("attemptId",attemptId).put("ownerToken",ownerToken));
            Map<String,Object> a=owned(owner);require("generation".equals(a.get("purpose")),"not_publication_owner");
            require(jdbc.queryForObject("SELECT count(*) FROM ai_executions WHERE briefing_attempt_id=:id AND status IN ('running','unknown')",params("id",attemptId),Integer.class)==0,"unresolved_model_call");
            jdbc.queryForObject("SELECT set_config('zoop.briefing.owner_token',:owner,true)",params("owner",ownerToken),String.class);
            T result=validatedPublisher.get();
            require(round((String)a.get("round_id")).get("published_at")!=null,"publication_not_saved");
            outcome(a,"available",null);
            jdbc.update("UPDATE briefing_attempts SET status='completed',finished_at=clock_timestamp() WHERE id=:id",params("id",attemptId));
            return result;
        });
    }

    private Map<String,Object> owned(StrictJson.Obj c) {
        String id=identifier(c.string("attemptId")); Map<String,Object> before=find(id,false);
        round((String)before.get("round_id")); // Every owner mutation locks round first, then attempt.
        Map<String,Object> a=find(id,true);
        require(a.get("owner_token").equals(c.string("ownerToken")) && ACTIVE.contains(a.get("status"))
            && instant(a,"lease_until").isAfter(now()),"stale_attempt_owner");
        return a;
    }
    private void close(Map<String,Object> a,String state,String reason,String roundState,Instant now) {
        jdbc.update("UPDATE briefing_attempts SET status=:state,failure_reason=:reason,finished_at=:now WHERE id=:id",
            params("state",state,"reason",reason,"now",at(now),"id",a.get("id")));
        if("generation".equals(a.get("purpose"))) jdbc.update("""
            UPDATE briefing_rounds SET status=:state,generation_token=NULL,lease_until=NULL,failure_reason=:reason
            WHERE id=:id AND published_at IS NULL
            """,params("state",roundState,"reason",reason,"id",a.get("round_id")));
    }
    private void outcome(Map<String,Object> a,String outcome,String failureStage) {
        ObjectNode stages=(ObjectNode)StrictJson.parseObject(a.get("stages").toString()).node().deepCopy();
        stages.put("outcome",outcome);if(failureStage!=null)stages.put("failureStage",failureStage);
        if(stages.has("outlook"))((ObjectNode)stages.get("outlook")).put("outcome",outcome);
        jdbc.update("UPDATE briefing_attempts SET stages=:stages::jsonb WHERE id=:id",params("stages",json(stages),"id",a.get("id")));
    }
    private void stage(Map<String,Object> a,String stage,String feature,String state,String job) {
        require(stage.matches("[a-z][a-z0-9_]{0,79}") && !Set.of("purpose","inputSha256","outcome","failureStage","outlook").contains(stage),"invalid_stage");
        ObjectNode entry=StrictJson.newObject().put("status",state).put("feature",feature);
        if(job!=null)entry.put("aiJobId",job);
        jdbc.update("UPDATE briefing_attempts SET stages=jsonb_set(stages,ARRAY[:key],:value::jsonb,true) WHERE id=:id",
            params("key",stage,"value",json(entry),"id",a.get("id")));
        if(feature.equals("briefing-outlook"))jdbc.update("""
            UPDATE briefing_attempts SET stages=jsonb_set(stages,'{outlook}',
                COALESCE(stages->'outlook',jsonb_build_object('requestedAt',clock_timestamp(),'outcome','pending')),true) WHERE id=:id
            """,params("id",a.get("id")));
        if(state.equals("running") || state.equals("reused")) {
            String next=stage.endsWith("verification")?"verifying":"running";
            jdbc.update("UPDATE briefing_attempts SET status=:state WHERE id=:id",params("state",next,"id",a.get("id")));
            if("generation".equals(a.get("purpose")))jdbc.update("UPDATE briefing_rounds SET status=:state WHERE id=:id",
                params("state",next.equals("running")?"generating":next,"id",a.get("round_id")));
        }
    }
    private Map<String,Object> round(String id) {return jdbc.queryForMap("SELECT * FROM briefing_rounds WHERE id=:id FOR UPDATE",params("id",id));}
    private Map<String,Object> find(String id,boolean lock) {return jdbc.queryForMap("SELECT * FROM briefing_attempts WHERE id=:id"+(lock?" FOR UPDATE":""),params("id",id));}
    private Map<String,Object> execution(String id,boolean lock) {return jdbc.queryForMap("SELECT * FROM ai_executions WHERE id=:id"+(lock?" FOR UPDATE":""),params("id",id));}
    private Instant now() {return jdbc.queryForObject("SELECT clock_timestamp()",params(),Timestamp.class).toInstant();}
    private static Instant instant(Map<String,Object> row,String name) {return row.get(name)==null?null:((Timestamp)row.get(name)).toInstant();}
    private static Timestamp at(Instant value) {return value==null?null:Timestamp.from(value);}
    private static ObjectNode attempt(Map<String,Object> a,boolean reused) {
        return StrictJson.newObject().put("attemptId",(String)a.get("id")).put("roundId",(String)a.get("round_id"))
            .put("attemptNo",((Number)a.get("attempt_no")).intValue()).put("ownerToken",(String)a.get("owner_token"))
            .put("status",(String)a.get("status")).put("leaseUntil",instant(a,"lease_until").toString()).put("reused",reused);
    }
    private static String executionId(String attempt,String call) {return "aix-brf-"+ArtifactFileStore.sha256((attempt+":"+call).getBytes(StandardCharsets.UTF_8));}
    private static String json(JsonNode value) {return new String(StrictJson.write(value),StandardCharsets.UTF_8);}
    private static Long token(JsonNode value) {
        if(value.isNull())return null;
        require(value.isIntegralNumber()&&value.canConvertToLong()&&value.longValue()>=0,"invalid_token_count"); return value.longValue();
    }
    private static BigDecimal decimal(JsonNode value) {
        if(value.isNull())return null;
        require(value.isNumber(),"invalid_price");BigDecimal number=new BigDecimal(value.toString());
        require(number.signum()>=0 && number.precision()<=24 && Math.abs(number.scale())<=12,"invalid_price");return number;
    }
    private static MapSqlParameterSource params(Object... values) {
        MapSqlParameterSource p=new MapSqlParameterSource();for(int i=0;i<values.length;i+=2)p.addValue((String)values[i],values[i+1]);return p;
    }
    private static String identifier(String value) {require(value!=null&&value.matches("[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}"),"invalid_identifier");return value;}
    private static String choice(String value,Set<String> choices) {require(choices.contains(value),"invalid_choice");return value;}
    private static void require(boolean condition,String code) {if(!condition)throw new Rejected(code);}
    public static final class Rejected extends RuntimeException {
        public Rejected(String code) {super(code,null,false,false);}
    }
}
