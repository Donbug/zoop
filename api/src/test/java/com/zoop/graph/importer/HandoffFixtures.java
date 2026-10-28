package com.zoop.graph.importer;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Function;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.Text;
import com.zoop.document.DocumentImportException;
import com.zoop.document.importer.IngestionExporter;
import com.zoop.document.importer.Observation;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.VersionRow;
import com.zoop.document.service.InMemoryDocumentRegistry;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * A complete, synthetic and VALID handoff in the exact shape of {@code zoop-ai-handoff export}: one article whose text holds a
 * non-BMP emoji before the cited sentences (so UTF-16 and code point offsets differ), one issue, two companies, one INVOLVES
 * and one STRUCTURALLY_RELATED_TO relation with a validity basis. Every digest, id formula, count and reference is computed
 * the way the producer does, so the strict verifier accepts it; tests mutate copies to break exactly one rule. A real producer
 * export is covered separately by the resource fixtures under {@code graph-handoff/}.
 */
final class HandoffFixtures {
    static final JsonMapper JSON = JsonMapper.builder().build();
    static final String SOURCE = "synthetic-source";
    static final String HANDOFF_ID = "handoff-unit-1";
    static final String EVENT = "계약을 발표했다.";
    static final String GEO = "국내 시장이다.";
    static final String BASIS = "구조 근거 문장이다.";
    /** The second structural basis of a two-hop chain: a sentence no issue, mention or relation cites. */
    static final String BASIS2 = "두 번째 구조 근거 문장이다.";
    /** The emoji (two UTF-16 units, one code point) sits before every cited sentence. */
    static final String TEXT = "합성기업은 \uD83D\uDE00 " + EVENT + " " + GEO + " " + BASIS + " " + BASIS2;
    static final String ARTICLE_ID = "doc-" + "a".repeat(64);
    static final String ARTICLE_VERSION = "b".repeat(64);
    static final String RAW_VERSION = "c".repeat(64);
    static final String OBSERVED_AT = "2026-10-14T01:02:03.456789+00:00";
    static final String PUBLISHED_AT = "2026-10-08T09:00:00+09:00";
    static final String COMPANY_A = "SYNTH:000001";
    static final String COMPANY_B = "SYNTH:000002";
    /** The middle company of a two-hop chain: a public company, or a private path company, by {@link Shape}. */
    static final String COMPANY_M = "SYNTH:000003";
    static final String ISSUE = "issue:supply-2026q3";
    static final Observation SELECTOR = new Observation("round-1", SOURCE, 0, 0, ARTICLE_ID, RAW_VERSION, ARTICLE_VERSION);

    private HandoffFixtures() {
    }

    /**
     * Knobs that change the content of the handoff (and therefore its digests). {@code verdicts} adds an operator review of the
     * one mention: a REJECT/contradicted on its {@code eventTime} (citing the event sentence) and a HOLD/ambiguous on its
     * {@code period} (citing the structural basis sentence, which no mention cites), so the issue's headline {@code eventTime} and
     * {@code period} are withheld while the mention keeps both original values.
     */
    record Spec(String handoffId, String canonicalPin, String publishedAt, String precision, String eventTime,
            String eventPrecision, String validFrom, String validUntil, boolean utf16Offsets, boolean verdicts,
            boolean manualApproval, boolean live, boolean origin, Shape shape, boolean impact) {
        static Spec standard() {
            return new Spec(HANDOFF_ID, "4".repeat(64), PUBLISHED_AT, "datetime", "2026-09-30", "day", "2026-01-01",
                    "2026-12-31", false, false, false, false, false, Shape.ONE_HOP, false);
        }

        Spec withHandoffId(String value) {
            return new Spec(value, canonicalPin, publishedAt, precision, eventTime, eventPrecision, validFrom, validUntil,
                    utf16Offsets, verdicts, manualApproval, live, origin, shape, impact);
        }

        Spec withCanonicalPin(String value) {
            return new Spec(handoffId, value, publishedAt, precision, eventTime, eventPrecision, validFrom, validUntil,
                    utf16Offsets, verdicts, manualApproval, live, origin, shape, impact);
        }

        Spec withPublication(String value, String valuePrecision) {
            return new Spec(handoffId, canonicalPin, value, valuePrecision, eventTime, eventPrecision, validFrom, validUntil,
                    utf16Offsets, verdicts, manualApproval, live, origin, shape, impact);
        }

        Spec withEvent(String value, String valuePrecision) {
            return new Spec(handoffId, canonicalPin, publishedAt, precision, value, valuePrecision, validFrom, validUntil,
                    utf16Offsets, verdicts, manualApproval, live, origin, shape, impact);
        }

        Spec withValidity(String from, String until) {
            return new Spec(handoffId, canonicalPin, publishedAt, precision, eventTime, eventPrecision, from, until,
                    utf16Offsets, verdicts, manualApproval, live, origin, shape, impact);
        }

        Spec withUtf16Offsets() {
            return new Spec(handoffId, canonicalPin, publishedAt, precision, eventTime, eventPrecision, validFrom, validUntil,
                    true, verdicts, manualApproval, live, origin, shape, impact);
        }

        Spec withVerdicts() {
            return new Spec(handoffId, canonicalPin, publishedAt, precision, eventTime, eventPrecision, validFrom, validUntil,
                    utf16Offsets, true, manualApproval, live, origin, shape, impact);
        }

        /** The one S3 relation the edges rest on became eligible by an operator's final approval of a HOLD, not by the verifier. */
        Spec withManualApproval() {
            return new Spec(handoffId, canonicalPin, publishedAt, precision, eventTime, eventPrecision, validFrom, validUntil,
                    utf16Offsets, verdicts, true, live, origin, shape, impact);
        }

        /** Provider-recorded live provenance ({@code executionMode: live}, {@code recordingKind: provider}). */
        Spec withLive() {
            return new Spec(handoffId, canonicalPin, publishedAt, precision, eventTime, eventPrecision, validFrom, validUntil,
                    utf16Offsets, verdicts, manualApproval, true, origin, shape, impact);
        }

        /** The article's document version carries an operator-declared origin. */
        Spec withOrigin() {
            return new Spec(handoffId, canonicalPin, publishedAt, precision, eventTime, eventPrecision, validFrom, validUntil,
                    utf16Offsets, verdicts, manualApproval, live, true, shape, impact);
        }

        /** The shape of the one structural edge's company chain. */
        Spec withShape(Shape value) {
            return new Spec(handoffId, canonicalPin, publishedAt, precision, eventTime, eventPrecision, validFrom, validUntil,
                    utf16Offsets, verdicts, manualApproval, live, origin, value, impact);
        }

        /**
         * Every INVOLVES source relation has a {@code verified} positive impact whose one quote is the {@link #BASIS2} sentence: a
         * span no issue, mention, relation or structural basis of a one-hop world cites. Ignored under a manual approval, which
         * makes no impact call ({@code not-applicable}).
         */
        Spec withImpact() {
            return new Spec(handoffId, canonicalPin, publishedAt, precision, eventTime, eventPrecision, validFrom, validUntil,
                    utf16Offsets, verdicts, manualApproval, live, origin, shape, true);
        }
    }

