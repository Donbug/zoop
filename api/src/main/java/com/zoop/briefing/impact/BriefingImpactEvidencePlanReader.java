package com.zoop.briefing.impact;

import com.zoop.briefing.impact.BriefingImpacts.*;
import com.zoop.common.json.Canonical;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.evidence.service.EvidenceArtifactReader;
import org.springframework.stereotype.Component;
import org.springframework.beans.factory.annotation.Autowired;
import com.zoop.document.evidence.config.DocumentReadProperties;
import com.zoop.artifact.storage.ArtifactFileStore;
import tools.jackson.databind.JsonNode;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.time.*;
import java.nio.file.Path;
import java.util.*;

/** Source matching for editorial preparation, never a new or verified directional assessment.
 * Caller has already checked the publication and current getItem source permissions in this transaction. */
@Component
public class BriefingImpactEvidencePlanReader {
    private final DocumentRegistryRepository registry;
    private final EvidenceArtifactReader artifacts;
    private final Clock clock;
    @Autowired
    public BriefingImpactEvidencePlanReader(DocumentRegistryRepository registry, DocumentReadProperties properties, Clock clock) {
        this(registry,new EvidenceArtifactReader(properties.artifactRootPath()==null?null:ArtifactFileStore.at(properties.artifactRootPath())),clock);
    }
    public BriefingImpactEvidencePlanReader(DocumentRegistryRepository registry, EvidenceArtifactReader artifacts, Clock clock) {
        this.registry=registry;this.artifacts=artifacts;this.clock=clock;
    }
    public EvidencePlan read(JsonNode plan, JsonNode basis, Instant cutoff) throws Exception {
        return read(plan,basis,cutoff,null,null);
    }
    public EvidencePlan read(JsonNode plan, JsonNode basis, Instant cutoff, Path directory, String company) throws Exception {
        if (plan.isMissingNode() || plan.isNull()) return null;
        check(text(plan,"status").equals("prepared_not_evaluated") && !plan.has("label") && !plan.has("effect"));
        Instant prepared=Instant.parse(text(plan,"preparedAt"));
        check(!prepared.isBefore(cutoff) && !prepared.isAfter(clock.instant().plusSeconds(60)));
        check(plan.path("existingEvidence").isArray() && !plan.path("existingEvidence").isEmpty() && plan.path("existingEvidence").size()<=8);
        List<SupportingFact> facts=new ArrayList<>();Set<String> ids=new HashSet<>();
        for (JsonNode item:plan.path("existingEvidence")) {
            String scope=text(item,"scope");
            check(Set.of("direct","issuer_explanation","conditional_risk","background").contains(scope));
            var q=item.path("source");check(!q.has("effect") && !q.has("label") && ids.add(text(q,"id")));
            JsonNode bound=null;
            for (var source:basis.path("evidence")) if (text(q,"sourceEvidenceId").equals(source.path("id").asString())) bound=source;
            check(bound!=null && text(q,"articleId").equals(text(bound,"documentId")) && text(q,"articleVersion").equals(text(bound,"documentVersion")));
            for (String field:List.of("title","url","publishedAt","bodySha256")) check(q.path(field).equals(bound.path(field)));
            var version=registry.findVersion(text(q,"articleId"),text(q,"articleVersion")).orElseThrow();
            check(Objects.equals(version.title(),text(q,"title")) && Objects.equals(version.url(),text(q,"url"))
                    && Objects.equals(version.publishedAt(),Instant.parse(text(q,"publishedAt"))));
            check(version.publishedAt()!=null && !version.publishedAt().isAfter(cutoff));
            var artifact=registry.findArtifact(version.textArtifactId()).orElseThrow();
            check(artifact.sha256().equals(text(q,"bodySha256")) && artifact.bytes()<=1_000_000);
            byte[] bytes=artifacts.read(artifact);
            check(bytes.length==artifact.bytes() && Canonical.sha256(bytes).equals(artifact.sha256()));
            String body=StandardCharsets.UTF_8.newDecoder().decode(ByteBuffer.wrap(bytes)).toString();
            check(q.path("start").isIntegralNumber() && q.path("end").isIntegralNumber());
            int start=q.path("start").asInt(),end=q.path("end").asInt();String quote=text(q,"quote");
            check(start>=0 && end>start && quote.codePointCount(0,quote.length())==end-start && end-start<=2000);
            check(body.substring(body.offsetByCodePoints(0,start),body.offsetByCodePoints(0,end)).equals(quote));
            facts.add(new SupportingFact(scope,text(item,"note"),new FactEvidence(text(q,"id"),quote,text(q,"articleId"),
                    text(q,"articleVersion"),text(q,"title"),text(q,"url"),version.publishedAt(),start,end)));
        }
        check(plan.path("collectionNeeds").isArray() && !plan.path("collectionNeeds").isEmpty() && plan.path("collectionNeeds").size()<=16);
        List<CollectionNeed> needs=new ArrayList<>();
        for (var need:plan.path("collectionNeeds")) {
            String kind=text(need,"kind");check(Set.of("before_cutoff_gap","future_followup").contains(kind));
            needs.add(new CollectionNeed(kind,text(need,"what"),text(need,"why"),text(need,"preferredSource")));
        }
        var research=BriefingSupplementalEvidenceReader.read(plan.path("research"),basis,cutoff,directory,company,clock);
        return new EvidencePlan("prepared_not_evaluated",prepared,text(plan,"reason"),List.copyOf(facts),List.copyOf(needs),research);
    }
    private static String text(JsonNode node,String field) {
        check(node.path(field).isString() && !node.path(field).asString().isBlank() && node.path(field).asString().length()<=4000);
        return node.path(field).asString();
    }
    private static void check(boolean value) {if(!value)throw new IllegalArgumentException("invalid_evidence_preparation");}
}
