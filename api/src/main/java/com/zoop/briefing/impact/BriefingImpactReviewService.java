package com.zoop.briefing.impact;

import com.zoop.briefing.impact.BriefingImpacts.*;
import com.zoop.briefing.query.BriefingQueryService;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import com.zoop.common.response.Metadata;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.*;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import java.nio.file.*;
import java.time.*;
import java.util.*;

/** Opt-in historical assessment read. Never changes or substitutes a publication graph/receipt. */
@Service
public class BriefingImpactReviewService {
    private final BriefingQueryService briefings;
    private final JdbcTemplate jdbc;
    private final JsonMapper mapper;
    private final Clock clock;
    private final String path;
    private final String expectedSha;
    private final BriefingImpactEvidencePlanReader plans;
    public BriefingImpactReviewService(BriefingQueryService briefings, JdbcTemplate jdbc, JsonMapper mapper, Clock clock,
            String path, String expectedSha) {this(briefings,jdbc,mapper,clock,path,expectedSha,null);}
    @Autowired
    public BriefingImpactReviewService(BriefingQueryService briefings, JdbcTemplate jdbc, JsonMapper mapper, Clock clock,
            @Value("${zoop.briefing.impact-review.manifest:}") String path,
            @Value("${zoop.briefing.impact-review.sha256:}") String expectedSha, BriefingImpactEvidencePlanReader plans) {
        this.briefings=briefings; this.jdbc=jdbc; this.mapper=mapper; this.clock=clock;
        this.path=path; this.expectedSha=expectedSha;
        this.plans=plans;
    }