    /**
     * The structural edge {@code issue -> COMPANY_B}: {@link #ONE_HOP} is the complete chain {@code [A, B]} on one basis;
     * {@link #TWO_HOP_PUBLIC} the complete chain {@code [A, M, B]} on two bases whose middle {@code M} is a PUBLIC company (so it
     * also needs an INVOLVES edge to be linked); {@link #TWO_HOP_PRIVATE} the same chain whose middle is a private
     * {@code pathCompanies} entry (never a public node); {@link #TWO_HOP_UNMAPPED} the two-basis edge whose middle company the
     * operator did not map, so its path is {@code unavailable}.
     */
    enum Shape {
        ONE_HOP, TWO_HOP_PUBLIC, TWO_HOP_PRIVATE, TWO_HOP_UNMAPPED;

        boolean twoHop() {
            return this != ONE_HOP;
        }
    }

    /** One built handoff: the nodes, the bytes the CLI would print and the request that pins them. */
    record Built(Spec spec, ObjectNode manifest, ObjectNode bundle, ObjectNode envelope, byte[] envelopeBytes,
            String manifestDigest, String bundleDigest, List<String> evidenceIds) {
        GraphHandoffRequest request() {
            return new GraphHandoffRequest(spec.handoffId(), manifestDigest, bundleDigest, "operator-a");
        }

        String versionId() {
            return HandoffSnapshotWriter.versionId(spec.handoffId());
        }
    }

    static Built build() {
        return build(Spec.standard());
    }

