package com.zoop.briefing.server;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.briefing.query.*;
import com.zoop.briefing.replay.BriefingReplayReadPolicy;
import com.zoop.briefing.storage.BriefingRound;
import com.zoop.briefing.usage.BriefingUsageLedger;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.document.analysis.GrantRegistry;
import com.zoop.document.analysis.repository.JdbcDocumentAnalysisRepository;
import com.zoop.document.evidence.config.DocumentReadProperties;
import com.zoop.document.evidence.service.DocumentReadSources;
import com.zoop.document.repository.JdbcDocumentRegistryRepository;
import com.zoop.graph.importer.JdbcGraphHandoffRepository;
import com.zoop.graph.publication.*;
import com.zoop.graph.read.*;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import java.nio.file.*;
import java.sql.Timestamp;
import java.time.*;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.datasource.*;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.*;

/** Operator-only producer boundary. No Spring application, schema migration, catalog writer or graph activation. */
public final class BriefingServerCommand {
    private final JdbcTemplate jdbc;
    private final NamedParameterJdbcTemplate named;
    private final DriverManagerDataSource source;
    private final Path work, artifacts, grantsPath,scopePath;
    private final ArtifactFileStore files;
    private final GraphPublicationReader reader;
    private final GraphPublicationAuthority authority;
    private final DocumentBriefingContentAccess readAccess;

    public BriefingServerCommand(Map<String,String> env) {
        source = new DriverManagerDataSource(required(env,"DB_URL"),required(env,"DB_USERNAME"),required(env,"DB_PASSWORD"));
        jdbc = new JdbcTemplate(source); named = new NamedParameterJdbcTemplate(source);
        work = Path.of(required(env,"BRIEFING_SERVER_WORK_ROOT")).toAbsolutePath().normalize();
        artifacts = Path.of(required(env,"BRIEFING_USAGE_ARTIFACT_ROOT")).toAbsolutePath().normalize();
        scopePath=Path.of(required(env,"BRIEFING_SERVER_SOURCE_SCOPE"));
        grantsPath = Path.of(required(env,"ZOOP_DOCUMENT_READ_GRANTS")); files = ArtifactFileStore.at(artifacts);
        var registry = new JdbcDocumentRegistryRepository(named);
        reader = new GraphPublicationReader(new JdbcGraphHandoffRepository(named,new JdbcDocumentAnalysisRepository(named)),registry,files,new JdbcGraphPublicationRepository(named));
        authority = new GraphPublicationAuthority(registry,new DocumentReadSources(Path.of(required(env,"ZOOP_DOCUMENT_READ_INGESTION_SOURCES"))),new JdbcDisclosureExclusionReader(named),Clock.systemUTC());
        var properties = new DocumentReadProperties(grantsPath.toString(),required(env,"ZOOP_DOCUMENT_READ_INGESTION_SOURCES"),artifacts.toString());
        readAccess = new DocumentBriefingContentAccess(jdbc,properties,Clock.systemUTC(),BriefingReplayReadPolicy.disabled(),
            new BriefingGraphContentAuthority(new com.zoop.graph.version.JdbcGraphVersionRepository(named,Clock.systemUTC()),reader,authority));
    }

    public static void main(String[] args) throws Exception {
        try {
            if(args.length!=2 || !Set.of("prepare","check","publish").contains(args[0])) throw new IllegalArgumentException("operation");
            var command = new BriefingServerCommand(System.getenv());
            Path path = Path.of(args[1]).toAbsolutePath().normalize();
            if(!path.startsWith(command.work) || !path.toRealPath().startsWith(command.work.toRealPath()) || Files.isSymbolicLink(path) || Files.size(path)>4*1024*1024) throw new IllegalArgumentException("private_request");
            var request = StrictJson.parseObject(Files.readAllBytes(path));
            ObjectNode result = switch(args[0]) {
                case "prepare" -> command.prepare(request);
                case "check" -> { command.check(request.object("prepared")); yield StrictJson.newObject().put("status","current"); }
                case "publish" -> command.publish(request);
                default -> throw new IllegalArgumentException();
            };
            System.out.println("BRIEFING_SERVER_RESULT="+new String(StrictJson.write(result),java.nio.charset.StandardCharsets.UTF_8));
        } catch(Exception failure) {
            System.err.println("BRIEFING_SERVER_FAILED="+failure.getClass().getSimpleName()); System.exit(1);
        }
    }

