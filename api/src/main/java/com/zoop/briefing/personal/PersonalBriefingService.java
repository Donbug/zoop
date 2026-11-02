package com.zoop.briefing.personal;

import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.briefing.query.BriefingGraphContentAuthority;
import com.zoop.briefing.query.BriefingQueryService;
import com.zoop.briefing.storage.BriefingRound;
import com.zoop.briefing.storage.BriefingRoundRepository;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.graph.read.PersonalCompanies;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.dao.DataAccessException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;
import java.time.Instant;
import java.util.*;

/** Read-only deterministic selection from ALL qualified candidates, not the common publication's three items. */
@Service
public class PersonalBriefingService {
    public static final String POLICY="personal-issue-selection-v1";
    private final PersonalBriefingRepository pools;
    private final BriefingRoundRepository rounds;
    private final BriefingQueryService publicReads;
    private final PersonalCompanies companies;
    private final PersonalCandidateAccess access;
    private final BriefingGraphContentAuthority graph;
    private final JsonMapper json=JsonMapper.builder().build();
    public PersonalBriefingService(PersonalBriefingRepository pools, BriefingRoundRepository rounds,
            BriefingQueryService publicReads, PersonalCompanies companies, PersonalCandidateAccess access,
            BriefingGraphContentAuthority graph) {
        this.pools=pools; this.rounds=rounds; this.publicReads=publicReads; this.companies=companies; this.access=access;
        this.graph=graph;
    }
    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ,timeout=10)
    public ObjectNode get(String roundId, MemberPrincipal member, String requestId) {
        if (member==null) throw new CustomException(ErrorCode.AUTH_REQUIRED);
        if (roundId==null || roundId.isBlank() || roundId.length()>256) throw new CustomException(ErrorCode.INVALID_REQUEST);
        try {
            var round=rounds.findById(roundId).orElseThrow(()->new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
            // Same suspension/replay/current rights rules as the public original.
            var common=publicReads.get(round.date(),round.edition(),requestId);
            if (!roundId.equals(common.path("id").asString()) || !"published".equals(common.path("status").asString()))
                throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
            var ids=companies.of(member);
            var out=json.createObjectNode().put("roundId",roundId).put("dataAsOf",round.windowTo().toString())
                    .put("policyVersion",POLICY).put("basisObservedAt",Instant.now().toString());
            var basis=out.putObject("basis"); basis.set("holdings",json.valueToTree(ids.holdings()));
            basis.set("watchlist",json.valueToTree(ids.watchlist())); basis.put("holdingsKind","connected_mock_portfolio");
            out.putArray("items"); out.putArray("tracking"); out.putNull("poolVersion"); out.putNull("previousRoundId");
            out.put("eligibleCount",0).put("matchingCount",0).put("excludedByCurrentAccess",0);
            Set<String> scope=new LinkedHashSet<>(ids.holdings()); scope.addAll(ids.watchlist());
            if (scope.isEmpty()) return state(out,"no_companies","보유·관심 종목을 등록해 주세요.");
            var pool=pools.pool(roundId).orElse(null);
            if (pool==null) return state(out,"pool_unavailable","전체 후보 저장본이 없어 공통 이슈로 대신 채우지 않습니다.");
            validatePool(pool,round);
            out.put("poolVersion",pool.path("inputSha256").asString()).put("scope",pool.path("scope").asString());
            if (rounds.changes(roundId).stream().anyMatch(c->"correction".equals(c.kind())))
                return state(out,"pool_unavailable","정정된 회차입니다. 후보 저장본의 재검증이 필요합니다.");
            var graphContext=graph.context(round.graphVersion(),requestId);
            var eligible=eligible(pool,round); out.put("eligibleCount",eligible.size());
            var matches=new ArrayList<JsonNode>(); int blocked=0;
            for (var c:eligible) {
                if (matched(c,scope).isEmpty()) continue;
                if (!access.readable(c,graphContext,requestId)) {blocked++;continue;}
                matches.add(c);
            }
            var selected=select(matches,scope);
            out.put("matchingCount",matches.size()).put("excludedByCurrentAccess",blocked);
            for (var c:selected) {
                var item=(ObjectNode)c.deepCopy(); item.remove("verification");
                for(var source:item.path("sources")) if(source instanceof ObjectNode object) object.remove(List.of("grantId","grantRevision","recipients","bodySha256","documentVersion"));
                var links=item.putArray("matches");
                for (var relation:matched(c,scope)) {
                    String id=relation.path("companyId").asString();
                    var link=links.addObject().put("companyId",id).put("name",relation.path("name").asString())
                            .put("reason",relation.path("reason").asString()).put("directness",relation.path("directness").asString());
                    var kinds=link.putArray("kinds"); if(ids.holdings().contains(id))kinds.add("holding"); if(ids.watchlist().contains(id))kinds.add("watchlist");
                }
                out.withArray("items").add(item);
            }
            track(out,round,scope,requestId,pool,graphContext);
            return state(out,selected.isEmpty()?(blocked>0?"sources_unavailable":"no_matching_issues"):"available",
                    selected.isEmpty()?"이번 회차에서 현재 제공 가능한 적격 관련 이슈가 없습니다.":null);
        } catch (DataAccessException | IllegalArgumentException | com.zoop.common.json.StrictJson.Malformed error) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
    }
    static void validatePool(JsonNode pool,BriefingRound round) {
        if (!"personal-candidate-pool-v1".equals(pool.path("schemaVersion").asString())
                || !round.id().equals(pool.path("roundId").asString())
                || !round.windowTo().equals(Instant.parse(pool.path("cutoff").asString()))
                || !pool.path("complete").asBoolean() || !pool.path("candidates").isArray()
                || pool.path("candidateCount").asInt(-1)!=pool.path("candidates").size()
                || !pool.path("inputSha256").asString().matches("[a-f0-9]{64}")) throw new IllegalArgumentException("pool binding");
        Set<String> seen=new HashSet<>();
        for(var c:pool.path("candidates")) {
            if(!seen.add(c.path("issueId").asString()) || c.path("issueId").asString().isBlank()
                    || !c.path("importance").isIntegralNumber() || c.path("importance").asInt()<0 || c.path("importance").asInt()>3
                    || !c.path("verified").isBoolean() || !c.path("sources").isArray() || !c.path("companies").isArray())
                throw new IllegalArgumentException("candidate shape");
            Set<String> evidence=new HashSet<>(),links=new HashSet<>();
            for(var source:c.path("sources")) {
                if(source.path("evidenceId").asString().isBlank() || !evidence.add(source.path("evidenceId").asString())
                        || !source.path("bodySha256").asString().matches("[a-f0-9]{64}")
                        || !source.path("url").asString().matches("https?://[^\\s]+")) throw new IllegalArgumentException("source shape");
            }
            for(var link:c.path("companies")) {
                if(!links.add(link.path("companyId").asString())) throw new IllegalArgumentException("duplicate company");
                for(var id:link.path("evidenceIds")) if(!evidence.contains(id.asString()))throw new IllegalArgumentException("foreign relation evidence");
            }
        }
    }

    static List<JsonNode> eligible(JsonNode pool,BriefingRound round) {
        var list=new ArrayList<JsonNode>();
        for(var c:pool.path("candidates")) {
            if (!c.path("verified").asBoolean() || c.path("importance").asInt()<2
                    || !List.of("new_event","material_update").contains(c.path("informationChange").asString())) continue;
            if (c.path("eventKey").asString().isBlank() || c.path("sources").isEmpty()) continue;
            boolean valid=true;
            for(var s:c.path("sources")) {
                Instant at=Instant.parse(s.path("publishedAt").asString());
                if(at.isAfter(round.windowTo()) || (round.windowFrom()!=null && !at.isAfter(round.windowFrom()))
                        || s.path("quote").asString().isBlank() || !s.path("quoteVerified").asBoolean()) valid=false;
            }
            if(valid)list.add(c);
        }
        return list;
    }
    static List<JsonNode> matched(JsonNode c,Set<String> scope) {
        return c.path("companies").valueStream().filter(r->scope.contains(r.path("companyId").asString())
                && List.of("direct","indirect").contains(r.path("directness").asString())
                && !r.path("reason").asString().isBlank() && !r.path("evidenceIds").isEmpty()).toList();
    }
    static List<JsonNode> select(List<JsonNode> candidates,Set<String> scope) {
        var sorted=new ArrayList<>(candidates);
        sorted.sort(Comparator.<JsonNode>comparingInt(c->c.path("importance").asInt()).reversed()
                .thenComparing(Comparator.comparingInt((JsonNode c)->"material_update".equals(c.path("informationChange").asString())?1:0).reversed())
                .thenComparing(Comparator.comparingInt((JsonNode c)->matched(c,scope).size()).reversed())
                .thenComparing(c->c.path("issueId").asString()));
        var selected=new ArrayList<JsonNode>(); Set<String> events=new HashSet<>(),support=new HashSet<>();
        for(var c:sorted) {
            Set<String> quotes=new HashSet<>(); for(var s:c.path("sources"))quotes.add(s.path("documentId").asString()+":"+s.path("bodySha256").asString()+":"+s.path("quote").asString());
            if(events.contains(c.path("eventKey").asString()) || quotes.stream().anyMatch(support::contains))continue;
            events.add(c.path("eventKey").asString());support.addAll(quotes);selected.add(c);if(selected.size()==3)break;
        }
        return selected;
    }
    private void track(ObjectNode out,BriefingRound round,Set<String> scope,String requestId,JsonNode pool,
            BriefingGraphContentAuthority.Context graphContext) {
        // Fixed predecessor; never substitute the latest successful round or match by company alone.
        String priorId=pool.path("previousRoundId").asString("");
        if(priorId.isBlank()) {out.put("trackingStatus","previous_not_recorded");return;}
        var previous=rounds.findById(priorId).orElse(null);
        if(previous==null || !previous.windowTo().isBefore(round.windowTo())
                || (round.windowFrom()!=null && !previous.windowTo().equals(round.windowFrom()))
                || !"published".equals(previous.status()) || rounds.changes(priorId).stream().anyMatch(c->"correction".equals(c.kind()))) {
            out.put("trackingStatus","previous_unavailable");return;
        }
        // A missing/revoked predecessor must not hide valid current results.
        try {
            var prior=publicReads.get(previous.date(),previous.edition(),requestId);
            if(!"published".equals(prior.path("status").asString())) {out.put("trackingStatus","previous_unavailable");return;}
        } catch(CustomException unavailable) {out.put("trackingStatus","previous_unavailable");return;}
        JsonNode priorPool=pools.pool(priorId).orElse(null);
        if(priorPool==null) {out.put("trackingStatus","previous_pool_unavailable");return;}
        validatePool(priorPool,previous);
        var priorGraph=graph.context(previous.graphVersion(),requestId);
        var allowed=new ArrayList<JsonNode>();
        for(var c:eligible(priorPool,previous))if(!matched(c,scope).isEmpty() && access.readable(c,priorGraph,requestId))allowed.add(c);
        out.put("previousRoundId",priorId).put("trackingStatus","available");
        for(var old:select(allowed,scope))for(var relation:matched(old,scope)) {
            String company=relation.path("companyId").asString();
            var now=pool.path("candidates").valueStream().filter(c->c.path("eventKey").equals(old.path("eventKey"))
                    && eligible(pool,round).contains(c) && !matched(c,Set.of(company)).isEmpty()).findFirst().orElse(null);
            if(now!=null && !access.readable(now,graphContext,requestId))now=null;
            var row=out.withArray("tracking").addObject().put("issueId",old.path("issueId").asString())
                    .put("title",old.path("title").asString()).put("companyId",company).put("companyName",relation.path("name").asString())
                    .put("status",now==null?"not_observed":"follow_up_available")
                    .put("message",now==null?"이번 회차에 같은 사건의 후속 근거가 없습니다. 확인 완료를 뜻하지 않습니다.":"같은 이슈·기업의 후속 자료가 있습니다. 조건 충족 여부는 별도 확인이 필요합니다.")
                    .put("basis","current_companies_replayed_on_fixed_previous_pool");
            row.set("nextCheck",relation.path("nextCheck").isMissingNode()?json.nullNode():relation.path("nextCheck").deepCopy());
        }
    }
    private ObjectNode state(ObjectNode out,String status,String message){return out.put("status",status).put("message",message);}
}
