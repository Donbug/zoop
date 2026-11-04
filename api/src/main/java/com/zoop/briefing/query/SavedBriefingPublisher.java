package com.zoop.briefing.query;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.briefing.personal.PersonalBriefingPreferences;
import com.zoop.briefing.personal.PersonalCandidateAccess;
import com.zoop.briefing.storage.BriefingRoundRepository;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.document.evidence.config.DocumentReadProperties;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

/** Explicit operator publication of staged, frozen results. No model/selection/scheduler is called. */
@Service
public class SavedBriefingPublisher {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final BriefingRoundRepository rounds;
    private final DocumentBriefingContentAccess access;
    private final PersonalCandidateAccess candidates;
    private final PersonalBriefingPreferences personal;
    private final DocumentReadProperties properties;
    private final Clock clock;

    public SavedBriefingPublisher(JdbcTemplate jdbc, PlatformTransactionManager manager, BriefingRoundRepository rounds,
            DocumentBriefingContentAccess access, PersonalCandidateAccess candidates, PersonalBriefingPreferences personal,
            DocumentReadProperties properties, Clock clock) {
        this.jdbc=jdbc;this.rounds=rounds;this.access=access;this.candidates=candidates;this.personal=personal;
        this.properties=properties;this.clock=clock;this.tx=new TransactionTemplate(manager);
        tx.setIsolationLevel(TransactionDefinition.ISOLATION_SERIALIZABLE);tx.setTimeout(60);
    }