    public ObjectNode prepare(StrictJson.Obj request) {
        var round=request.object("round"); String id=round.string("id");
        Instant cutoff=Instant.parse(round.string("windowTo")), from=Instant.parse(round.string("windowFrom"));
        if(cutoff.isAfter(Instant.now()) || !cutoff.equals(Instant.parse(round.string("scheduledAt"))) || !from.isBefore(cutoff)) reject();
        var graphRows=jdbc.queryForList("SELECT id,kind,published_at,review_revision,rule_revision FROM graph_versions WHERE active");
        if(graphRows.size()!=1 || !"snapshot".equals(graphRows.getFirst().get("kind"))) throw new IllegalStateException("published_graph_required");
        String version=graphRows.getFirst().get("id").toString();
        if(graphRows.getFirst().get("published_at")==null)throw new IllegalStateException("published_graph_clock_required");
        Instant graphPublished=((Timestamp)graphRows.getFirst().get("published_at")).toInstant();
        if(graphPublished.isAfter(cutoff)) throw new IllegalStateException("graph_after_cutoff");
        var publication=reader.read(version); var excluded=authority.current(publication,"briefing-server");
        var visible=GraphSnapshotFilter.apply(publication.snapshot(),null,excluded);
        byte[] grantBytes=readGrants();var grantRoot=StrictJson.parseObject(grantBytes); var current=GrantRegistry.parse(grantBytes);
        var result=StrictJson.newObject(); result.set("round",round.node().deepCopy()); result.put("graphVersion",version);
        result.put("graphSnapshotSha256",publication.snapshotArtifact().sha256());
        result.put("reviewRevision",((Number)graphRows.getFirst().get("review_revision")).longValue());
        Object ruleRevision=graphRows.getFirst().get("rule_revision");result.put("ruleRevision",ruleRevision==null?0:((Number)ruleRevision).longValue());
        result.put("exclusionRevision",excluded.revision());
        result.put("preparedAt",Instant.now().toString()); result.put("model","gpt-6-luna");
        result.put("schemaVersion","briefing-server-input-v1");
        var candidates=result.putArray("candidates"); var bindings=result.putArray("sourceBindings");
        Set<String> bound=new HashSet<>(); int outside=0, denied=0;
        for(var issue:visible.issues()) {
            var sources=StrictJson.newObject(); var links=StrictJson.newArray(); Set<String> evidenceIds=new LinkedHashSet<>();
            for(var e:visible.evidence()) {
                if(!issue.evidenceIds().contains(e.evidenceId())) continue;
                var article=visible.articles().stream().filter(a -> a.articleId().equals(e.articleId()) && a.version().equals(e.articleVersion())).findFirst().orElseThrow();
                var rows=jdbc.queryForList("SELECT a.provider,a.kind,v.title,v.publisher,v.published_at,t.storage_uri,t.sha256,t.bytes FROM articles a JOIN article_versions v ON v.article_id=a.id JOIN artifacts t ON t.id=v.text_artifact_id WHERE a.id=? AND v.version=? AND a.access_status='available'",e.articleId(),e.articleVersion());
                if(rows.size()!=1) reject(); var row=rows.getFirst(); var grant=findGrant(grantRoot,current,row.get("provider").toString());
                if(grant==null || !inScope(row.get("provider").toString(),e.articleId(),e.articleVersion(),row.get("sha256").toString())) {denied++;continue;}
                if(row.get("published_at")==null) {outside++;continue;}
                Instant at=((Timestamp)row.get("published_at")).toInstant(); if(!at.isAfter(from)||at.isAfter(cutoff)) {outside++;continue;}
                String docKey=e.articleId()+"\n"+e.articleVersion();
                if(bound.add(docKey)) bindings.addObject().put("documentId",e.articleId()).put("documentVersion",e.articleVersion()).put("grantId",grant.string("grantId"))
                    .put("grantRevision",grant.string("revision")).putArray("recipients").add("openai");
                byte[] body=files.readVerified(row.get("storage_uri").toString(),row.get("sha256").toString(),((Number)row.get("bytes")).longValue());
                String text=new String(body,java.nio.charset.StandardCharsets.UTF_8);
                int points=text.codePointCount(0,text.length()); if(e.start()<0||e.end()>points||e.start()>=e.end()) reject();
                String quote=text.substring(text.offsetByCodePoints(0,e.start()),text.offsetByCodePoints(0,e.end()));
                var s=sources.putObject(e.evidenceId()).put("evidenceId",e.evidenceId()).put("documentId",e.articleId()).put("documentVersion",e.articleVersion())
                    .put("bodySha256",row.get("sha256").toString()).put("title",(String)row.get("title")).put("publisher",(String)row.get("publisher")).put("sourceKind",(String)row.get("kind")).put("quote",quote).put("url",article.url()).put("publishedAt",at.toString())
                    .put("grantId",grant.string("grantId")).put("grantRevision",grant.string("revision"));
                s.putArray("recipients").add("openai"); evidenceIds.add(e.evidenceId());
            }
            if(sources.isEmpty()) continue;
            for(var relation:visible.relations()) {
                if(!issue.issueId().equals(relation.source()) || !Set.of("INVOLVES","STRUCTURALLY_RELATED_TO").contains(relation.relationType())) continue;
                var refs=relation.evidenceIds().stream().filter(evidenceIds::contains).toList(); if(refs.isEmpty())continue;
                var company=visible.companies().stream().filter(c->c.companyId().equals(relation.target())).findFirst().orElseThrow();
                var link=links.addObject().put("companyId",company.companyId()).put("name",company.label()).put("role",relation.role()).put("relationType",relation.relationType());
                var array=link.putArray("evidenceIds");refs.forEach(array::add);
                link.putObject("observedMovement").put("status","unavailable").put("reason","no_cutoff_price_observation");
            }
            if(links.isEmpty())continue;
            var candidate=candidates.addObject().put("issueId",issue.issueId()).put("title",issue.label());
            candidate.set("sources",sources);candidate.set("companies",links);
            candidate.putObject("freshnessReview").put("decision","REQUIRES_REVIEW").putArray("deltaEvidenceIds").addAll(sources.propertyNames().stream().map(JsonNodeFactory.instance::stringNode).toList());
            candidate.put("snapshotSha256",Canonical.sha256(Canonical.appBytes(candidate)));
        }
        if(bindings.isEmpty()) throw new IllegalStateException("briefing_grants_and_sources_required");
        // A historical import is not evidence of complete current collection. Never turn absent fresh input into "no news".
        if(candidates.isEmpty()) throw new IllegalStateException("current_window_evidence_required");
        result.putObject("coverage").put("scope","currently_published_graph_only").put("completeMarketCoverage",false).put("outsideWindowOrUnknownClock",outside).put("modelPermissionExcluded",denied);
        var previous=result.putObject("previous").put("status","unavailable");
        var ids=jdbc.queryForList("SELECT id FROM briefing_rounds WHERE status='published' AND published_at<=? AND scheduled_at<? AND ((?='evening' AND edition='morning' AND round_date=?::date) OR (?='morning' AND edition='evening' AND round_date<?::date)) ORDER BY scheduled_at DESC LIMIT 1",String.class,Timestamp.from(cutoff),Timestamp.from(cutoff),round.string("edition"),round.string("date"),round.string("edition"),round.string("date"));
        if(!ids.isEmpty()) {
            var prior=new com.zoop.briefing.storage.BriefingRoundRepository(jdbc).findById(ids.getFirst()).orElseThrow();
            if(prior.publicSnapshot().has("serverGeneration")&&readAccess.mayRead(prior,"briefing-server-previous")) {
                BriefingSnapshotValidator.validate(prior);
                previous.put("status","available").put("roundId",prior.id());
                previous.put("payloadSha256",jdbc.queryForObject("SELECT payload_sha256 FROM briefing_rounds WHERE id=?",String.class,prior.id()));
                previous.set("records",prior.publicSnapshot().path("serverGeneration").path("records").deepCopy());
                previous.set("selected",prior.publicSnapshot().path("serverGeneration").path("selected").deepCopy());
            }
        }
        result.put("inputSha256",Canonical.sha256(Canonical.appBytes(result))); return result;
    }

