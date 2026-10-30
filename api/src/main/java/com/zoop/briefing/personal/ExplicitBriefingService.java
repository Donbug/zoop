package com.zoop.briefing.personal;

import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.briefing.query.BriefingQueryService;
import com.zoop.briefing.storage.BriefingRoundRepository;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.graph.read.PersonalCompanies;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;
import java.util.*;

/** D-BRF-01/02: explicit member choices; never silently imports an account or starts paid AI. */
@Service
public class ExplicitBriefingService {
    public record Choice(List<String> companyIds,Integer maxIssues,Integer minIssues,Integer perCompanyLimit) {}
    private final PersonalBriefingRepository pools;
    private final BriefingRoundRepository rounds;
    private final BriefingQueryService reads;
    private final PersonalCandidateAccess access;
    private final PersonalCompanies personal;
    private final JdbcTemplate jdbc;
    private final SelectedGenerationRepository generated;
    private final JsonMapper json=JsonMapper.builder().build();
    public ExplicitBriefingService(PersonalBriefingRepository pools,BriefingRoundRepository rounds,BriefingQueryService reads,
            PersonalCandidateAccess access,PersonalCompanies personal,JdbcTemplate jdbc,SelectedGenerationRepository generated){
        this.pools=pools;this.rounds=rounds;this.reads=reads;this.access=access;this.personal=personal;this.jdbc=jdbc;this.generated=generated;
    }
    public ObjectNode options(MemberPrincipal member,boolean importMine){
        requireMember(member);var out=json.createObjectNode();var list=out.putArray("companies");
        jdbc.query("SELECT id,name,logo_url FROM companies ORDER BY name,id LIMIT 1000",r->{list.addObject().put("id",r.getString(1)).put("name",r.getString(2)).put("logoUrl",r.getString(3));});
        out.putArray("selectedIds");
        if(importMine){var ids=personal.of(member);var selected=out.withArray("selectedIds");
            java.util.stream.Stream.concat(ids.holdings().stream(),ids.watchlist().stream()).distinct().forEach(selected::add);
            out.put("importedBasis","connected_mock_holdings_and_watchlist");}
        return out;
    }
    static Set<String> validate(Choice c){
        if(c==null || c.companyIds()==null || c.companyIds().isEmpty() || c.companyIds().size()>1000
                || c.companyIds().stream().anyMatch(x->x==null || x.isBlank() || x.length()>160)
                || new HashSet<>(c.companyIds()).size()!=c.companyIds().size())throw new CustomException(ErrorCode.INVALID_REQUEST);
        int max=c.maxIssues()==null?3:c.maxIssues(),min=c.minIssues()==null?0:c.minIssues(),per=c.perCompanyLimit()==null?3:c.perCompanyLimit();
        if(max<1||max>3||min<0||min>max||per<1||per>3)throw new CustomException(ErrorCode.INVALID_REQUEST);
        return new TreeSet<>(c.companyIds());
    }
    private static void requireMember(MemberPrincipal p){if(p==null)throw new CustomException(ErrorCode.AUTH_REQUIRED);}
    @Transactional(readOnly=true,timeout=10)
    public ObjectNode select(String roundId,MemberPrincipal member,Choice choice,String requestId){
        requireMember(member);Set<String> scope=validate(choice);
        var known=new HashSet<>(jdbc.query("SELECT id FROM companies",(r,i)->r.getString(1)));
        if(!known.containsAll(scope))throw new CustomException(ErrorCode.INVALID_REQUEST);
        var round=rounds.findById(roundId).orElseThrow(()->new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
        var common=reads.get(round.date(),round.edition(),requestId);
        if(!roundId.equals(common.path("id").asString()) || !"published".equals(common.path("status").asString()))throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        if(rounds.changes(roundId).stream().anyMatch(c->"correction".equals(c.kind())))throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        var pool=pools.pool(roundId).orElseThrow(()->new CustomException(ErrorCode.SOURCE_UNAVAILABLE));
        PersonalBriefingService.validatePool(pool,round);
        var eligible=PersonalBriefingService.eligible(pool,round);var matches=new ArrayList<JsonNode>();int excluded=0;
        for(var c:eligible)if(!PersonalBriefingService.matched(c,scope).isEmpty()){
            if(access.readable(c,requestId))matches.add(c);else excluded++;
        }
        int max=choice.maxIssues()==null?3:choice.maxIssues(),min=choice.minIssues()==null?0:choice.minIssues(),per=choice.perCompanyLimit()==null?3:choice.perCompanyLimit();
        var selected=select(matches,scope,max,per);
        var out=json.createObjectNode().put("roundId",roundId).put("dataAsOf",round.windowTo().toString())
                .put("status",selected.isEmpty()?"no_matching_issues":"available").put("eligibleCount",eligible.size())
                .put("matchingCount",matches.size()).put("excludedByCurrentAccess",excluded).put("minimumShortfall",Math.max(0,min-selected.size()))
                .put("poolVersion",pool.path("inputSha256").asString()).put("policyVersion",pool.path("selectionPolicyVersion").asString());
        out.set("choice",json.valueToTree(new Choice(List.copyOf(scope),max,min,per)));
        out.put("selectionVersion",com.zoop.common.json.Canonical.sha256(com.zoop.common.json.Canonical.bytes(out)));
        var presentation=(ObjectNode)common.deepCopy();
        if(presentation.has("editionReview"))presentation.set("companyPriceBasis",presentation.path("editionReview").deepCopy());
        presentation.remove(List.of("continuity","editionReview","issueReading","judgmentUpdate","companyOutlooks","aiPriceOutlooks","preservedPublication","issueIntelligence","outlook"));
        presentation.putNull("graphVersion");((ObjectNode)presentation.path("metadata")).putNull("graphVersion");
        presentation.putNull("sinceMorning");presentation.putNull("previousComparison");
        var items=presentation.putArray("items");var details=out.putObject("details");var aiIssues=json.createArrayNode();
        var meta=pool.path("sharedMeta").isObject()?(ObjectNode)pool.path("sharedMeta").deepCopy():json.createObjectNode();int pending=0;
        var reasons=out.putArray("selectionReasons");
        for(var c:selected){
            reasons.addObject().put("issueId",c.path("issueId").asString()).put("whyImportant",c.path("whyImportant").asString()).put("whyNow",c.path("whyNow").asString());
            var shared=c.path("sharedView");
            if(!shared.isObject() && !c.path("analysisInput").path("inputSha256").asString().isBlank())
                shared=generated.analysis(roundId,c.path("issueId").asString(),c.path("analysisInput").path("inputSha256").asString()).orElse(shared);
            if(shared.isObject() && shared.path("item").path("eventId").equals(c.path("issueId"))){
                var item=(ObjectNode)shared.path("item").deepCopy();item.put("rank",items.size()+1);items.add(item);
                aiIssues.add(shared.path("analysis").deepCopy());details.set(c.path("issueId").asString(),shared.path("detail").deepCopy());
            }else{
                pending++;var item=items.addObject().put("eventId",c.path("issueId").asString()).put("title",c.path("title").asString())
                    .put("rank",items.size()).put("reason",c.path("whyImportant").asString()+" "+c.path("whyNow").asString())
                    .putNull("eventTime").put("timePrecision","unknown").put("evidenceCount",c.path("sources").size());
                var company=item.putArray("companies");for(var link:c.path("companies"))company.addObject().put("id",link.path("companyId").asString()).put("name",link.path("name").asString()).put("relationType","INVOLVES").putNull("role").put("roleUnconfirmed",true);
                var refs=item.putArray("evidenceIds");for(var s:c.path("sources"))refs.add(s.path("evidenceId").asString());
                item.putObject("summary").put("status","unavailable").put("reason","선정·근거 검증 완료. 이 이슈의 공통 기준 AI 분석은 아직 생성되지 않았습니다.");
                var d=details.putObject(c.path("issueId").asString()).put("roundId",roundId).put("eventId",c.path("issueId").asString()).put("title",c.path("title").asString()).put("selectionReason",item.path("reason").asString());
                d.set("summary",item.path("summary").deepCopy());d.set("companies",company.deepCopy());d.putArray("claims");d.putArray("limitations").add("이 이슈의 공통 기준 AI 분석은 아직 생성되지 않았습니다.");d.set("metadata",presentation.path("metadata").deepCopy());
                var evidence=d.putArray("evidence");for(var source:c.path("sources")) {var e=evidence.addObject().put("id",source.path("evidenceId").asString()).put("title","원문 자료").put("publisher","").put("sourceKind","news").put("quoteVerified",true).putNull("bodyContext");
                    for(String field:List.of("documentId","documentVersion","quote","url","publishedAt"))e.set(field,source.path(field).deepCopy());}

            }
        }
        if(!aiIssues.isEmpty()){
            meta.put("schemaVersion","issue-intelligence-v1").put("policyVersion","issue-selection-policy-v2").put("model","gpt-6-luna").put("verificationMode","separate_model_request");
            if(!meta.has("generatedAt"))meta.put("generatedAt",java.time.Instant.now().toString());
            meta.put("roundId",roundId).put("date",round.date().toString()).put("edition",round.edition()).put("cutoff",round.windowTo().toString());
            meta.set("issues",aiIssues);meta.put("resultVersion",com.zoop.common.json.Canonical.sha256(com.zoop.common.json.Canonical.bytes(aiIssues))+"-explicit");
            if(pending==0)presentation.set("issueIntelligence",meta);
            else {
                var verified=(ObjectNode)presentation.deepCopy();var readyItems=verified.putArray("items");
                for(var item:items)if(aiIssues.valueStream().anyMatch(a->a.path("issueId").equals(item.path("eventId"))))readyItems.add(item.deepCopy());
                verified.set("issueIntelligence",meta);out.set("verifiedPresentation",verified);
            }
        }
        presentation.put("emptyReason",selected.isEmpty()?"no_issues_in_window":null);
        out.put("analysisStatus",selected.isEmpty()?"no_issues":pending==0?"ready":"needs_generation").put("pendingAnalysisCount",pending).set("presentation",presentation);
        out.set("tracking",tracking(pool,round,scope,requestId));return out;
    }
    static List<JsonNode> select(List<JsonNode> candidates,Set<String> scope,int max,int per){
        // issue-selection-policy-v2: business importance first, only comparable unshared
        // prices within a tied cohort, capped verified direct parties, stable issue ID.
        var ordered=new ArrayList<JsonNode>();var groups=new TreeMap<Integer,List<JsonNode>>(Comparator.reverseOrder());
        candidates.forEach(c->groups.computeIfAbsent(c.path("importance").asInt(),k->new ArrayList<>()).add(c));
        for(var cohort:groups.values()) {
            Set<JsonNode> bases=new HashSet<>(),observations=new HashSet<>();boolean comparable=true;
            for(var c:cohort){var p=c.path("priceSignal");
                if(!"observed".equals(p.path("status").asString()))comparable=false;
                bases.add(p.path("basis"));for(var key:p.path("keys"))if(!observations.add(key))comparable=false;
            }
            final boolean usePrice=comparable&&bases.size()==1;
            cohort.sort(Comparator.<JsonNode,java.math.BigDecimal>comparing(c->usePrice?new java.math.BigDecimal(c.path("priceSignal").path("value").asString()):java.math.BigDecimal.ZERO).reversed()
                .thenComparing(Comparator.comparingInt((JsonNode c)->c.path("relationSignal").path("value").asInt()).reversed())
                .thenComparing(c->c.path("issueId").asString()));ordered.addAll(cohort);
        }
        var selected=new ArrayList<JsonNode>();var counts=new HashMap<String,Integer>();var events=new HashSet<String>();var support=new HashSet<String>();
        for(var next:ordered){
            var ids=PersonalBriefingService.matched(next,scope).stream().map(x->x.path("companyId").asString()).toList();
            if(ids.isEmpty()||ids.stream().anyMatch(id->counts.getOrDefault(id,0)>=per))continue;
            Set<String> quotes=new HashSet<>();for(var source:next.path("sources"))quotes.add(source.path("documentId").asString()+":"+source.path("bodySha256").asString()+":"+source.path("quote").asString());
            if(events.contains(next.path("eventKey").asString())||quotes.stream().anyMatch(support::contains))continue;
            events.add(next.path("eventKey").asString());support.addAll(quotes);selected.add(next);ids.forEach(id->counts.merge(id,1,Integer::sum));
            if(selected.size()==max)break;
        }
        return selected;
    }
    private JsonNode tracking(JsonNode pool,com.zoop.briefing.storage.BriefingRound current,Set<String> scope,String requestId){
        var result=json.createArrayNode();String priorId=pool.path("previousRoundId").asString("");if(priorId.isBlank())return result;
        var previous=rounds.findById(priorId).orElse(null);if(previous==null||!previous.windowTo().isBefore(current.windowTo()))return result;
        try{var p=reads.get(previous.date(),previous.edition(),requestId);if(!priorId.equals(p.path("id").asString())||!"published".equals(p.path("status").asString()))return result;}catch(CustomException e){return result;}
        var old=pools.pool(priorId).orElse(null);if(old==null)return result;PersonalBriefingService.validatePool(old,previous);
        for(var c:PersonalBriefingService.eligible(old,previous))if(!PersonalBriefingService.matched(c,scope).isEmpty()&&access.readable(c,requestId))
            result.addObject().put("issueId",c.path("issueId").asString()).put("title",c.path("title").asString()).put("previousRoundId",priorId).put("nextCheck",c.path("nextCheck").asString("")).put("status","not_evaluated").put("poolVersion",old.path("inputSha256").asString());
        return result;
    }
}