    public ObjectNode publish(JsonNode manifest, String manifestSha, Map<String,List<JsonNode>> tables) {
        var finalization=StrictJson.Obj.of(manifest).object("finalization");
        require("briefing-finalization-v1".equals(finalization.string("schemaVersion")),"finalization_required");
        String member=finalization.string("memberId"), request=finalization.string("requestSha256");
        require(StrictJson.SHA256.matcher(request).matches()&&StrictJson.SHA256.matcher(manifestSha).matches(),"invalid_digest");
        Instant imported=Instant.parse(finalization.string("importedAt"));require(!imported.isAfter(clock.instant()),"future_import");
        return tx.execute(status -> {
            jdbc.query("SELECT pg_advisory_xact_lock(hashtext(?))",rs->{},"saved-briefing:"+request);
            require(Integer.valueOf(1).equals(jdbc.queryForObject("SELECT count(*) FROM members WHERE id=? AND status='active' AND created_at<=?",Integer.class,member,Timestamp.from(imported))),"member_unavailable_or_import_backdated");
            var prior=jdbc.queryForList("SELECT manifest_sha256,member_id FROM briefing_result_imports WHERE request_sha256=?",request);
            boolean repeated=!prior.isEmpty();
            if(repeated)require(prior.size()==1&&manifestSha.equals(prior.getFirst().get("manifest_sha256"))&&member.equals(prior.getFirst().get("member_id")),"request_identity_conflict");
            currentGrantFile(finalization.string("grantsSha256"));
            artifactsAndQuotes(tables);
            var sourceRounds=tables.get("briefing_rounds");
            require(!sourceRounds.isEmpty()&&sourceRounds.size()<=100,"invalid_round_count");
            require(finalization.objects("rounds").size()==sourceRounds.size(),"graph_scope_changed");
            Set<String> seen=new HashSet<>();
            // Lock/check the complete batch before changing any availability or publication state.
            for(var source:sourceRounds) {
                String id=text(source,"id");require(seen.add(id),"duplicate_round");
                var locked=jdbc.queryForList("SELECT status,published_at FROM briefing_rounds WHERE id=? FOR UPDATE",id);
                require(locked.size()==1,"staged_round_missing");
                require(repeated?"published".equals(locked.getFirst().get("status"))&&locked.getFirst().get("published_at")!=null:
                        "scheduled".equals(locked.getFirst().get("status"))&&locked.getFirst().get("published_at")==null,"round_already_used");
                require(Integer.valueOf(1).equals(jdbc.queryForObject("""
                    SELECT count(*) FROM briefing_rounds WHERE id=? AND published_payload=?::jsonb AND public_snapshot=?::jsonb
                    AND comparison_snapshot IS NOT DISTINCT FROM ?::jsonb
                    AND payload_sha256=encode(sha256(convert_to(published_payload::text,'UTF8')),'hex')
                    """,Integer.class,id,source.path("published_payload").toString(),source.path("public_snapshot").toString(),
                        source.path("comparison_snapshot").isNull()?null:source.path("comparison_snapshot").toString())),"staged_round_changed");
                var g=finalization.objects("rounds").stream().filter(x->id.equals(x.string("roundId"))).toList();
                require(g.size()==1,"graph_binding_missing");String graph=g.getFirst().string("graphVersion");
                require(graph.matches("gv-[0-9a-f]{64}"),"registered_graph_required");
                require(Integer.valueOf(1).equals(jdbc.queryForObject("""
                    SELECT count(*) FROM graph_versions v JOIN artifacts a ON a.id=v.snapshot_artifact_id
                    WHERE v.id=? AND v.kind='snapshot' AND a.sha256=?
                    """,Integer.class,graph,g.getFirst().string("snapshotSha256"))),"registered_graph_changed");
                require(graph.equals(source.path("graph_version_id").asString()),"graph_binding_changed");
            }
            for(var source:tables.get("articles")) {
                var stored=jdbc.queryForList("SELECT provider,current_version,access_status FROM articles WHERE id=? FOR UPDATE",text(source,"id"));
                require(stored.size()==1&&text(source,"provider").equals(stored.getFirst().get("provider"))
                        &&java.util.Objects.equals(source.path("current_version").isNull()?null:text(source,"current_version"),stored.getFirst().get("current_version"))
                        &&Set.of("private","available").contains(stored.getFirst().get("access_status")),"source_visibility_or_identity_changed");
                if(!repeated)jdbc.update("UPDATE articles SET access_status='available' WHERE id=? AND access_status='private'",text(source,"id"));
            }
            Instant published=clock.instant();
            for(var source:sourceRounds) {
                String id=text(source,"id");
                if(!repeated)require(jdbc.update("UPDATE briefing_rounds SET status='published',published_at=? WHERE id=? AND status='scheduled' AND published_at IS NULL",Timestamp.from(published),id)==1,"publication_race");
            }
            for(var source:sourceRounds) {
                var round=rounds.findById(text(source,"id")).orElseThrow(()->new IllegalArgumentException("round_missing"));
                require(!round.scheduledAt().isAfter(published),"future_round");
                BriefingSnapshotValidator.validate(round);
                require(access.mayRead(round,"saved-result-publication"),"current_round_authority_denied");
                var pool=tables.get("briefing_personal_pools").stream().filter(p->round.id().equals(p.path("round_id").asString())).toList();
                require(pool.size()==1,"personal_pool_missing");
                require(Integer.valueOf(1).equals(jdbc.queryForObject("""
                    SELECT count(*) FROM briefing_personal_pools WHERE round_id=? AND input_sha256=? AND snapshot=?::jsonb
                    AND snapshot_sha256=encode(sha256(convert_to(snapshot::text,'UTF8')),'hex')
                    """,Integer.class,round.id(),text(pool.getFirst(),"input_sha256"),pool.getFirst().path("snapshot").toString())),"pool_changed");
                for(var candidate:pool.getFirst().path("snapshot").path("candidates"))
                    require(candidates.readableForRound(candidate,round,"saved-result-publication"),"current_candidate_authority_denied");
            }
            int revision=finalization.count("preferenceRevision");
            String pref="prep-pref-"+Canonical.sha256(manifest.path("memberBindingRef").asString()+"\n"+member+"\ndemo\n"+revision).substring(0,24);
            require(tables.get("briefing_personal_preferences").size()==1,"one_demo_preference_required");
            require(Integer.valueOf(1).equals(jdbc.queryForObject("SELECT count(*) FROM briefing_personal_preferences WHERE id=? AND member_id=? AND scope='demo' AND revision=? AND created_at=? AND choice=?::jsonb",Integer.class,pref,member,revision,Timestamp.from(imported),tables.get("briefing_personal_preferences").getFirst().path("choice").toString())),"demo_preference_unbound");
            require(tables.get("briefing_personal_deliveries").size()==seen.size(),"personal_round_count");
            Set<String> delivered=new HashSet<>();
            for(var source:tables.get("briefing_personal_deliveries")) {
                String id="prep-delivery-"+Canonical.sha256(text(source,"id")+"\n"+pref).substring(0,24),rid=text(source,"round_id");
                require(seen.contains(rid)&&delivered.add(rid),"foreign_or_duplicate_delivery_round");
                require(Integer.valueOf(1).equals(jdbc.queryForObject("""
                    SELECT count(*) FROM briefing_personal_deliveries WHERE id=? AND member_id=? AND round_id=? AND preference_id=?
                    AND mode='demo' AND status='ready' AND job_id IS NULL AND selection_snapshot=?::jsonb AND result_snapshot=?::jsonb
                    AND selection_sha256=encode(sha256(convert_to(selection_snapshot::text,'UTF8')),'hex')
                    AND result_sha256=encode(sha256(convert_to(result_snapshot::text,'UTF8')),'hex')
                    """,Integer.class,id,member,rid,pref,source.path("selection_snapshot").toString(),source.path("result_snapshot").toString())),"delivery_changed");
                var restored=personal.get(rid,new MemberPrincipal(member,"saved-import"),true,"saved-result-publication");
                require("ready".equals(restored.path("status").asString())&&id.equals(restored.path("id").asString()),"personal_read_denied");
            }
            currentGrantFile(finalization.string("grantsSha256"));
            var ids=StrictJson.newObject().putArray("ids");seen.stream().sorted().forEach(ids::add);
            if(!repeated)jdbc.update("INSERT INTO briefing_result_imports(request_sha256,manifest_sha256,member_id,round_ids) VALUES(?,?,?,?::jsonb)",request,manifestSha,member,ids.toString());
            return StrictJson.newObject().put("publishedRounds",seen.size()).put("demoDeliveries",seen.size()).put("reused",repeated).put("newAiCalls",0);
        });
    }