    static Built build(Spec spec) {
        String relationJob = "rel-1";
        String upstreamJob = "s2-1";
        String candidate = "rc-" + "2".repeat(64);
        String candidate2 = "rc-" + "9".repeat(64);
        String eventCandidate = "evc-" + "3".repeat(64);

        ObjectNode event = span(spec, EVENT);
        ObjectNode geo = span(spec, GEO);
        ObjectNode basis = span(spec, BASIS);
        ObjectNode basis2 = span(spec, BASIS2);
        List<ObjectNode> evidence = new ArrayList<>(List.of(event, geo, basis));
        boolean verifiedImpact = spec.impact() && !spec.manualApproval();
        if (spec.shape().twoHop() || verifiedImpact) {
            evidence.add(basis2);
        }
        evidence.sort((a, b) -> a.get("id").stringValue().compareTo(b.get("id").stringValue()));
        String eventId = event.get("id").stringValue();
        String geoId = geo.get("id").stringValue();
        String basisId = basis.get("id").stringValue();
        String basis2Id = basis2.get("id").stringValue();

        ObjectNode bundle = StrictJson.newObject();
        bundle.put("schemaVersion", HandoffBundleVerifier.BUNDLE_SCHEMA);
        bundle.put("handoffId", spec.handoffId());
        // manifestDigest is filled in below, once the manifest exists.
        ObjectNode provenance = bundle.putObject("provenance");
        provenance.put("declaredSourceKind", "synthetic");
        provenance.put("observedSourceKind", "synthetic");
        provenance.put("executionMode", spec.live() ? "live" : "replay");
        provenance.put("recordingKind", spec.live() ? "provider" : "authored-test");
        ObjectNode policy = bundle.putObject("policy");
        policy.put("version", HandoffBundleVerifier.POLICY);
        ObjectNode files = policy.putObject("files");
        files.put("bindings", "6".repeat(64));
        files.put("canonical", spec.canonicalPin());
        files.put("decisions", "5".repeat(64));
        policy.put("evidenceIdKind", HandoffBundleVerifier.EVIDENCE_KIND);
        policy.put("offsetUnit", HandoffBundleVerifier.OFFSET_UNIT);
        policy.put("geography", "operator-field-verdict");
        policy.put("structural", "manual-operator-review");
        policy.put("sequence", "s2-comparison-with-operator-decision");
        policy.put("sourceSupport", HandoffBundleVerifier.SOURCE_SUPPORT_POLICY);
        policy.put("impacts", HandoffBundleVerifier.IMPACTS_POLICY);
        policy.put("issueSummary", HandoffIssueSummary.POLICY);

        ObjectNode pin = StrictJson.newObject();
        pin.putObject("relation").put("jobId", relationJob).put("inputDigest", "f".repeat(64));
        ObjectNode upstreamPin = pin.putObject("upstream");
        upstreamPin.put("jobId", upstreamJob);
        upstreamPin.put("inputDigest", "d".repeat(64));
        upstreamPin.put("digest", "e".repeat(64));
        pin.put("reviewDigest", "1".repeat(64));

        ObjectNode source = bundle.putArray("sources").addObject();
        source.set("relation", pin.get("relation"));
        source.set("upstream", pin.get("upstream"));
        source.put("reviewDigest", "1".repeat(64));
        source.putObject("provenance").put("sourceKind", "synthetic").put("executionMode", spec.live() ? "live" : "replay")
                .put("recordingKind", spec.live() ? "provider" : "authored-test");
        ObjectNode policies = source.putObject("policies");
        for (String name : List.of("producer", "verifier", "impactProducer", "impactVerifier", "policy", "revalidationPolicy",
                "impactPolicy")) {
            policies.put(name, name + "-1");
        }
        ArrayNode used = source.putArray("reviewUsed");
        for (String usedCandidate : spec.shape().twoHop() ? List.of(candidate, candidate2) : List.of(candidate)) {
            ObjectNode usedEntry = used.addObject();
            usedEntry.put("relationCandidateId", usedCandidate);
            usedEntry.put("revision", 1);
            ObjectNode approvalBasis = usedEntry.putObject("approvalBasis");
            approvalBasis.put("kind", spec.manualApproval() ? HandoffBundleVerifier.OPERATOR_FINAL : HandoffBundleVerifier.AUTOMATIC);
            approvalBasis.put("revision", 1);
            if (spec.manualApproval()) {
                approvalBasis.put("reviewer", "reviewer-final");
            } else {
                approvalBasis.putNull("reviewer");
            }
            approvalBasis.put("decidedAt", VERIFIED_AT);
        }
        ObjectNode audit = source.putObject("audit");
        audit.put("s3Relations", 2);
        ObjectNode eligibility = audit.putObject("eligibility");
        eligibility.put("eligible", 2);
        eligibility.put("hold", 0);
        eligibility.put("reject", 0);
        eligibility.put("pending", 0);
        audit.put("reviewPending", 0);
        audit.put("impactCandidates", verifiedImpact ? (spec.shape() == Shape.TWO_HOP_PUBLIC ? 2 : 1) : 0);
        audit.putObject("eligibleNotPublicByType");

        List<String[]> publicCompanies = new ArrayList<>(List.of(new String[] {COMPANY_B, "co:b", "합성부품"},
                new String[] {COMPANY_A, "co:a", "합성기업"}));
        if (spec.shape() == Shape.TWO_HOP_PUBLIC) {
            publicCompanies.add(new String[] {COMPANY_M, "co:m", "합성중간"});
        }
        ArrayNode companies = bundle.putArray("companies");
        for (String[] company : publicCompanies) {
            companyNode(companies, company);
        }
        // The private support references of the complete two-hop path: catalogue companies that are never public nodes.
        ArrayNode pathCompanies = bundle.putArray("pathCompanies");
        if (spec.shape() == Shape.TWO_HOP_PRIVATE) {
            companyNode(pathCompanies, new String[] {COMPANY_M, "co:m", "합성중간"});
        }

        ObjectNode sourceEvent = StrictJson.newObject();
        sourceEvent.set("upstream", StrictJson.newObject().put("jobId", upstreamJob).put("inputDigest", "d".repeat(64)));
        sourceEvent.put("kind", "event-candidate");
        sourceEvent.put("ref", eventCandidate);
        sourceEvent.put("mentionId", "m-1");
        sourceEvent.put("documentId", ARTICLE_ID);
        sourceEvent.put("documentVersion", ARTICLE_VERSION);
        ObjectNode observation = sourceEvent.putObject("observation");
        observation.put("roundId", SELECTOR.roundId());
        observation.put("sourceId", SELECTOR.sourceId());
        observation.put("page", SELECTOR.page());
        observation.put("ordinal", SELECTOR.ordinal());
        observation.put("documentId", ARTICLE_ID);
        observation.put("rawVersion", RAW_VERSION);
        observation.put("documentVersion", ARTICLE_VERSION);

        ObjectNode issue = bundle.putArray("issues").addObject();
        issue.put("id", ISSUE);
        issue.put("canonicalId", "issue:supply");
        issue.put("title", "합성 공급 계약");
        issue.put("action", "공급 계약");
        issue.put("target", "배터리");
        // A withheld headline value is null (an event time then has unknown precision); the mention below keeps the original.
        if (spec.verdicts()) {
            issue.putNull("eventTime");
            issue.put("timePrecision", "unknown");
            issue.putNull("period");
        } else {
            issue.put("eventTime", spec.eventTime());
            issue.put("timePrecision", spec.eventPrecision());
            issue.put("period", "2026Q3");
        }
        issue.put("assertionStatus", "announced");
        ObjectNode geography = issue.putObject("geography");
        geography.put("value", "domestic");
        geography.put("decisionRef", "geo-1");
        geography.put("decisionVersion", "g1");
        geography.put("policyVersion", HandoffBundleVerifier.POLICY);
        geography.putArray("countries").add("KR");
        geography.put("verification", "operator-field-verdict");
        geography.putArray("evidenceIds").add(geoId);
        ObjectNode geographyBasis = sourceEvent.deepCopy();
        geographyBasis.putArray("countries").add("KR");
        geography.putArray("basis").add(geographyBasis);
        ArrayNode issueEvidence = issue.putArray("evidenceIds");
        for (String id : spec.verdicts() ? sorted(eventId, geoId, basisId) : sorted(eventId, geoId)) {
            issueEvidence.add(id);
        }
        issue.putArray("sourceEvents").add(sourceEvent);
        ObjectNode mention = issue.putArray("mentions").addObject();
        mention.put("documentId", ARTICLE_ID);
        mention.put("documentVersion", ARTICLE_VERSION);
        mention.put("mentionId", "m-1");
        mention.put("articleId", ARTICLE_ID);
        mention.put("articleVersion", ARTICLE_VERSION);
        mention.put("verification", "none");
        mention.put("title", "합성 공급 계약");
        mention.put("action", "공급 계약");
        mention.put("target", "배터리");
        mention.put("eventTime", spec.eventTime());
        mention.put("timePrecision", spec.eventPrecision());
        mention.put("period", "2026Q3");
        mention.put("assertionStatus", "announced");
        mention.put("background", false);
        ArrayNode participants = mention.putArray("participants");
        participants.addObject().put("sourceCompanyId", "s2-co-a").put("companyId", COMPANY_A).put("name", "합성기업")
                .put("role", "공급자");
        participants.addObject().put("sourceCompanyId", "s2-co-unlisted").putNull("companyId").put("name", "미등록 협력사")
                .put("role", "수요자");
        participants.addObject().putNull("sourceCompanyId").putNull("companyId").put("name", "이름만 있는 참가자")
                .put("role", "언급");
        mention.putArray("evidenceIds").add(eventId);
        issue.put("decisionRef", "issue-1");
        issue.putNull("representative");
        // One mention that every issue value copies: unanimous, each field's list is that one mention, no operator verdict (so nothing is
        // withheld and every headline value is the mention's own).
        ObjectNode provenanceOfIssue = issue.putObject("fieldProvenance");
        provenanceOfIssue.put("selection", "unanimous");
        provenanceOfIssue.put("verification", "none");
        ArrayNode withheld = provenanceOfIssue.putArray("withheld");
        ArrayNode verdicts = issue.putArray("fieldVerdicts");
        if (spec.verdicts()) {
            withheld.add("eventTime").add("period");
            verdicts.add(verdict("eventTime", spec.eventTime(), "REJECT", "contradicted", eventId));
            verdicts.add(verdict("period", "2026Q3", "HOLD", "ambiguous", basisId));
        }
        issue.set("sourceSupport", sourceSupport(spec.origin()));
        // A HOLD/REJECT verdict anywhere leaves exactly temporal-review-pending; otherwise no job was pinned: not-requested.
        issue.set("summary", unavailable(spec.verdicts() ? HandoffIssueSummary.TEMPORAL_PENDING : HandoffIssueSummary.NOT_REQUESTED));
        ObjectNode sameValue = provenanceOfIssue.putObject("sameValueMentions");
        for (String field : List.of("title", "action", "target", "eventTime", "period", "assertionStatus")) {
            ObjectNode reference = sameValue.putArray(field).addObject();
            reference.put("documentId", ARTICLE_ID);
            reference.put("documentVersion", ARTICLE_VERSION);
            reference.put("mentionId", "m-1");
        }

        ArrayNode relations = bundle.putArray("relations");
        List<ObjectNode> relationNodes = new ArrayList<>();
        // A participant of the issue: the standard chain starts at COMPANY_A; a PUBLIC middle is a participant too (it needs an
        // INVOLVES edge to be linked, as every public company does).
        for (String participant : spec.shape() == Shape.TWO_HOP_PUBLIC ? List.of(COMPANY_A, COMPANY_M) : List.of(COMPANY_A)) {
            ObjectNode involves = StrictJson.newObject();
            involves.put("id", edge(Map.of("type", "INVOLVES", "source", ISSUE, "target", participant)));
            involves.put("type", "INVOLVES");
            involves.put("source", ISSUE);
            involves.put("target", participant);
            involves.putNull("role");
            involves.put("assertionStatus", "announced");
            involves.putArray("evidenceIds").add(eventId);
            involves.putArray("basis");
            ObjectNode involvesProvenance = involves.putObject("provenance");
            involvesProvenance.put("origin", "s3-relation");
            involvesProvenance.put("s3SemanticValidation", spec.manualApproval() ? "manual-operator-final-approval"
                    : "independent-verifier-supported-all-claims");
            involves.putNull("decisionRef");
            involves.putArray("sourceRefs").add(ref("s3-relation", relationJob, candidate));
            involves.putNull("structuralPath");
            relationNodes.add(involves);
        }

        String relationKey = "7".repeat(64);
        List<String> relationKeys = spec.shape().twoHop() ? List.of(relationKey, "9".repeat(64)) : List.of(relationKey);
        ObjectNode structuralPreimage = StrictJson.newObject();
        structuralPreimage.put("type", "STRUCTURALLY_RELATED_TO");
        structuralPreimage.put("source", ISSUE);
        structuralPreimage.put("target", COMPANY_B);
        ArrayNode preimageKeys = structuralPreimage.putArray("basis");
        relationKeys.forEach(preimageKeys::add);
        ObjectNode structural = StrictJson.newObject();
        structural.put("id", "edge-" + Canonical.digest(structuralPreimage));
        structural.put("type", "STRUCTURALLY_RELATED_TO");
        structural.put("source", ISSUE);
        structural.put("target", COMPANY_B);
        structural.putNull("role");
        structural.put("assertionStatus", "announced");
        structural.putArray("evidenceIds").add(eventId);
        ArrayNode basisArray = structural.putArray("basis");
        ArrayNode structuralRefs = structural.putArray("sourceRefs");
        for (int index = 0; index < relationKeys.size(); index++) {
            String basisCandidate = index == 0 ? candidate : candidate2;
            ObjectNode basisNode = basisArray.addObject();
            basisNode.putObject("sourceRelation").put("jobId", relationJob).put("relationCandidateId", basisCandidate);
            basisNode.put("relationKey", relationKeys.get(index));
            basisNode.put("relationType", "SUPPLIES");
            basisNode.put("validFrom", spec.validFrom());
            basisNode.put("validUntil", spec.validUntil());
            basisNode.putArray("countries").add("KR");
            basisNode.put("verifiedAt", VERIFIED_AT);
            basisNode.putArray("sourceArticles").addObject().put("articleId", ARTICLE_ID).put("articleVersion", ARTICLE_VERSION);
            basisNode.putArray("evidenceIds").add(index == 0 ? basisId : basis2Id);
            // The operator's S3 text as it stands: scope text, never an entity id.
            basisNode.put("businessScope", index == 0 ? "부품 공급 계약" : "소재 공급 계약");
            basisNode.put("productScope", index == 0 ? "배터리" : null);
            structuralRefs.add(ref("s3-relation", relationJob, basisCandidate));
        }
        ObjectNode path = structural.putObject("structuralPath");
        switch (spec.shape()) {
            case ONE_HOP -> completePath(path, List.of(COMPANY_A, COMPANY_B), COMPANY_B);
            case TWO_HOP_PUBLIC, TWO_HOP_PRIVATE -> completePath(path, List.of(COMPANY_A, COMPANY_M, COMPANY_B), COMPANY_M,
                    COMPANY_B);
            case TWO_HOP_UNMAPPED -> {
                path.put("status", "unavailable");
                path.put("reason", HandoffBundleVerifier.UNMAPPED_MIDDLE);
            }
        }
        ObjectNode structuralProvenance = structural.putObject("provenance");
        structuralProvenance.put("origin", "manual-operator-review");
        structuralProvenance.put("s3SemanticValidation", "none");
        structuralProvenance.put("status", "operator-asserted");
        structuralProvenance.put("reviewer", "reviewer-a");
        structuralProvenance.put("decisionRef", "applic-1");
        structuralProvenance.put("decisionVersion", "v1");
        structuralProvenance.put("bindingDigest", "8".repeat(64));
        structuralProvenance.put("basisEligibility", spec.manualApproval() ? "s3-operator-final-approval"
                : "s3-independent-verifier-supported-all-claims");
        structural.put("decisionRef", "applic-1");
        relationNodes.add(structural);
        relationNodes.sort((a, b) -> {
            int type = a.get("type").stringValue().compareTo(b.get("type").stringValue());
            return type != 0 ? type : a.get("id").stringValue().compareTo(b.get("id").stringValue());
        });
        relationNodes.forEach(relations::add);
        // One row per S3 relation behind an INVOLVES edge (never aggregated per edge), sorted by (edgeId, jobId, relationCandidateId).
        List<ObjectNode> impactRows = new ArrayList<>();
        for (ObjectNode relationNode : relationNodes) {
            if ("INVOLVES".equals(relationNode.get("type").stringValue())) {
                impactRows.add(impactRow(relationNode.get("id").stringValue(), relationNode.get("target").stringValue(),
                        relationJob, candidate, spec, basis2Id));
            }
        }
        impactRows.sort((a, b) -> a.get("edgeId").stringValue().compareTo(b.get("edgeId").stringValue()));
        ArrayNode impacts = bundle.putArray("impacts");
        impactRows.forEach(impacts::add);

        ArrayNode evidenceNodes = bundle.putArray("evidence");
        evidence.forEach(evidenceNodes::add);

        ObjectNode article = bundle.putArray("articles").addObject();
        article.put("articleId", ARTICLE_ID);
        article.put("articleVersion", ARTICLE_VERSION);
        article.put("documentId", ARTICLE_ID);
        article.put("documentVersion", ARTICLE_VERSION);
        article.put("rawVersion", RAW_VERSION);
        article.put("title", "합성 제목");
        article.put("url", "https://example.invalid/a");
        article.put("publishedAt", spec.publishedAt());
        article.put("publicationPrecision", spec.precision());
        article.put("textSha256", Canonical.sha256(TEXT));
        if (spec.origin()) {
            article.set("origin", origin());
        } else {
            article.putNull("origin");
        }
        ObjectNode observed = article.putArray("observations").addObject();
        observed.put("roundId", SELECTOR.roundId());
        observed.put("sourceId", SELECTOR.sourceId());
        observed.put("page", SELECTOR.page());
        observed.put("ordinal", SELECTOR.ordinal());
        observed.put("observedAt", OBSERVED_AT);
        observed.putObject("grant").put("grantId", "operator-grant").put("revision", "rights-1");

        ObjectNode exclusions = bundle.putObject("exclusions");
        exclusions.putObject("counts");
        exclusions.putArray("items");
        ObjectNode counts = bundle.putObject("counts");
        counts.put("companies", spec.shape() == Shape.TWO_HOP_PUBLIC ? 3 : 2);
        counts.put("pathCompanies", spec.shape() == Shape.TWO_HOP_PRIVATE ? 1 : 0);
        counts.put("issues", 1);
        ObjectNode relationCounts = counts.putObject("relations");
        relationCounts.put("INVOLVES", spec.shape() == Shape.TWO_HOP_PUBLIC ? 2 : 1);
        relationCounts.put("STRUCTURALLY_RELATED_TO", 1);
        relationCounts.put("FOLLOWS", 0);
        counts.put("evidence", spec.shape().twoHop() || verifiedImpact ? 4 : 3);
        counts.put("articles", 1);
        counts.put("exclusions", 0);
        counts.put("impacts", impactRows.size());
        ObjectNode checks = bundle.putObject("checks");
        HandoffBundleVerifier.PRODUCER_CHECKS.forEach(checks.putArray("producerConfirmed")::add);
        HandoffBundleVerifier.APP_IMPORT_PENDING.forEach(checks.putArray("appImportPending")::add);
        ObjectNode readiness = bundle.putObject("readiness");
        readiness.put("app", "import-pending");
        readiness.put("evidenceRegistration", "not-registered");
        readiness.put("publicActivation", "none");
        readiness.put("graphDb", "none");

        ObjectNode manifest = StrictJson.newObject();
        manifest.put("schemaVersion", HandoffBundleVerifier.MANIFEST_SCHEMA);
        manifest.put("handoffId", spec.handoffId());
        manifest.put("sourceKind", "synthetic");
        manifest.put("policyVersion", HandoffBundleVerifier.POLICY);
        ObjectNode manifestSource = manifest.putArray("sources").addObject();
        manifestSource.set("relation", pin.get("relation"));
        manifestSource.set("upstream", pin.get("upstream"));
        manifestSource.put("reviewDigest", "1".repeat(64));
        manifest.set("files", files.deepCopy());
        String manifestDigest = Canonical.digest(manifest);
        bundle.put("manifestDigest", manifestDigest);
        ObjectNode digests = bundle.putObject("digests");
        digests.put("content", HandoffBundleVerifier.contentDigest(bundle));

        byte[] bundleBytes = Canonical.bytes(bundle);
        String bundleDigest = Canonical.sha256(bundleBytes);
        ObjectNode receipt = StrictJson.newObject();
        receipt.put("handoffId", spec.handoffId());
        receipt.put("manifestDigest", manifestDigest);
        receipt.put("bundleSchema", HandoffBundleVerifier.BUNDLE_SCHEMA);
        receipt.put("bundleDigest", bundleDigest);
        receipt.put("contentDigest", digests.get("content").stringValue());
        receipt.put("bundleBytes", bundleBytes.length);
        receipt.set("provenance", provenance.deepCopy());
        ArrayNode receiptSources = receipt.putArray("sources");
        ObjectNode receiptSource = receiptSources.addObject();
        receiptSource.set("relation", pin.get("relation"));
        receiptSource.set("upstream", pin.get("upstream"));
        receiptSource.put("reviewDigest", "1".repeat(64));
        receipt.set("files", files.deepCopy());
        receipt.set("counts", counts.deepCopy());
        receipt.putObject("exclusionCodes");
        receipt.set("checks", checks.deepCopy());
        receipt.put("frozenAt", "2026-10-14T00:00:00+00:00");

        ObjectNode envelope = StrictJson.newObject();
        envelope.put("schemaVersion", ProcessHandoffExporter.SCHEMA_VERSION);
        envelope.put("handoffId", spec.handoffId());
        envelope.put("state", "ready");
        envelope.put("publication", "not-published");
        envelope.put("next", "export");
        envelope.putNull("failure");
        envelope.set("receipt", receipt);
        ObjectNode attempt = envelope.putArray("attempts").addObject();
        attempt.put("n", 1);
        attempt.put("kind", "freeze");
        attempt.put("outcome", "written");
        attempt.putNull("code");
        envelope.putObject("usage").put("providerCalls", 0).put("modelCalls", 0);
        ObjectNode delivery = envelope.putObject("delivery");
        delivery.put("status", "current");
        delivery.put("checkedAt", "2026-10-17T00:00:00+00:00");
        delivery.put("reviewDigestMatches", true);
        ArrayNode deliveryChecks = delivery.putArray("checks");
        for (String check : List.of("operator_files_equal_manifest_pins", "s3_authority_and_s2_upstream_pin_current",
                "used_review_revisions_unchanged", "content_digest_rebuilt_equal")) {
            deliveryChecks.add(check);
        }
        envelope.set("manifest", manifest);
        envelope.set("bundle", bundle);
        return new Built(spec, manifest, bundle, envelope, Canonical.bytes(envelope), manifestDigest, bundleDigest,
                evidence.stream().map(node -> node.get("id").stringValue()).toList());
    }

