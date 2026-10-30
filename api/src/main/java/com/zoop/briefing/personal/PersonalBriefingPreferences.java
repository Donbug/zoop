package com.zoop.briefing.personal;

import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.briefing.storage.BriefingRoundRepository;
import com.zoop.common.exception.*;
import com.zoop.common.json.StrictJson;
import java.sql.Timestamp;
import java.time.*;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

/** D-BRF-01/02: settings are prospective; each published personal delivery has one frozen basis. */
@Service
public class PersonalBriefingPreferences {
    public record Save(ExplicitBriefingService.Choice choice,String expectedRevision) {}
    private final JdbcTemplate jdbc; private final Clock clock; private final boolean demoEnabled;
    private final ExplicitBriefingService selections; private final SelectedGenerationService generation;
    private final BriefingRoundRepository rounds; private final PersonalCandidateAccess access;
    private final com.zoop.graph.read.PersonalCompanies personal;
    private final JsonMapper json=JsonMapper.builder().build();
    public PersonalBriefingPreferences(JdbcTemplate jdbc,Clock clock,ExplicitBriefingService selections,
        SelectedGenerationService generation,BriefingRoundRepository rounds,PersonalCandidateAccess access,com.zoop.graph.read.PersonalCompanies personal,
        @Value("${zoop.briefing.personal-demo-enabled:false}")boolean demoEnabled){
        this.jdbc=jdbc;this.clock=clock;this.selections=selections;this.generation=generation;this.rounds=rounds;this.access=access;this.demoEnabled=demoEnabled;this.personal=personal;
    }
    static void member(MemberPrincipal p){if(p==null)throw new CustomException(ErrorCode.AUTH_REQUIRED);}
    public static Instant nextSlot(Instant now){
        var local=now.atZone(ZoneId.of("Asia/Seoul"));
        for(var time:List.of(LocalTime.of(9,20),LocalTime.of(17,30))){var slot=local.toLocalDate().atTime(time).atZone(local.getZone()).toInstant();if(slot.isAfter(now))return slot;}
        return local.toLocalDate().plusDays(1).atTime(9,20).atZone(local.getZone()).toInstant();
    }
    private Optional<ObjectNode> preference(String member,String where,Object...extra){
        var args=new ArrayList<Object>();args.add(member);args.addAll(Arrays.asList(extra));
        return jdbc.query("SELECT id,revision,choice,created_at,effective_from FROM briefing_personal_preferences WHERE member_id=? "+where+" ORDER BY revision DESC LIMIT 1",(r,i)->{
            var o=json.createObjectNode().put("revisionId",r.getString(1)).put("revision",r.getInt(2));o.set("choice",StrictJson.parseObject(r.getString(3)).node());
            o.put("savedAt",r.getTimestamp(4).toInstant().toString()).put("effectiveFrom",r.getTimestamp(5).toInstant().toString());return o;},args.toArray()).stream().findFirst();
    }
    public ObjectNode settings(MemberPrincipal p){
        member(p);var o=json.createObjectNode().put("demoEnabled",demoEnabled).put("timezone","Asia/Seoul").put("nextScheduledAt",nextSlot(clock.instant()).toString());
        o.putArray("schedule").add("09:20").add("17:30");o.set("preference",preference(p.memberId(),"").<JsonNode>map(x->x).orElse(json.nullNode()));return o;
    }
    public boolean hasCurrentCompanies(MemberPrincipal p){
        member(p);var ids=personal.of(p);return !ids.holdings().isEmpty()||!ids.watchlist().isEmpty();
    }
    @Transactional(timeout=10)
    public void captureEligibility(MemberPrincipal member,Instant slot){
        member(member);var now=clock.instant();
        if(now.isBefore(slot)||!now.isBefore(slot.plusSeconds(120)))throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        if(!jdbc.query("SELECT 1 FROM briefing_personal_slot_eligibility WHERE member_id=? AND scheduled_at=?",(r,i)->r.getInt(1),member.memberId(),Timestamp.from(slot)).isEmpty())return;
        jdbc.update("INSERT INTO briefing_personal_slot_eligibility(member_id,scheduled_at,observed_at,has_companies) VALUES (?,?,?,?) ON CONFLICT DO NOTHING",member.memberId(),Timestamp.from(slot),Timestamp.from(now),hasCurrentCompanies(member));
    }
    @Transactional(timeout=10)
    public ObjectNode initialize(MemberPrincipal p){
        member(p);lock(p.memberId());
        if(preference(p.memberId(),"").isPresent())return settings(p).put("initializationStatus","existing");
        var source=personal.of(p);
        var ids=java.util.stream.Stream.concat(source.holdings().stream(),source.watchlist().stream()).distinct().sorted().toList();
        if(ids.isEmpty())return settings(p).put("initializationStatus","no_companies");
        return save(p,new Save(new ExplicitBriefingService.Choice(ids,3,0,3),null)).put("initializationStatus","initialized");
    }
    @Transactional(timeout=10)
    public ObjectNode save(MemberPrincipal p,Save request){
        member(p);if(request==null)throw new CustomException(ErrorCode.INVALID_REQUEST);if(request.choice()==null)throw new CustomException(ErrorCode.INVALID_REQUEST);
        var fixed=new ExplicitBriefingService.Choice(request.choice().companyIds(),3,0,3);
        var ids=ExplicitBriefingService.validate(fixed);
        var known=new HashSet<>(jdbc.query("SELECT id FROM companies",(r,i)->r.getString(1)));if(!known.containsAll(ids))throw new CustomException(ErrorCode.INVALID_REQUEST);
        lock(p.memberId());var latest=preference(p.memberId(),"");
        if(!Objects.equals(latest.map(x->x.path("revisionId").asString()).orElse(null),request.expectedRevision()))throw new CustomException(ErrorCode.REVISION_CONFLICT);
        var normalized=new ExplicitBriefingService.Choice(List.copyOf(ids),3,0,3);
        if(latest.isPresent()&&latest.get().path("choice").equals(json.valueToTree(normalized)))return settings(p);
        var now=clock.instant();jdbc.update("INSERT INTO briefing_personal_preferences(id,member_id,revision,choice,created_at,effective_from) VALUES (?,?,?,?::jsonb,?,?)",
            "pref-"+UUID.randomUUID(),p.memberId(),latest.map(x->x.path("revision").asInt()+1).orElse(1),json.valueToTree(normalized).toString(),Timestamp.from(now),Timestamp.from(nextSlot(now)));
        return settings(p);
    }
    private void lock(String key){jdbc.query("SELECT pg_advisory_xact_lock(hashtext(?))",r->{},"personal-briefing:"+key);}
    @Transactional(timeout=10)
    public ObjectNode prepare(String roundId,MemberPrincipal p,boolean demo,String expectedRevision,String requestId){
        member(p);if(demo&&!demoEnabled)throw new CustomException(ErrorCode.ACCESS_DENIED);
        var round=rounds.findById(roundId).orElseThrow(()->new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
        if(!"published".equals(round.status()) || round.scheduledAt().isAfter(clock.instant()) || (!demo && !List.of(LocalTime.of(9,20),LocalTime.of(17,30)).contains(round.scheduledAt().atZone(ZoneId.of("Asia/Seoul")).toLocalTime())))throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        if(!demo){
            var eligible=jdbc.query("SELECT has_companies FROM briefing_personal_slot_eligibility WHERE member_id=? AND scheduled_at=?",(r,i)->r.getBoolean(1),p.memberId(),Timestamp.from(round.scheduledAt()));
            if(eligible.isEmpty()||!eligible.getFirst())return json.createObjectNode().put("status",eligible.isEmpty()?"not_scheduled":"no_companies").put("roundId",roundId);
        }
        lock(p.memberId()+":"+roundId);
        var pref=preference(p.memberId(),demo?"":"AND effective_from<=? AND created_at<?",demo?new Object[]{}:new Object[]{Timestamp.from(round.scheduledAt()),Timestamp.from(round.scheduledAt())}).orElseThrow(()->new CustomException(ErrorCode.SOURCE_UNAVAILABLE));
        if(demo&&!pref.path("revisionId").asString().equals(expectedRevision))throw new CustomException(ErrorCode.REVISION_CONFLICT);
        var existing=delivery(p.memberId(),roundId,demo,pref.path("revisionId").asString());if(existing.isPresent())return response(existing.get(),requestId);
        var choice=json.treeToValue(pref.path("choice"),ExplicitBriefingService.Choice.class);var selection=selections.select(roundId,p,choice,requestId);
        String job=null;var result=selection.path("pendingAnalysisCount").asInt()==0?selection:null;
        if(result==null){var g=generation.create(roundId,p,new SelectedGenerationService.Request(choice,selection.path("selectionVersion").asString()),requestId);job=g.path("id").asString();}
        String id="delivery-"+UUID.randomUUID();
        jdbc.update("""
          INSERT INTO briefing_personal_deliveries(id,member_id,round_id,preference_id,mode,scheduled_at,selection_snapshot,selection_sha256,result_snapshot,result_sha256,job_id,status,finished_at)
          VALUES (?,?,?,?,?,?,?::jsonb,encode(sha256(convert_to((?::jsonb)::text,'UTF8')),'hex'),?::jsonb,
          CASE WHEN ?::jsonb IS NULL THEN NULL ELSE encode(sha256(convert_to((?::jsonb)::text,'UTF8')),'hex') END,?,?,CASE WHEN ?::jsonb IS NULL THEN NULL ELSE now() END)
          """,id,p.memberId(),roundId,pref.path("revisionId").asString(),demo?"demo":"scheduled",Timestamp.from(round.scheduledAt()),selection.toString(),selection.toString(),result==null?null:result.toString(),result==null?null:result.toString(),result==null?null:result.toString(),job,result==null?"generating":"ready",result==null?null:result.toString());
        return response(delivery(p.memberId(),roundId,demo,pref.path("revisionId").asString()).orElseThrow(),requestId);
    }
    private Optional<ObjectNode> delivery(String member,String round,boolean demo,String pref){
        String clause=demo&&pref!=null?" AND preference_id=?":"";var args=new ArrayList<Object>(List.of(member,round,demo?"demo":"scheduled"));if(demo&&pref!=null)args.add(pref);
        return jdbc.query("""
          SELECT id,member_id,round_id,preference_id,mode,scheduled_at,selection_snapshot,result_snapshot,status,job_id,finished_at
          FROM briefing_personal_deliveries WHERE member_id=? AND round_id=? AND mode=?
          AND selection_sha256=encode(sha256(convert_to(selection_snapshot::text,'UTF8')),'hex')
          AND (result_snapshot IS NULL OR result_sha256=encode(sha256(convert_to(result_snapshot::text,'UTF8')),'hex'))
          """+clause+" ORDER BY created_at DESC,id COLLATE \"C\" LIMIT 1",(r,i)->{
            var o=json.createObjectNode().put("id",r.getString(1)).put("memberId",r.getString(2)).put("roundId",r.getString(3)).put("preferenceRevision",r.getString(4)).put("mode",r.getString(5)).put("scheduledAt",r.getTimestamp(6).toInstant().toString()).put("status",r.getString(9)).put("jobId",r.getString(10));
            o.set("selection",StrictJson.parseObject(r.getString(r.getString(8)==null?7:8)).node());return o;},args.toArray()).stream().findFirst();
    }
    public ObjectNode get(String round,MemberPrincipal p,boolean demo,String requestId){
        member(p);if(demo&&!demoEnabled)throw new CustomException(ErrorCode.ACCESS_DENIED);
        return delivery(p.memberId(),round,demo,null).map(x->response(x,requestId)).orElseGet(()->json.createObjectNode().put("status","not_published").put("roundId",round));
    }
    private ObjectNode response(ObjectNode row,String requestId){
        String roundId=row.path("roundId").asString();var r=rounds.findById(roundId).orElseThrow(()->new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
        if(!"published".equals(r.status())||rounds.changes(roundId).stream().anyMatch(c->"correction".equals(c.kind())))throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        var selection=row.path("selection");var pools=jdbc.query("SELECT snapshot FROM briefing_personal_pools WHERE round_id=? AND input_sha256=? AND snapshot_sha256=encode(sha256(convert_to(snapshot::text,'UTF8')),'hex')",(rs,i)->StrictJson.parseObject(rs.getString(1)).node(),roundId,selection.path("poolVersion").asString());
        if(pools.size()!=1)throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        PersonalBriefingService.validatePool(pools.getFirst(),r);
        for(var item:selection.path("presentation").path("items")){
            var c=pools.getFirst().path("candidates").valueStream().filter(x->x.path("issueId").equals(item.path("eventId"))).findFirst().orElseThrow(()->new CustomException(ErrorCode.SOURCE_UNAVAILABLE));
            if(!access.readable(c,requestId))throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
        for(var tracked:selection.path("tracking")){
            String prior=tracked.path("previousRoundId").asString();var pr=rounds.findById(prior).orElseThrow(()->new CustomException(ErrorCode.SOURCE_UNAVAILABLE));
            if(!"published".equals(pr.status())||rounds.changes(prior).stream().anyMatch(c->"correction".equals(c.kind())))throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
            var basis=jdbc.query("SELECT snapshot FROM briefing_personal_pools WHERE round_id=? AND input_sha256=? AND snapshot_sha256=encode(sha256(convert_to(snapshot::text,'UTF8')),'hex')",(rs,i)->StrictJson.parseObject(rs.getString(1)).node(),prior,tracked.path("poolVersion").asString());
            if(basis.size()!=1)throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);PersonalBriefingService.validatePool(basis.getFirst(),pr);
            var candidate=basis.getFirst().path("candidates").valueStream().filter(x->x.path("issueId").equals(tracked.path("issueId"))).findFirst().orElseThrow(()->new CustomException(ErrorCode.SOURCE_UNAVAILABLE));
            if(!access.readable(candidate,requestId))throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
        row.remove(List.of("memberId","jobId"));return row;
    }
    @Transactional(timeout=10)
    public void complete(String id){
        var rows=jdbc.query("SELECT member_id,round_id,job_id,selection_snapshot FROM briefing_personal_deliveries WHERE id=? AND result_snapshot IS NULL FOR UPDATE",(r,i)->List.of(r.getString(1),r.getString(2),r.getString(3),r.getString(4)),id);
        if(rows.isEmpty())return;var row=rows.getFirst();var old=StrictJson.parseObject(row.get(3)).node();
        var job=generation.get(row.get(1),row.get(2),new MemberPrincipal(row.getFirst(),"scheduled"),"personal-delivery");
        String status=job.path("status").asString();if(List.of("queued","running").contains(status))return;
        var selected=job.path("selection");if(!selected.isObject()||!selected.path("selectionVersion").equals(old.path("selectionVersion"))){jdbc.update("UPDATE briefing_personal_deliveries SET status='failed' WHERE id=? AND result_snapshot IS NULL",id);return;}
        String finalStatus=List.of("ready","partial","withheld").contains(status)?status:"failed";
        jdbc.update("UPDATE briefing_personal_deliveries SET result_snapshot=?::jsonb,result_sha256=encode(sha256(convert_to((?::jsonb)::text,'UTF8')),'hex'),status=?,finished_at=now() WHERE id=? AND result_snapshot IS NULL",selected.toString(),selected.toString(),finalStatus,id);
    }
}