    private StrictJson.Obj findGrant(StrictJson.Obj root,GrantRegistry registry,String provider) {
        for(JsonNode node:root.array("grants")) {
            var grant=StrictJson.Obj.of(node);
            if(provider.equals(grant.string("sourceId")) && GrantRegistry.evaluate(registry.current(grant.string("grantId")).orElse(null),provider,grant.string("revision"),
                List.of("briefing-outlook","semantic-verification"),List.of("openai"),true,Instant.now())==null) return grant;
        }
        return null;
    }
    private boolean inScope(String provider,String document,String version,String sha) {
        try {
            if(Files.size(scopePath)>1_000_000)reject();
            var scope=StrictJson.parseObject(Files.readAllBytes(scopePath));
            if(!"briefing-model-scope-v1".equals(scope.string("schemaVersion"))||scope.string("authorizationRef").isBlank())reject();
            for(JsonNode node:scope.array("sources")) {
                var pin=StrictJson.Obj.of(node);
                if(provider.equals(pin.string("sourceId"))&&document.equals(pin.string("documentId"))&&version.equals(pin.string("documentVersion"))&&sha.equals(pin.string("bodySha256")))return true;
            }
            return false;
        } catch(java.io.IOException e){throw new IllegalStateException("source_scope_unavailable");}
    }
    private byte[] readGrants() {try{return Files.readAllBytes(grantsPath);}catch(Exception e){throw new IllegalStateException("grants_unavailable");}}