    /** The envelope bytes after {@code change} was applied to a copy; pins are NOT recomputed. */
    static byte[] envelopeAfter(Built built, java.util.function.Consumer<ObjectNode> change) {
        ObjectNode copy = built.envelope().deepCopy();
        change.accept(copy);
        return Canonical.bytes(copy);
    }

    /**
     * The handoff after {@code change} was applied to a copy of its BUNDLE, with the content digest, the bundle digest and the
     * producer's receipt recomputed: the strict verifier sees a self-consistent bundle (the manifest is unchanged), so only a rule
     * about the mutated content can refuse it. {@code change} must not alter the counts, the sources or the provenance.
     */
    static Built repinned(Built built, java.util.function.Consumer<ObjectNode> change) {
        ObjectNode envelope = built.envelope().deepCopy();
        ObjectNode bundle = (ObjectNode) envelope.get("bundle");
        change.accept(bundle);
        ((ObjectNode) bundle.get("digests")).put("content", HandoffBundleVerifier.contentDigest(bundle));
        byte[] bundleBytes = Canonical.bytes(bundle);
        String bundleDigest = Canonical.sha256(bundleBytes);
        ObjectNode receipt = (ObjectNode) envelope.get("receipt");
        receipt.put("bundleDigest", bundleDigest);
        receipt.put("contentDigest", bundle.get("digests").get("content").stringValue());
        receipt.put("bundleBytes", bundleBytes.length);
        return new Built(built.spec(), built.manifest(), bundle, envelope, Canonical.bytes(envelope), built.manifestDigest(),
                bundleDigest, built.evidenceIds());
    }