    @Transactional(readOnly=true, isolation=Isolation.REPEATABLE_READ, timeout=10)
    public BriefingImpacts get(String roundId, String eventId, String version, String requestId) {
        var round=briefings.impactBasis(roundId,eventId,requestId);
        if (version!=null && !version.equals(round.graphVersion())) throw new CustomException(ErrorCode.INVALID_REQUEST);
        var metadata=new Metadata("s3_issue_impacts",round.windowTo(),round.graphVersion(),requestId,false,List.of());
        if (path.isBlank()) return new BriefingImpacts(roundId,eventId,round.graphVersion(),round.windowTo(),
                "unavailable","historical_assessment_not_recorded",List.of(),metadata);
        try {
            check(expectedSha.matches("[a-f0-9]{64}"));
            Path manifest=Path.of(path);
            byte[] bytes=read(manifest,2_000_000);
            check(Canonical.sha256(bytes).equals(expectedSha));
            JsonNode root=mapper.readTree(bytes);
            boolean completeContext=text(root,"schemaVersion").equals("zoop-briefing-impact-reviews-2");
            check(completeContext || text(root,"schemaVersion").equals("zoop-briefing-impact-reviews-1"));
            if (completeContext) {
                check(text(root,"citationPolicy").equals("complete-source-paragraph-1"));
                check(text(root,"previousManifestSha256").matches("[a-f0-9]{64}"));
            }
            check(text(root,"sourceKind").equals("actual") && text(root,"executionMode").equals("live")
                    && text(root,"recordingKind").equals("provider"));
            check(text(root,"inputScope").equals("preserved_quote_context"));
            check(text(root,"generationModel").equals("gpt-6-luna") && text(root,"verifierModel").equals("jev-1.14.0"));
            check(root.path("reviews").isArray());
            JsonNode chosen=null;
            for (JsonNode row:root.path("reviews")) if (roundId.equals(row.path("basis").path("roundId").asString())
                    && eventId.equals(row.path("basis").path("eventId").asString())) {
                check(chosen==null); chosen=row;
            }
            if (chosen==null) return new BriefingImpacts(roundId,eventId,round.graphVersion(),round.windowTo(),
                    "unavailable","historical_assessment_not_recorded",List.of(),metadata);
            var basis=chosen.path("basis");
            check(text(basis,"dataAsOf").equals(round.windowTo().toString()));
            check(Canonical.digest(basis).equals(text(chosen,"inputDigest")));
            String publication=jdbc.queryForObject("SELECT payload_sha256 FROM briefing_rounds WHERE id=?",String.class,roundId);
            check(Objects.equals(publication,text(basis,"publicationSha256")));
            // Also checks current source/document permissions and the immutable detail/source bindings.
            var detail=briefings.getItem(roundId,eventId,requestId);
            check(basis.path("evidence").equals(detail.path("evidence")));
            JsonNode selected=null;
            for (JsonNode item:round.payload().path("items")) if (eventId.equals(item.path("eventId").asString())) selected=item;
            check(selected!=null);
            var actualCompanies=mapper.createArrayNode();
            for (JsonNode company:selected.path("companies")) actualCompanies.addObject()
                    .put("id",text(company,"id")).put("name",text(company,"name"));
            check(actualCompanies.equals(basis.path("companies")));
            Set<String> proofStages=new HashSet<>();
            check(chosen.path("proofs").isArray() && chosen.path("proofs").size()<=4);
            for (JsonNode proof:chosen.path("proofs")) {
                String relative=text(proof,"path");
                check(relative.startsWith("receipts/") && !relative.contains("..") && !Path.of(relative).isAbsolute());
                byte[] receiptBytes=read(manifest.getParent().resolve(relative),2_000_000);
                check(Canonical.sha256(receiptBytes).equals(text(proof,"sha256"))
                        && receiptBytes.length==proof.path("bytes").asLong());
                var receipt=mapper.readTree(receiptBytes);
                check(text(receipt,"format").equals("zoop-live-receipt-1"));
                String stage=text(receipt,"stage");
                check(Set.of("impact","verify-impact").contains(stage));
                check(receipt.path("http").path("status").asInt()==200);
                check(Canonical.sha256(text(receipt.path("http"),"bodyText"))
                        .equals(text(receipt.path("http"),"bodySha256")));
                String model=stage.equals("impact")?"gpt-6-luna":"jev-1.14.0";
                check(text(receipt.path("model"),"requested").equals(model));
                String reported=text(receipt.path("model"),"reported");
                check(reported.equals(model)||reported.startsWith(model+"-"));
                proofStages.add(stage);
            }
            check(proofStages.contains("impact"));
            if (completeContext) {
                var repair=chosen.path("citationRepair");
                check(text(repair,"policy").equals("complete-source-paragraph-1")
                        && text(repair,"generation").equals("reused")
                        && Set.of("reused","independent_recheck").contains(text(repair,"effects"))
                        && text(repair,"previousResultSha256").matches("[a-f0-9]{64}"));
            }
            Instant assessedAt=Instant.parse(text(chosen,"assessedAt"));
            check(!assessedAt.isBefore(round.publishedAt()) && !assessedAt.isAfter(clock.instant().plusSeconds(60)));
            List<CompanyImpact> companies=new ArrayList<>(); Set<String> seen=new HashSet<>();
            check(chosen.path("assessments").isArray());
            for (JsonNode assessment:chosen.path("assessments")) {
                String company=text(assessment,"companyId"),name=text(assessment,"companyName"),status=text(assessment,"status");
                check(seen.add(company)); boolean member=false;
                for (JsonNode c:actualCompanies) if (company.equals(c.path("id").asString()) && name.equals(c.path("name").asString())) member=true;
                check(member && Set.of("verified","not-proposed","no-evidence","verifier-reject","technical-reject").contains(status));
                List<EffectEvidence> quotes=new ArrayList<>();Set<String> quoteIds=new HashSet<>();
                List<FactEvidence> facts=new ArrayList<>();Set<String> factIds=new HashSet<>();
                if (completeContext) {
                    check(assessment.path("facts").isArray() && !assessment.path("facts").isEmpty()
                            && assessment.path("facts").size()<=16);
                    for (JsonNode q:assessment.path("facts")) {
                        check(!q.has("effect") && factIds.add(text(q,"id")));
                        facts.add(sourceQuote(q,basis,round.windowTo()));
                    }
                }
                String label=assessment.path("label").isNull()?null:text(assessment,"label");
                check(assessment.path("evidence").isArray());
                boolean positive=false,negative=false,uncertain=false;
                for (JsonNode q:assessment.path("evidence")) {
                    check(quoteIds.add(text(q,"id")));String effect=text(q,"effect");
                    check(Set.of("positive","negative","neutral","uncertain").contains(effect));
                    var fact=sourceQuote(q,basis,round.windowTo());
                    quotes.add(new EffectEvidence(fact.id(),effect,fact.quote(),fact.articleId(),fact.articleVersion(),
                            fact.title(),fact.url(),fact.publishedAt(),fact.start(),fact.end()));
                    positive|=effect.equals("positive");negative|=effect.equals("negative");uncertain|=effect.equals("uncertain");
                }
                if (status.equals("verified")) {
                    check(proofStages.contains("verify-impact") && !quotes.isEmpty());
                    String target=text(assessment,"targetVerdict");check(Set.of("supported","insufficient").contains(target));
                    String computed=uncertain||target.equals("insufficient")?"undetermined":positive&&negative?"mixed":positive?"positive":negative?"negative":"undetermined";
                    check(computed.equals(label));
                } else check(label==null && quotes.isEmpty());
                EvidencePlan plan=null;
                if (assessment.hasNonNull("evidencePlan")) {
                    check(plans!=null);plan=plans.read(assessment.path("evidencePlan"),basis,round.windowTo(),manifest.getParent(),company);
                }
                SupplementalReview supplement=null;
                if(assessment.hasNonNull("supplementalReview")) {
                    check(plan!=null && plan.research()!=null);
                    supplement=BriefingSupplementalReviewReader.read(assessment.path("supplementalReview"),chosen,assessment,
                            manifest.getParent(),company,text(selected,"title"),clock,mapper);
                }
                var row=new Assessment("review:"+text(chosen,"inputDigest")+":"+company,"review:"+eventId,status,label,
                        new Provenance("collected","live","provider"),List.copyOf(quotes),List.copyOf(facts),plan,supplement);
                companies.add(new CompanyImpact(company,name,status.equals("verified")?"available":"unavailable",
                        status.equals("verified")?null:"no_verified_assessment",List.of(row)));
            }
            check(seen.size()==actualCompanies.size());
            boolean available=companies.stream().anyMatch(c->c.status().equals("available"));
            return new BriefingImpacts(roundId,eventId,round.graphVersion(),round.windowTo(),available?"available":"unavailable",
                    available?null:"no_verified_assessment",List.copyOf(companies),metadata,
                    new ReviewContext("historical_reassessment",assessedAt,"preserved_quote_context","gpt-6-luna","jev-1.14.0",expectedSha,
                            completeContext?"complete-source-paragraph-1":null));
        } catch (CustomException error) { throw error;
        } catch (Exception invalid) { throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE); }
    }

    static FactEvidence sourceQuote(JsonNode q, JsonNode basis, Instant cutoff) {
        JsonNode source=null;
        for (JsonNode e:basis.path("evidence")) if (text(q,"sourceEvidenceId").equals(e.path("id").asString())) source=e;
        check(source!=null && text(q,"articleId").equals(text(source,"documentId"))
                && text(q,"articleVersion").equals(text(source,"documentVersion")));
        check(Objects.equals(q.path("title"),source.path("title")) && Objects.equals(q.path("url"),source.path("url"))
                && Objects.equals(q.path("publishedAt"),source.path("publishedAt")));
        var context=source.path("bodyContext");
        check(q.path("start").isIntegralNumber() && q.path("end").isIntegralNumber());
        int start=q.path("start").asInt(),end=q.path("end").asInt(),base=context.path("start").asInt();
        String body=text(context,"text"),quote=text(q,"quote");
        check(start>=base && end>start && end<=context.path("end").asInt());
        check(body.substring(body.offsetByCodePoints(0,start-base),body.offsetByCodePoints(0,end-base)).equals(quote));
        Instant published=Instant.parse(text(q,"publishedAt"));check(!published.isAfter(cutoff));
        return new FactEvidence(text(q,"id"),quote,text(q,"articleId"),text(q,"articleVersion"),
                text(q,"title"),text(q,"url"),published,start,end);
    }

    private static String text(JsonNode node,String field) {
        check(node.path(field).isString() && !node.path(field).asString().isBlank());return node.path(field).asString();
    }
    private static void check(boolean ok) { if (!ok) throw new IllegalArgumentException("historical_impact_invalid"); }
    private static byte[] read(Path path,int limit) throws Exception {
        check(path.isAbsolute() && path.normalize().equals(path));
        for (Path p=path;p!=null;p=p.getParent()) check(!Files.isSymbolicLink(p));
        check(Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS) && Files.size(path)<=limit);
        byte[] raw=Files.readAllBytes(path);check(raw.length<=limit);return raw;
    }
}