    public void check(StrictJson.Obj prepared) {
        ObjectNode copy=(ObjectNode)prepared.node().deepCopy();String digest=prepared.string("inputSha256");copy.remove("inputSha256");
        if(!digest.equals(Canonical.sha256(Canonical.appBytes(copy))))reject();
        var publication=reader.read(prepared.string("graphVersion"));
        if(!publication.snapshotArtifact().sha256().equals(prepared.string("graphSnapshotSha256")))reject();
        var exclusions=authority.current(publication,"briefing-server");if(exclusions.revision()!=prepared.raw("exclusionRevision").asLong(-1))reject();
        var visible=GraphSnapshotFilter.apply(publication.snapshot(),null,exclusions);
        var registry=GrantRegistry.parse(readGrants());
        Set<String> bound=new HashSet<>();
        for(JsonNode binding:prepared.array("sourceBindings")) {
            var pin=StrictJson.Obj.of(binding);if(!bound.add(pin.string("documentId")+"\n"+pin.string("documentVersion")))reject();
            var b=StrictJson.Obj.of(binding); var rows=jdbc.queryForList("SELECT a.provider FROM articles a JOIN article_versions v ON v.article_id=a.id WHERE a.id=? AND v.version=? AND a.access_status='available'",b.string("documentId"),b.string("documentVersion"));
            if(rows.size()!=1||GrantRegistry.evaluate(registry.current(b.string("grantId")).orElse(null),rows.getFirst().get("provider").toString(),b.string("grantRevision"),List.of("briefing-outlook","semantic-verification"),List.of("openai"),true,Instant.now())!=null)reject();
            if(visible.articles().stream().noneMatch(a->a.articleId().equals(b.string("documentId")) && a.version().equals(b.string("documentVersion"))))reject();
        }
        verifyCandidates(prepared,visible,bound);
        var previous=prepared.object("previous");
        if("available".equals(previous.string("status"))) {
            var prior=new com.zoop.briefing.storage.BriefingRoundRepository(jdbc).findById(previous.string("roundId")).orElseThrow();
            String sha=jdbc.queryForObject("SELECT payload_sha256 FROM briefing_rounds WHERE id=?",String.class,prior.id());
            if(!sha.equals(previous.string("payloadSha256"))||!readAccess.mayRead(prior,"briefing-server-previous"))reject();
        }
    }