    // ---------------------------------------------------------------------------------------------- evidence -----------

    /** An evidence node for one cited sentence: offsets in code points (or, for a negative test, in UTF-16 units). */
    private static ObjectNode span(Spec spec, String quote) {
        int index = TEXT.indexOf(quote);
        int start = spec.utf16Offsets() ? index : TEXT.codePointCount(0, index);
        int end = spec.utf16Offsets() ? index + quote.length() : start + quote.codePointCount(0, quote.length());
        ObjectNode node = StrictJson.newObject();
        node.put("id", HandoffBundleVerifier.appEvidenceId(ARTICLE_ID, ARTICLE_VERSION, start, end));
        node.put("kind", HandoffBundleVerifier.EVIDENCE_KIND);
        node.put("articleId", ARTICLE_ID);
        node.put("articleVersion", ARTICLE_VERSION);
        node.put("start", start);
        node.put("end", end);
        node.put("offsetUnit", HandoffBundleVerifier.OFFSET_UNIT);
        node.put("quoteSha256", Canonical.sha256(quote));
        node.putArray("rawLocatorIds").add("loc-1");
        ObjectNode source = node.putObject("source");
        source.put("documentId", ARTICLE_ID);
        source.put("documentVersion", ARTICLE_VERSION);
        source.put("rawVersion", RAW_VERSION);
        source.put("textArtifactId", "text-" + ARTICLE_VERSION);
        ArrayNode preimage = StrictJson.newArray();
        preimage.add(ARTICLE_VERSION);
        preimage.add(start);
        preimage.add(end);
        source.put("sourceEvidenceId", "ev-" + Canonical.digest(preimage).substring(0, 32));
        source.put("inputKind", "body");
        return node;
    }