    private void artifactsAndQuotes(Map<String,List<JsonNode>> tables) {
        require(properties.artifactRootPath()!=null,"artifact_root_required");
        var files=ArtifactFileStore.at(properties.artifactRootPath());
        Map<String,String> texts=new java.util.HashMap<>();
        for(var source:tables.get("artifacts")) {
            var row=jdbc.queryForMap("SELECT kind,storage_uri,sha256,bytes FROM artifacts WHERE id=?",text(source,"id"));
            require(text(source,"kind").equals(row.get("kind"))&&text(source,"sha256").equals(row.get("sha256"))
                    &&source.path("bytes").asLong()==((Number)row.get("bytes")).longValue(),"artifact_changed");
            byte[] raw=files.readVerified(row.get("storage_uri").toString(),row.get("sha256").toString(),((Number)row.get("bytes")).longValue());
            if("extracted_text".equals(row.get("kind")))texts.put(text(source,"id"),new String(raw,StandardCharsets.UTF_8));
        }
        for(var e:tables.get("evidence")) {
            String body=texts.get(text(e,"text_artifact_id"));require(body!=null,"quote_body_missing");
            int start=e.path("start_offset").asInt(),end=e.path("end_offset").asInt();
            require("unicode_code_point".equals(text(e,"offset_unit"))&&start>=0&&end>start&&end<=body.codePointCount(0,body.length()),"quote_range_invalid");
            require(text(e,"quote").equals(body.substring(body.offsetByCodePoints(0,start),body.offsetByCodePoints(0,end))),"quote_not_exact");
            require(Integer.valueOf(1).equals(jdbc.queryForObject("""
                SELECT count(*) FROM evidence e JOIN article_versions v ON v.article_id=e.article_id AND v.version=e.article_version
                WHERE e.id=? AND e.article_id=? AND e.article_version=? AND e.text_artifact_id=? AND e.quote=?
                AND e.start_offset=? AND e.end_offset=? AND e.quote_verified IS TRUE AND e.verification_artifact_id=?
                AND e.text_artifact_id=v.text_artifact_id
                """,Integer.class,text(e,"id"),text(e,"article_id"),text(e,"article_version"),text(e,"text_artifact_id"),text(e,"quote"),start,end,text(e,"verification_artifact_id"))),"evidence_changed");
        }
    }
    private void currentGrantFile(String expected) {
        try{require(properties.grantsPath()!=null&&expected.equals(Canonical.sha256(Files.readAllBytes(properties.grantsPath()))),"current_grants_changed");}
        catch(java.io.IOException error){throw new IllegalArgumentException("current_grants_unavailable");}
    }
    private static String text(JsonNode value,String field){return StrictJson.Obj.of(value).string(field);}
    private static void require(boolean ok,String code){if(!ok)throw new IllegalArgumentException(code);}
}