    private void verifyCandidates(StrictJson.Obj prepared,PublicGraphSnapshot visible,Set<String> bound) {
        var round=prepared.object("round");Instant from=Instant.parse(round.string("windowFrom")),to=Instant.parse(round.string("windowTo"));
        Set<String> seen=new HashSet<>();
        for(JsonNode node:prepared.array("candidates")) {
            var c=StrictJson.Obj.of(node);if(!seen.add(c.string("issueId")))reject();
            ObjectNode hash=(ObjectNode)node.deepCopy();hash.remove("snapshotSha256");
            if(!c.string("snapshotSha256").equals(Canonical.sha256(Canonical.appBytes(hash))))reject();
            var issue=visible.issues().stream().filter(i->i.issueId().equals(c.string("issueId"))).findFirst().orElseThrow();
            if(!issue.label().equals(c.string("title")))reject();
            for(String id:c.object("sources").node().propertyNames()) {
                var pin=c.object("sources").object(id);
                if(!issue.evidenceIds().contains(id)||!id.equals(pin.string("evidenceId"))||!bound.contains(pin.string("documentId")+"\n"+pin.string("documentVersion")))reject();
                var e=visible.evidence().stream().filter(v->v.evidenceId().equals(id)).findFirst().orElseThrow();
                if(!e.articleId().equals(pin.string("documentId"))||!e.articleVersion().equals(pin.string("documentVersion")))reject();
                var article=visible.articles().stream().filter(a->a.articleId().equals(e.articleId())&&a.version().equals(e.articleVersion())).findFirst().orElseThrow();
                var row=jdbc.queryForMap("SELECT v.title,v.publisher,v.published_at,t.storage_uri,t.sha256,t.bytes FROM article_versions v JOIN artifacts t ON t.id=v.text_artifact_id WHERE v.article_id=? AND v.version=?",e.articleId(),e.articleVersion());
                Instant at=((Timestamp)row.get("published_at")).toInstant();
                var articleInfo=jdbc.queryForMap("SELECT provider,kind FROM articles WHERE id=?",e.articleId());String provider=articleInfo.get("provider").toString();
                if(!Objects.equals(row.get("title"),pin.stringOrNull("title"))||!Objects.equals(row.get("publisher"),pin.stringOrNull("publisher"))||!articleInfo.get("kind").equals(pin.string("sourceKind")))reject();
                if(!inScope(provider,e.articleId(),e.articleVersion(),row.get("sha256").toString()))reject();
                if(!at.isAfter(from)||at.isAfter(to)||!at.equals(Instant.parse(pin.string("publishedAt")))||!article.url().equals(pin.string("url"))||!row.get("sha256").equals(pin.string("bodySha256")))reject();
                String text=new String(files.readVerified(row.get("storage_uri").toString(),row.get("sha256").toString(),((Number)row.get("bytes")).longValue()),java.nio.charset.StandardCharsets.UTF_8);
                if(!text.substring(text.offsetByCodePoints(0,e.start()),text.offsetByCodePoints(0,e.end())).equals(pin.string("quote")))reject();
            }
            for(JsonNode link:c.array("companies")) {
                var company=StrictJson.Obj.of(link);
                if(visible.relations().stream().noneMatch(r->r.source().equals(issue.issueId())&&r.target().equals(company.string("companyId"))&&r.relationType().equals(company.string("relationType"))&&Objects.equals(r.role(),company.stringOrNull("role"))&&r.evidenceIds().containsAll(company.strings("evidenceIds"))))reject();
            }
        }
        if(seen.isEmpty())reject();
    }