    /**
     * One operator field verdict of the standard mention, in the closed bundle shape ({@code evidenceIds} instead of spans).
     * SYNTHETIC: it names no real reviewer and no real review.
     */
    static ObjectNode verdict(String field, String value, String decision, String reason, String... evidenceIds) {
        ObjectNode node = StrictJson.newObject();
        node.put("documentId", ARTICLE_ID);
        node.put("documentVersion", ARTICLE_VERSION);
        node.put("mentionId", "m-1");
        node.put("field", field);
        node.put("value", value);
        node.put("decision", decision);
        node.put("reasonCode", reason);
        ArrayNode ids = node.putArray("evidenceIds");
        for (String id : sorted(evidenceIds)) {
            ids.add(id);
        }
        node.put("verification", "operator-field-verdict");
        node.put("reviewer", "reviewer-a");
        node.put("decisionRef", "fverdict-1:" + field);
        node.put("decisionVersion", "fv1");
        return node;
    }

    /**
     * The impact row of one INVOLVES source relation in the closed 13-key shape: {@code not-applicable} for an operator's final
     * approval (no impact call), {@code verified} (positive, one quote effect, {@code supported}) for {@link Spec#withImpact()}, and
     * otherwise {@code not-proposed} (the automatic relation completed without an on-target candidate). SYNTHETIC: a replay.
     */
    static ObjectNode impactRow(String edgeId, String company, String jobId, String relationCandidateId, Spec spec,
            String quoteEvidenceId) {
        ObjectNode row = StrictJson.newObject();
        row.put("edgeId", edgeId);
        row.put("issueId", ISSUE);
        row.put("companyId", company);
        row.putObject("sourceRelation").put("jobId", jobId).put("relationCandidateId", relationCandidateId);
        boolean verified = spec.impact() && !spec.manualApproval();
        row.put("status", spec.manualApproval() ? "not-applicable" : verified ? "verified" : "not-proposed");
        row.putNull("code");
        if (verified) {
            row.put("impactCandidateId", "ic-" + Canonical.sha256(company));
            row.put("label", "positive");
            row.put("targetVerdict", "supported");
            ObjectNode effects = row.putObject("effects");
            effects.putArray("positive").add(quoteEvidenceId);
            effects.putArray("negative");
            effects.putArray("neutral");
            effects.putArray("uncertain");
            row.put("verifier", "called");
            row.put("verifierRequestDigest", Canonical.sha256("verify-impact:" + company));
            ObjectNode proposal = row.putObject("proposal");
            proposal.put("direction", "positive");
            proposal.put("reason", "합성 영향: 두 번째 구조 근거 문장이 대상 회사의 긍정적 효과를 보인다.");
            proposal.putNull("limitations");
            proposal.put("verification", "none");
        } else {
            row.putNull("impactCandidateId");
            row.putNull("label");
            row.putNull("targetVerdict");
            row.putNull("effects");
            row.put("verifier", "not-called");
            row.putNull("verifierRequestDigest");
            row.putNull("proposal");
        }
        return row;
    }

    /** The time of the event that made the one S3 relation eligible: the structural basis's {@code verifiedAt} too. */
    static final String VERIFIED_AT = "2026-10-16T12:00:00.123456+00:00";

    /** The operator-declared origin of the standard article's document version (SYNTHETIC reviewer and decision). */
    static ObjectNode origin() {
        ObjectNode node = StrictJson.newObject();
        node.put("originId", "origin-wire-1");
        node.put("reviewer", "reviewer-a");
        node.put("decisionRef", "origin-1:" + ARTICLE_ID);
        node.put("decisionVersion", "o1");
        node.put("verification", "operator-declared-origin");
        return node;
    }

    /** The sourceSupport of the standard single-article issue: one article, with or without a declared origin. */
    static ObjectNode sourceSupport(boolean origin) {
        ObjectNode node = StrictJson.newObject();
        node.put("articleCount", 1);
        node.put("knownLineageCount", origin ? 1 : 0);
        ArrayNode unknown = node.putArray("unknownLineageArticles");
        if (origin) {
            node.put("independentSourceCount", 1);
        } else {
            unknown.add(ARTICLE_ID);
            node.putNull("independentSourceCount");
        }
        node.putArray("duplicateGroups");
        return node;
    }

    // ---------------------------------------------------------------------------------------------- issue summary ------------------------

    static final String SUMMARY_JOB = "summary-job-1";
    /** The one claim of the standard issue's available summary: a Hangul sentence that restates its one mention quote. */
    static final String SUMMARY_CLAIM = "합성기업이 계약을 발표했다.";

    /** An {@code unavailable} summary with {@code source: null}: {@code not-requested}, {@code temporal-review-pending} or {@code input-too-large}. */
    static ObjectNode unavailable(String code) {
        ObjectNode node = StrictJson.newObject();
        node.put("status", "unavailable");
        node.put("code", code);
        node.putNull("source");
        return node;
    }

    /**
     * The summary basis of the standard issue, built by hand from the bundle's own fields (not through the verifier's code): its
     * title, its ONE mention quote ({@code report}: the mention is not a background one) and that quote's article version.
     */
    static ObjectNode summaryBasis(ObjectNode bundle) {
        JsonNode issue = bundle.get("issues").get(0);
        JsonNode mention = issue.get("mentions").get(0);
        String quoteId = mention.get("evidenceIds").get(0).stringValue();
        JsonNode record = null;
        for (JsonNode candidate : bundle.get("evidence")) {
            if (candidate.get("id").stringValue().equals(quoteId)) {
                record = candidate;
            }
        }
        JsonNode article = bundle.get("articles").get(0);
        ObjectNode basis = StrictJson.newObject();
        basis.put("policy", HandoffIssueSummary.POLICY);
        basis.put("issueId", issue.get("id").stringValue());
        basis.put("title", issue.get("title").stringValue());
        ObjectNode quote = basis.putArray("quotes").addObject();
        quote.put("evidenceId", quoteId);
        quote.put("articleId", record.get("articleId").stringValue());
        quote.put("articleVersion", record.get("articleVersion").stringValue());
        quote.put("start", record.get("start").intValue());
        quote.put("end", record.get("end").intValue());
        quote.put("quoteSha256", record.get("quoteSha256").stringValue());
        quote.put("context", mention.get("background").booleanValue() ? "background" : "report");
        ObjectNode used = basis.putArray("articles").addObject();
        used.put("articleId", article.get("articleId").stringValue());
        used.put("articleVersion", article.get("articleVersion").stringValue());
        used.put("documentId", article.get("documentId").stringValue());
        used.put("documentVersion", article.get("documentVersion").stringValue());
        used.put("textSha256", article.get("textSha256").stringValue());
        return basis;
    }

    /** The {@code source} pin of a job result: its identity, the basis it was written for and the digest of {@code body} around them. */
    private static ObjectNode summarySource(ObjectNode body, String basisDigest) {
        ObjectNode preimage = StrictJson.newObject();
        preimage.put("jobId", SUMMARY_JOB);
        preimage.put("inputDigest", "9".repeat(64));
        preimage.put("basisDigest", basisDigest);
        preimage.set("result", body);
        ObjectNode source = StrictJson.newObject();
        source.put("jobId", SUMMARY_JOB);
        source.put("inputDigest", "9".repeat(64));
        source.put("resultDigest", Canonical.digest(preimage));
        source.put("basisDigest", basisDigest);
        return source;
    }

    /**
     * The AVAILABLE summary of the standard issue's one quote with every digest recomputed the way the producer does (basis digest,
     * {@code isr-} result version, result digest). The producer and verifier kinds pair with the bundle's execution mode: authored
     * replay with no model, or a provider with an independent verifier and named models.
     */
    static ObjectNode availableSummary(ObjectNode bundle) {
        boolean live = bundle.get("provenance").get("executionMode").stringValue().equals("live");
        ObjectNode basis = summaryBasis(bundle);
        String basisDigest = Canonical.digest(basis);
        String quoteId = basis.get("quotes").get(0).get("evidenceId").stringValue();
        ArrayNode claims = StrictJson.newArray();
        ObjectNode claim = claims.addObject();
        claim.put("claimId", "c1");
        claim.put("text", SUMMARY_CLAIM);
        claim.putArray("evidenceIds").add(quoteId);
        ObjectNode body = StrictJson.newObject();
        body.put("status", "available");
        body.put("text", SUMMARY_CLAIM);
        body.set("claims", claims.deepCopy());
        body.putArray("evidenceIds").add(quoteId);
        body.put("generatedAt", "2026-10-22T01:02:03+00:00");
        ObjectNode version = StrictJson.newObject();
        version.put("basisDigest", basisDigest);
        version.set("claims", claims);
        body.put("resultVersion", "isr-" + Canonical.digest(version));
        body.put("language", "ko");
        ObjectNode producer = body.putObject("producer");
        producer.put("kind", live ? "provider" : "authored-replay");
        if (live) {
            producer.put("model", "gpt-6-luna");
            producer.put("reasoningEffort", "high");
        } else {
            producer.putNull("model");
            producer.putNull("reasoningEffort");
        }
        producer.put("promptVersion", "zoop-issue-summary-prompt-1");
        producer.put("schemaDigest", "7".repeat(64));
        producer.put("runtimeIdentity", "8".repeat(64));
        ObjectNode verifier = body.putObject("verifier");
        verifier.put("kind", live ? "independent-verifier" : "authored-replay");
        if (live) {
            verifier.put("model", "jev-1.14.0");
        } else {
            verifier.putNull("model");
        }
        verifier.put("adapterIdentity", "a".repeat(64));
        verifier.put("requestDigest", "b".repeat(64));
        ObjectNode summary = body.deepCopy();
        summary.set("source", summarySource(body, basisDigest));
        return summary;
    }

    /** A job-coded {@code unavailable} summary ({@code producer-invalid}, {@code verifier-hold} or {@code verifier-reject}) of the standard issue. */
    static ObjectNode withheldSummary(ObjectNode bundle, String code) {
        String basisDigest = Canonical.digest(summaryBasis(bundle));
        ObjectNode body = StrictJson.newObject();
        body.put("status", "unavailable");
        body.put("code", code);
        ObjectNode summary = body.deepCopy();
        summary.set("source", summarySource(body, basisDigest));
        return summary;
    }

    /** The same handoff whose one issue carries the summary {@code make} builds from the built bundle (content digest and bundle pins recomputed). */
    static Built withSummary(Built built, Function<ObjectNode, ObjectNode> make) {
        return repinned(built, bundle -> ((ObjectNode) bundle.get("issues").get(0)).set("summary", make.apply(bundle)));
    }

    private static List<String> sorted(String... ids) {
        return java.util.Arrays.stream(ids).sorted().toList();
    }

    private static String edge(Map<String, String> preimage) {
        ObjectNode node = StrictJson.newObject();
        preimage.forEach(node::put);
        return "edge-" + Canonical.digest(node);
    }

    /** One closed company object {@code {id, canonicalId, label, decisionRef}}: {@code company} is {id, canonicalId, label}. */
    private static void companyNode(ArrayNode into, String[] company) {
        ObjectNode node = into.addObject();
        node.put("id", company[0]);
        node.put("canonicalId", company[1]);
        node.put("label", company[2]);
        node.put("decisionRef", "catalog-1");
    }

    /**
     * A complete structural path over {@code ids}; {@code suppliers[k]} is the supplier of link k (the other endpoint of the
     * adjacent pair is its customer), so the link direction is a fact of the S3 relation, not of the chain order.
     */
    private static void completePath(ObjectNode path, List<String> ids, String... suppliers) {
        path.put("status", "complete");
        ArrayNode chain = path.putArray("companyIds");
        ids.forEach(chain::add);
        ArrayNode links = path.putArray("links");
        for (int index = 0; index < suppliers.length; index++) {
            String from = ids.get(index);
            String to = ids.get(index + 1);
            links.addObject().put("supplierCompanyId", suppliers[index]).put("customerCompanyId",
                    suppliers[index].equals(from) ? to : from);
        }
    }

    private static ObjectNode ref(String kind, String jobId, String id) {
        ObjectNode node = StrictJson.newObject();
        node.put("kind", kind);
        node.put("jobId", jobId);
        node.put("id", id);
        return node;
    }

    // ---------------------------------------------------------------------------------------------- the app side --------

    /** The app's registered article, version, text artifact and text file for {@link #TEXT}. */
    static void seedApp(ArtifactFileStore store, InMemoryDocumentRegistry registry, String text) throws IOException {
        seedApp(store, registry, text, "합성 제목", "available");
    }

    /** The same with an explicit stored text, version title and article access status (to build app-side mismatches). */
    static void seedApp(ArtifactFileStore store, InMemoryDocumentRegistry registry, String text, String title, String access)
            throws IOException {
        seedApp(store, registry, text, title, access, Instant.parse("2026-10-08T00:00:00Z"), "datetime");
    }