    public ObjectNode publish(StrictJson.Obj request) {
        var prepared=request.object("prepared"); check(prepared); var round=prepared.object("round");
        var payload=request.object("payload"); var snapshot=request.object("snapshot");
        String admitted=jdbc.queryForObject("SELECT stages->>'inputSha256' FROM briefing_attempts WHERE id=?",String.class,request.string("attemptId"));
        if(!prepared.string("inputSha256").equals(admitted))reject();
        if(!round.string("id").equals(payload.string("id"))||!prepared.string("graphVersion").equals(payload.string("graphVersion"))
            ||!snapshot.array("sourceBindings").equals(prepared.array("sourceBindings")))reject();
        Set<String> allowed=new HashSet<>(); for(JsonNode c:prepared.array("candidates"))allowed.add(c.path("issueId").asString());
        Set<String> selected=new HashSet<>(); for(JsonNode i:payload.array("items"))if(!allowed.contains(i.path("eventId").asString())||!selected.add(i.path("eventId").asString()))reject();
        if(selected.size()>3)reject();
        JsonNode comparison="evening".equals(round.string("edition"))?StrictJson.newObject().put("status","unavailable").put("reason","판단 비교는 기업별 분석에 포함되며 회차 전체 변화 평가는 별도 검증 자료가 없습니다."):null;
        var proposed=new BriefingRound(round.string("id"),LocalDate.parse(round.string("date")),round.string("edition"),Instant.parse(round.string("scheduledAt")),
            Instant.parse(round.string("windowFrom")),Instant.parse(round.string("windowTo")),false,"published",Instant.now(),Instant.parse(payload.string("generatedAt")),prepared.string("graphVersion"),payload.node(),snapshot.node(),comparison);
        BriefingSnapshotValidator.validate(proposed);
        for(JsonNode item:payload.array("items"))BriefingItemDetailValidator.validate(proposed,item,snapshot.raw("itemDetails").path(item.path("eventId").asString()),new com.zoop.briefing.storage.BriefingRoundRepository(jdbc));
        if(!readAccess.mayRead(proposed,"briefing-server-publish"))reject();
        var ledger=new BriefingUsageLedger(named,new DataSourceTransactionManager(source),artifacts,Duration.ofSeconds(120));
        return ledger.publish(request.string("attemptId"),request.string("ownerToken"),()->{
            check(prepared);var r=round;
            int updated=jdbc.update("""
                UPDATE briefing_rounds SET graph_version_id=?,review_revision=?,rule_revision=?,published_payload=?::jsonb,
                  public_snapshot=?::jsonb,payload_sha256=encode(sha256(convert_to((?::jsonb)::text,'UTF8')),'hex'),
                  generated_at=?::timestamptz,published_at=clock_timestamp(),schema_version='briefing-server-v1',status='published',
                  comparison_snapshot=?::jsonb,generation_token=NULL,lease_until=NULL WHERE id=? AND published_at IS NULL
                """,prepared.string("graphVersion"),payload.count("reviewRevision"),payload.count("ruleRevision"),payload.node().toString(),snapshot.node().toString(),payload.node().toString(),payload.string("generatedAt"),comparison==null?null:comparison.toString(),r.string("id"));
            if(updated!=1)reject();
            String sha=jdbc.queryForObject("SELECT payload_sha256 FROM briefing_rounds WHERE id=?",String.class,r.string("id"));
            ObjectNode pool=(ObjectNode)request.object("pool").node().deepCopy();pool.put("publicationPayloadSha256",sha);
            if(!round.string("id").equals(pool.path("roundId").asString())||!pool.path("complete").asBoolean()||pool.path("candidateCount").asInt(-1)!=pool.path("candidates").size()||!pool.path("inputSha256").asString().matches("[a-f0-9]{64}"))reject();
            String poolText=pool.toString();jdbc.update("INSERT INTO briefing_personal_pools(id,round_id,input_sha256,snapshot,snapshot_sha256) VALUES(?,?,?,?::jsonb,encode(sha256(convert_to((?::jsonb)::text,'UTF8')),'hex'))",
                "brfp-"+pool.path("inputSha256").asString(),r.string("id"),pool.path("inputSha256").asString(),poolText,poolText);
            return StrictJson.newObject().put("status","published").put("roundId",r.string("id")).put("payloadSha256",sha);
        });
    }
    private static String required(Map<String,String> env,String key){String v=env.get(key);if(v==null||v.isBlank())throw new IllegalArgumentException(key);return v;}
    private static void reject(){throw new IllegalArgumentException("briefing_server_binding_rejected");}
}