    /** The same with the version's stored publication time and precision ({@code null} and {@code unknown} for no time). */
    static void seedApp(ArtifactFileStore store, InMemoryDocumentRegistry registry, String text, String title, String access,
            Instant publishedAt, String precision) throws IOException {
        byte[] utf8 = text.getBytes(StandardCharsets.UTF_8);
        String artifactId = "text-" + ARTICLE_VERSION;
        try (ArtifactFileStore.Session session = store.open()) {
            ArtifactFileStore.StoredFile file = session.put("extracted_text", artifactId + ".txt", utf8);
            registry.insertArtifactIfAbsent(new ArtifactRow(artifactId, "extracted_text", file.uri(), file.sha256(),
                    file.bytes(), "text/plain; charset=utf-8", Instant.parse("2026-10-14T01:00:00Z")));
        }
        registry.seedArticle(ARTICLE_ID, "news", SOURCE, ARTICLE_VERSION, access);
        registry.insertVersionIfAbsent(new VersionRow(ARTICLE_ID, ARTICLE_VERSION, title, null,
                "https://example.invalid/a", publishedAt, null, precision, null, artifactId,
                Instant.parse("2026-10-14T01:02:03.456789Z")));
    }

    // ---------------------------------------------------------------------------------------------- the CLIs ------------

    /** The S2-1 export of {@link #SELECTOR} for {@code text}, in the shape {@code zoop-ai-ingest export} prints. */
    static byte[] ingestionExport(Observation selector, String text, String title, String url, String publishedAt,
            String grantId, String grantRevision) {
        ObjectNode root = JSON.createObjectNode();
        root.put("schemaVersion", "zoop-ingestion-s2-1");
        ObjectNode observation = root.putObject("observation");
        observation.put("roundId", selector.roundId());
        observation.put("sourceId", selector.sourceId());
        observation.put("page", selector.page());
        observation.put("ordinal", selector.ordinal());
        observation.put("pageId", "page-0");
        observation.put("observedAt", OBSERVED_AT);
        observation.put("documentId", selector.documentId());
        observation.put("rawVersion", selector.rawVersion());
        observation.put("documentVersion", selector.documentVersion());
        observation.put("url", url);
        observation.put("title", title);
        observation.put("publishedAt", publishedAt);
        observation.putNull("modifiedAt");
        observation.putNull("sourceRevision");
        observation.put("mediaType", "text/html");
        ObjectNode grant = root.putObject("grant");
        grant.put("grantId", grantId);
        grant.put("revision", grantRevision);
        ObjectNode document = root.putObject("document");
        document.put("documentId", selector.documentId());
        document.put("documentVersion", selector.documentVersion());
        document.put("sourceId", selector.sourceId());
        document.put("textArtifactId", "text-" + selector.documentVersion());
        document.put("inputKind", "body");
        document.put("cleanerVersion", "exact-copy-1");
        document.put("text", text);
        document.put("sourceHash", Canonical.sha256(Text.pythonJsonString(text)));
        ObjectNode locator = document.putArray("rawLocators").addObject();
        locator.put("locatorId", "loc-1");
        locator.put("start", 0);
        locator.put("end", Text.codePoints(text));
        root.putObject("locatorMetadata").put("rawHash", "9".repeat(64));
        return Canonical.bytes(root);
    }

    /** The standard export of the standard article. */
    static byte[] standardIngestionExport() {
        return ingestionExport(SELECTOR, TEXT, "합성 제목", "https://example.invalid/a", PUBLISHED_AT, "operator-grant",
                "rights-1");
    }

    /**
     * The installed S2-1 CLI's stand-in: serves the standard export of the standard article, can refuse it, can start refusing
     * from the n-th call on (rights revoked while an import runs), and counts every call.
     */
    static final class FakeIngestion implements IngestionExporter {
        final AtomicInteger calls = new AtomicInteger();
        Function<Observation, byte[]> serve = observation -> standardIngestionExport();
        private int refuseFromCall = Integer.MAX_VALUE;
        private String refusalCode = "source_unauthorized";
        private int hookCall = Integer.MAX_VALUE;
        private Runnable hook = () -> { };

        /** Runs {@code action} when the n-th call arrives (before it is served): something changes while an import is running. */
        FakeIngestion before(int call, Runnable action) {
            this.hookCall = call;
            this.hook = action;
            return this;
        }

        FakeIngestion refuseAlways(String code) {
            return refuseFrom(1, code);
        }

        FakeIngestion refuseFrom(int call, String code) {
            this.refuseFromCall = call;
            this.refusalCode = code;
            return this;
        }

        @Override
        public byte[] export(Observation observation) {
            int call = calls.incrementAndGet();
            if (call == hookCall) {
                hook.run();
            }
            if (call >= refuseFromCall) {
                throw DocumentImportException.ingestionRefused(refusalCode);
            }
            return serve.apply(observation);
        }
    }

    /** The installed handoff CLI's stand-in: serves one envelope, or withholds it from the n-th call on. */
    static final class FakeHandoff implements HandoffExporter {
        final AtomicInteger calls = new AtomicInteger();
        byte[] envelope;
        private int withholdFromCall = Integer.MAX_VALUE;

        FakeHandoff(byte[] envelope) {
            this.envelope = envelope;
        }

        FakeHandoff withholdFrom(int call) {
            this.withholdFromCall = call;
            return this;
        }

        @Override
        public byte[] export(String handoffId) {
            int call = calls.incrementAndGet();
            if (call >= withholdFromCall) {
                throw GraphHandoffException.handoffWithheld("source_unauthorized");
            }
            return envelope;
        }
    }

    static JsonNode parse(byte[] bytes) {
        return JSON.readTree(bytes);
    }

    /** The impact FIELD names no public document may carry (an object key at any depth). */
    static final List<String> IMPACT_KEYS = List.of("impacts", "proposal", "effects", "verifierRequestDigest", "impactCandidateId",
            "targetVerdict", "sourceRelation");
    /** Status and policy literals that, as a string VALUE, only an impact row carries. */
    static final List<String> IMPACT_LITERALS = List.of("verifier-reject", "no-evidence", "technical-reject", "impact_precheck_rejected",
            "s3-independent-verifier-quote-effect");

    /**
     * What of an impact row a public JSON document carries, found structurally: a reserved field name at any depth, a string value that IS
     * a reserved literal, or one of the exact {@code protectedText} strings inside any string value. An identifier that merely contains a
     * reserved word (the handoff id {@code handoff-impacts-1} in {@code sourceBundleId}) is a legitimate value and never a leak.
     */
    static List<String> impactLeaks(String json, String... protectedText) {
        List<String> found = new ArrayList<>();
        collectImpactLeaks(JSON.readTree(json), found, protectedText);
        return found;
    }

    private static void collectImpactLeaks(JsonNode node, List<String> found, String[] protectedText) {
        if (node.isObject()) {
            for (String name : node.propertyNames()) {
                if (IMPACT_KEYS.contains(name)) {
                    found.add("key " + name);
                }
                collectImpactLeaks(node.get(name), found, protectedText);
            }
        } else if (node.isArray()) {
            for (JsonNode item : node.values()) {
                collectImpactLeaks(item, found, protectedText);
            }
        } else if (node.isString()) {
            String value = node.stringValue();
            if (IMPACT_LITERALS.contains(value)) {
                found.add("value " + value);
            }
            for (String text : protectedText) {
                if (value.contains(text)) {
                    found.add("text '" + text + "'");
                }
            }
        }
    }
}
