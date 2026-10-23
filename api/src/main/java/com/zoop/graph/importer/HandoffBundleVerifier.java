package com.zoop.graph.importer;

import java.time.DateTimeException;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.regex.Pattern;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.graph.importer.HandoffBundle.Approval;
import com.zoop.graph.importer.HandoffBundle.Article;
import com.zoop.graph.importer.HandoffBundle.Basis;
import com.zoop.graph.importer.HandoffBundle.Company;
import com.zoop.graph.importer.HandoffBundle.Evidence;
import com.zoop.graph.importer.HandoffBundle.Issue;
import com.zoop.graph.importer.HandoffBundle.ObservationPin;
import com.zoop.graph.importer.HandoffBundle.Origin;
import com.zoop.graph.importer.HandoffBundle.Relation;
import com.zoop.graph.importer.HandoffBundle.SourcePin;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * The strict, closed validator of a {@code zoop-graph-handoff-bundle-7} and of its frozen manifest: a Java port of the
 * producer's own {@code validate_bundle} ({@code ai/pipeline/.../handoff_contracts.py}), so the app never trusts a producer
 * claim it did not recompute. Every object has exactly the keys the producer writes, every value its type and pattern, every
 * reference is closed (articles, evidence, companies, issues, relations, source pins, review revisions), every id formula
 * ({@code ev-}, {@code edge-}) and count is recomputed and the content digest is rebuilt. Anything else is
 * {@link StrictJson.Malformed}: a damaged or hand-edited document is refused whole, never read partially.
 *
 * <p>The importer does not carry the producer's constants as its own policy: {@link #POLICY} is the one projection policy this
 * build can map, and a bundle under another policy version is refused instead of being read with these rules.
 */
final class HandoffBundleVerifier {
    static final String MANIFEST_SCHEMA = "zoop-ai-handoff-1";
    static final String BUNDLE_SCHEMA = "zoop-graph-handoff-bundle-7";
    static final String POLICY = "zoop-public-projection-policy-1";
    static final String EVIDENCE_KIND = "graph-body-span";
    static final String OFFSET_UNIT = "unicode_code_point";

    static final List<String> PUBLIC_TYPES = List.of("INVOLVES", "STRUCTURALLY_RELATED_TO", "FOLLOWS");
    static final List<String> PRODUCER_CHECKS = List.of("s3_authority_current", "s2_upstream_pinned", "review_state_pinned",
            "operator_files_pinned", "provenance_observed_equals_declared", "evidence_exact_resolved_against_source_text",
            "app_binding_text_digest_equals_source_text", "bundle_schema_and_closure_validated", "artifact_written_and_hashed");
    static final List<String> APP_IMPORT_PENDING = List.of("article_and_version_exist_in_app", "app_text_sha256_equals_binding",
            "app_text_span_hash_equals_evidence_quoteSha256", "article_title_url_publishedAt_equal_bundle",
            "company_ids_exist_in_app_catalog_with_equal_label", "evidence_rows_registered_in_app",
            "getEvidence_graph_evidence_path", "graph_version_row_and_activation", "asOf_policy");

    private static final Set<String> TIME_PRECISIONS = Set.of("year", "month", "day", "datetime", "unknown");
    private static final int MAX_SOURCES = 20;
    private static final int MAX_DECISIONS = 20_000;
    private static final int MAX_ISSUES = 2_000;
    private static final int MAX_RELATIONS = 10_000;
    private static final int MAX_EVIDENCE = 20_000;
    private static final int MAX_ARTICLES = 1_000;
    private static final int MAX_EXCLUSIONS = 20_000;

    private static final Pattern ID = Pattern.compile("[A-Za-z0-9._:-]{1,200}");
    private static final Pattern HASH = Pattern.compile("[a-f0-9]{64}");
    private static final Pattern RC = Pattern.compile("rc-[a-f0-9]{64}");
    private static final Pattern EVC = Pattern.compile("evc-[a-f0-9]{64}");
    private static final Pattern ARTICLE_ID = Pattern.compile("doc-[a-f0-9]{64}");
    private static final Pattern EVIDENCE_ID = Pattern.compile("ev-[a-f0-9]{64}");
    private static final Pattern SOURCE_EVIDENCE_ID = Pattern.compile("ev-[a-f0-9]{32}");
    private static final Pattern FOLLOWS_REF = Pattern.compile("evc-[a-f0-9]{64}>.+");
    private static final Pattern DAY = Pattern.compile("[0-9]{4}-[0-9]{2}-[0-9]{2}");

    private static final Set<String> SOURCE_EVENT_KEYS = Set.of("upstream", "kind", "ref", "mentionId", "documentId",
            "documentVersion", "observation");
    private static final Set<String> OBSERVATION_KEYS = Set.of("roundId", "sourceId", "page", "ordinal", "documentId",
            "rawVersion", "documentVersion");
    private static final Set<String> MENTION_KEYS = Set.of("documentId", "documentVersion", "mentionId", "articleId",
            "articleVersion", "verification", "title", "action", "target", "eventTime", "timePrecision", "period",
            "assertionStatus", "background", "participants", "evidenceIds");
    private static final Set<String> PARTICIPANT_KEYS = Set.of("sourceCompanyId", "companyId", "name", "role");
    /** The issue's wire field names whose original-mention agreement {@code fieldProvenance} records, in the producer's order. */
    private static final List<String> PROVENANCE_FIELDS = List.of("title", "action", "target", "eventTime", "period",
            "assertionStatus");
    /** The two fields an operator field verdict can judge, in the producer's (and the canonical) order. */
    private static final List<String> VERDICT_FIELDS = List.of("eventTime", "period");
    private static final Set<String> VERDICT_KEYS = Set.of("documentId", "documentVersion", "mentionId", "field", "value",
            "decision", "reasonCode", "evidenceIds", "verification", "reviewer", "decisionRef", "decisionVersion");
    private static final Set<String> MENTION_REF_KEYS = Set.of("documentId", "documentVersion", "mentionId");
    private static final Set<String> ASSERTION_STATUSES = Set.of("occurred", "announced", "planned", "forecast",
            "cancelled", "unknown");
    private static final int MAX_MENTIONS = 1_000;
    private static final int MAX_PARTICIPANTS = 1_000;
    private static final int MAX_VERDICTS = 2 * MAX_MENTIONS;
    private static final int MAX_VERDICT_EVIDENCE = 20;
    private static final Set<String> APPROVAL_KEYS = Set.of("kind", "revision", "reviewer", "decidedAt");
    private static final Set<String> ORIGIN_KEYS = Set.of("originId", "reviewer", "decisionRef", "decisionVersion",
            "verification");
    private static final Set<String> SUPPORT_KEYS = Set.of("articleCount", "knownLineageCount", "unknownLineageArticles",
            "independentSourceCount", "duplicateGroups");
    /** The eligibility of an S3 relation was decided by the independent verifier (no reviewer). */
    static final String AUTOMATIC = "automatic-verifier";
    /** The eligibility of an S3 relation was decided by a human's final approval of a HOLD: not a verifier verdict. */
    static final String OPERATOR_FINAL = "operator-final-approval";
    static final String SOURCE_SUPPORT_POLICY = "origin-or-exact-text-union";
    /** The only reason a structural path may be unavailable: a two-basis chain whose middle company the operator did not map. */
    static final String UNMAPPED_MIDDLE = "intermediate_company_unmapped";
    /** The longest business or product scope text of one structural basis, in Unicode code points. */
    private static final int MAX_SCOPE_CODE_POINTS = 500;
    /** The policy literal of the closed {@code impacts[]} collection: the independent verifier's per-quote effect, never a price claim. */
    static final String IMPACTS_POLICY = "s3-independent-verifier-quote-effect";
    private static final Set<String> IMPACT_KEYS = Set.of("edgeId", "issueId", "companyId", "sourceRelation",
            "impactCandidateId", "status", "code", "label", "targetVerdict", "effects", "verifier", "verifierRequestDigest",
            "proposal");
    private static final Set<String> PROPOSAL_KEYS = Set.of("direction", "reason", "limitations", "verification");
    private static final List<String> EFFECT_SIDES = List.of("positive", "negative", "neutral", "uncertain");
    private static final List<String> IMPACT_LABELS = List.of("positive", "negative", "mixed", "undetermined");
    private static final Pattern IMPACT_CANDIDATE = Pattern.compile("ic-[a-f0-9]{64}");
    /** The most evidence ids one verified impact row may list across its four effect sides. */
    private static final int MAX_IMPACT_EVIDENCE = 40;
    private static final int MAX_PROPOSAL_REASON_CODE_POINTS = 2_000;
    private static final int MAX_PROPOSAL_LIMITATIONS_CODE_POINTS = 1_000;

    private HandoffBundleVerifier() {
    }

    /** The frozen manifest, closed: the operator's pin of everything the handoff may consume. */
    record Manifest(String handoffId, String sourceKind, String policyVersion, Map<String, String> files,
            List<SourcePin> sources) {
        Manifest {
            files = Map.copyOf(files);
            sources = List.copyOf(sources);
        }
    }

    // ------------------------------------------------------------------------------------------------ manifest -----------

    static Manifest verifyManifest(JsonNode node) {
        Obj manifest = Obj.of(node).exactly(Set.of("schemaVersion", "handoffId", "sourceKind", "policyVersion", "sources",
                "files"));
        need(MANIFEST_SCHEMA.equals(manifest.string("schemaVersion")));
        String handoffId = text(manifest, "handoffId", ID);
        String sourceKind = manifest.string("sourceKind");
        need(sourceKind.equals("synthetic") || sourceKind.equals("actual"));
        String policyVersion = manifest.string("policyVersion");
        need(POLICY.equals(policyVersion));
        List<Obj> sourceNodes = manifest.objects("sources");
        need(sourceNodes.size() >= 1 && sourceNodes.size() <= MAX_SOURCES);
        List<SourcePin> pins = new ArrayList<>();
        Set<String> jobs = new HashSet<>();
        for (Obj source : sourceNodes) {
            source.exactly(Set.of("relation", "upstream", "reviewDigest"));
            Obj relation = source.object("relation").exactly(Set.of("jobId", "inputDigest"));
            Obj upstream = source.object("upstream").exactly(Set.of("jobId", "inputDigest", "digest"));
            SourcePin pin = new SourcePin(text(relation, "jobId", ID), text(relation, "inputDigest", HASH),
                    text(upstream, "jobId", ID), text(upstream, "inputDigest", HASH), text(upstream, "digest", HASH),
                    text(source, "reviewDigest", HASH));
            need(jobs.add(pin.relationJobId()));
            pins.add(pin);
        }
        Obj files = manifest.object("files").exactly(Set.of("canonical", "decisions", "bindings"));
        Map<String, String> fileHashes = new LinkedHashMap<>();
        for (String name : List.of("canonical", "decisions", "bindings")) {
            fileHashes.put(name, text(files, name, HASH));
        }
        return new Manifest(handoffId, sourceKind, policyVersion, fileHashes, pins);
    }

    // ------------------------------------------------------------------------------------------------ bundle ------------

    /** SHA-256 of the canonical JSON of the five public collections: the bundle's {@code digests.content}. */
    static String contentDigest(JsonNode bundle) {
        ObjectNode subset = StrictJson.newObject();
        for (String key : List.of("companies", "pathCompanies", "issues", "relations", "evidence", "articles", "impacts")) {
            subset.set(key, bundle.get(key));
        }
        return Canonical.digest(subset);
    }

    /** {@code ev-} + the digest of the graph-specific preimage: the producer's proposed id, adopted by the app as its rule. */
    static String appEvidenceId(String articleId, String articleVersion, int start, int end) {
        ObjectNode preimage = StrictJson.newObject();
        preimage.put("kind", EVIDENCE_KIND);
        preimage.put("articleId", articleId);
        preimage.put("articleVersion", articleVersion);
        preimage.put("start", start);
        preimage.put("end", end);
        return "ev-" + Canonical.digest(preimage);
    }

    static HandoffBundle verify(JsonNode node) {
        Obj bundle = Obj.of(node).exactly(Set.of("schemaVersion", "handoffId", "manifestDigest", "provenance", "policy",
                "sources", "companies", "pathCompanies", "issues", "relations", "evidence", "articles", "exclusions", "counts",
                "checks", "readiness", "digests", "impacts"));
        need(BUNDLE_SCHEMA.equals(bundle.string("schemaVersion")));
        String handoffId = text(bundle, "handoffId", ID);
        String manifestDigest = text(bundle, "manifestDigest", HASH);

        Obj producerProvenance = bundle.object("provenance").exactly(Set.of("declaredSourceKind", "observedSourceKind",
                "executionMode", "recordingKind"));
        String sourceKind = producerProvenance.string("declaredSourceKind");
        need(sourceKind.equals(producerProvenance.string("observedSourceKind"))
                && (sourceKind.equals("synthetic") || sourceKind.equals("actual")));
        String executionMode = producerProvenance.string("executionMode");
        String recordingKind = producerProvenance.string("recordingKind");
        // Live provider evidence and replayed authored fixtures are the only two truthful pairings; sourceKind is independent.
        need((executionMode.equals("replay") && recordingKind.equals("authored-test"))
                || (executionMode.equals("live") && recordingKind.equals("provider")));

        Obj policy = bundle.object("policy").exactly(Set.of("version", "files", "evidenceIdKind", "offsetUnit", "geography",
                "structural", "sequence", "sourceSupport", "impacts", "issueSummary"));
        String policyVersion = policy.string("version");
        need(POLICY.equals(policyVersion) && EVIDENCE_KIND.equals(policy.string("evidenceIdKind"))
                && OFFSET_UNIT.equals(policy.string("offsetUnit")));
        need("operator-field-verdict".equals(policy.string("geography")));
        need("manual-operator-review".equals(policy.string("structural")));
        need("s2-comparison-with-operator-decision".equals(policy.string("sequence")));
        need(SOURCE_SUPPORT_POLICY.equals(policy.string("sourceSupport")));
        need(IMPACTS_POLICY.equals(policy.string("impacts")));
        need(HandoffIssueSummary.POLICY.equals(policy.string("issueSummary")));
        Obj filesNode = policy.object("files").exactly(Set.of("canonical", "decisions", "bindings"));
        Map<String, String> files = new LinkedHashMap<>();
        for (String name : List.of("canonical", "decisions", "bindings")) {
            files.put(name, text(filesNode, name, HASH));
        }

        // sources -------------------------------------------------------------------------------------------------------
        List<Obj> sourceNodes = bundle.objects("sources");
        need(sourceNodes.size() >= 1 && sourceNodes.size() <= MAX_SOURCES);
        List<SourcePin> pins = new ArrayList<>();
        Set<String> jobs = new HashSet<>();
        Set<String> upstreams = new HashSet<>();
        Set<String> upstreamJobs = new HashSet<>();
        Map<String, Map<String, Approval>> usedReviews = new LinkedHashMap<>();
        for (Obj source : sourceNodes) {
            source.exactly(Set.of("relation", "upstream", "reviewDigest", "policies", "reviewUsed", "audit", "provenance"));
            Obj relation = source.object("relation").exactly(Set.of("jobId", "inputDigest"));
            String jobId = text(relation, "jobId", ID);
            String relationInput = text(relation, "inputDigest", HASH);
            Obj upstream = source.object("upstream").exactly(Set.of("jobId", "inputDigest", "digest"));
            String upstreamJob = text(upstream, "jobId", ID);
            String upstreamInput = text(upstream, "inputDigest", HASH);
            String upstreamDigest = text(upstream, "digest", HASH);
            String reviewDigest = text(source, "reviewDigest", HASH);
            // Every source must carry exactly the bundle's own provenance: a bundle never copies the first job's mode.
            Obj sourceProvenance = source.object("provenance").exactly(Set.of("sourceKind", "executionMode", "recordingKind"));
            need(sourceKind.equals(sourceProvenance.string("sourceKind"))
                    && executionMode.equals(sourceProvenance.string("executionMode"))
                    && recordingKind.equals(sourceProvenance.string("recordingKind")));
            Obj versions = source.object("policies").exactly(Set.of("producer", "verifier", "impactProducer",
                    "impactVerifier", "policy", "revalidationPolicy", "impactPolicy"));
            for (String name : versions.node().propertyNames()) {
                need(!versions.string(name).isEmpty());
            }
            JsonNode usedNodes = source.array("reviewUsed");
            need(usedNodes.size() <= MAX_RELATIONS);
            Map<String, Approval> used = new LinkedHashMap<>();
            String previousCandidate = null;
            for (JsonNode item : usedNodes.values()) {
                Obj use = Obj.of(item).exactly(Set.of("relationCandidateId", "revision", "approvalBasis"));
                String candidate = text(use, "relationCandidateId", RC);
                need(previousCandidate == null || compareCodePoints(previousCandidate, candidate) < 0);
                previousCandidate = candidate;
                int revision = use.count("revision");
                need(revision >= 1);
                used.put(candidate, approval(jobId, candidate, revision, use.object("approvalBasis")));
            }
            Obj audit = source.object("audit").exactly(Set.of("s3Relations", "eligibility", "reviewPending",
                    "impactCandidates", "eligibleNotPublicByType"));
            for (String name : List.of("s3Relations", "reviewPending", "impactCandidates")) {
                audit.count(name);
            }
            Obj eligibility = audit.object("eligibility").exactly(Set.of("eligible", "hold", "reject", "pending"));
            for (String name : List.of("eligible", "hold", "reject", "pending")) {
                eligibility.count(name);
            }
            Obj notPublic = audit.object("eligibleNotPublicByType");
            for (String type : notPublic.node().propertyNames()) {
                need(ID.matcher(type).matches());
                notPublic.count(type);
            }
            need(jobs.add(jobId));
            upstreams.add(pair(upstreamJob, upstreamInput));
            upstreamJobs.add(upstreamJob);
            usedReviews.put(jobId, used);
            pins.add(new SourcePin(jobId, relationInput, upstreamJob, upstreamInput, upstreamDigest, reviewDigest));
        }

        // evidence ------------------------------------------------------------------------------------------------------
        Map<String, Evidence> evidence = new LinkedHashMap<>();
        List<Obj> evidenceNodes = bundle.objects("evidence");
        need(evidenceNodes.size() <= MAX_EVIDENCE);
        for (Obj e : evidenceNodes) {
            e.exactly(Set.of("id", "kind", "articleId", "articleVersion", "start", "end", "offsetUnit", "quoteSha256",
                    "rawLocatorIds", "source"));
            String id = text(e, "id", EVIDENCE_ID);
            need(EVIDENCE_KIND.equals(e.string("kind")) && OFFSET_UNIT.equals(e.string("offsetUnit")));
            String articleId = text(e, "articleId", ARTICLE_ID);
            String articleVersion = text(e, "articleVersion", HASH);
            int start = e.count("start");
            int end = e.count("end");
            need(end >= 1 && end > start);
            String quoteSha256 = text(e, "quoteSha256", HASH);
            List<String> locators = strings(e, "rawLocatorIds", 1000);
            Obj source = e.object("source").exactly(Set.of("documentId", "documentVersion", "rawVersion", "textArtifactId",
                    "sourceEvidenceId", "inputKind"));
            String documentId = source.string("documentId");
            String documentVersion = text(source, "documentVersion", HASH);
            String rawVersion = text(source, "rawVersion", HASH);
            String textArtifactId = source.string("textArtifactId");
            String sourceEvidenceId = text(source, "sourceEvidenceId", SOURCE_EVIDENCE_ID);
            need("body".equals(source.string("inputKind")));
            need(id.equals(appEvidenceId(articleId, articleVersion, start, end)));
            need(!evidence.containsKey(id));
            evidence.put(id, new Evidence(id, articleId, articleVersion, start, end, quoteSha256, locators, documentId,
                    documentVersion, rawVersion, textArtifactId, sourceEvidenceId));
        }

        // articles ------------------------------------------------------------------------------------------------------
        Map<String, Article> articles = new LinkedHashMap<>();
        List<Obj> articleNodes = bundle.objects("articles");
        need(articleNodes.size() <= MAX_ARTICLES);
        for (Obj a : articleNodes) {
            a.exactly(Set.of("articleId", "articleVersion", "documentId", "documentVersion", "rawVersion", "title", "url",
                    "publishedAt", "publicationPrecision", "observations", "textSha256", "origin"));
            String articleId = text(a, "articleId", ARTICLE_ID);
            String articleVersion = text(a, "articleVersion", HASH);
            String documentId = a.string("documentId");
            String documentVersion = text(a, "documentVersion", HASH);
            String rawVersion = text(a, "rawVersion", HASH);
            String title = a.string("title");
            String url = a.string("url");
            String publishedAt = a.stringOrNull("publishedAt");
            String precision = a.string("publicationPrecision");
            need((precision.equals("datetime") && publishedAt != null) || (precision.equals("day") && publishedAt != null)
                    || (precision.equals("unknown") && publishedAt == null));
            need(!precision.equals("day") || DAY.matcher(publishedAt).matches());
            String textSha256 = text(a, "textSha256", HASH);
            Origin origin = a.isNull("origin") ? null : origin(a.object("origin"));
            List<Obj> observationNodes = a.objects("observations");
            need(observationNodes.size() >= 1 && observationNodes.size() <= 1000);
            List<ObservationPin> observations = new ArrayList<>();
            List<String> canonical = new ArrayList<>();
            for (Obj o : observationNodes) {
                o.exactly(Set.of("roundId", "sourceId", "page", "ordinal", "observedAt", "grant"));
                Obj grant = o.object("grant").exactly(Set.of("grantId", "revision"));
                observations.add(new ObservationPin(o.string("roundId"), o.string("sourceId"), o.count("page"),
                        o.count("ordinal"), o.string("observedAt"), grant.string("grantId"), grant.string("revision")));
                canonical.add(Canonical.write(o.node()));
            }
            need(sortedUnique(canonical));
            String key = articleKey(articleId, articleVersion);
            need(!articles.containsKey(key));
            articles.put(key, new Article(articleId, articleVersion, documentId, documentVersion, rawVersion, title, url,
                    publishedAt, precision, observations, textSha256, origin));
        }
        Set<String> evidenceArticles = new HashSet<>();
        for (Evidence e : evidence.values()) {
            Article article = articles.get(articleKey(e.articleId(), e.articleVersion()));
            need(article != null);
            need(article.documentId().equals(e.documentId()) && article.documentVersion().equals(e.documentVersion())
                    && article.rawVersion().equals(e.rawVersion()));
            evidenceArticles.add(articleKey(e.articleId(), e.articleVersion()));
        }
        need(articles.keySet().equals(evidenceArticles));

        Set<String> referenced = new HashSet<>();

        // companies -----------------------------------------------------------------------------------------------------
        Map<String, Company> companies = new LinkedHashMap<>();
        List<Obj> companyNodes = bundle.objects("companies");
        need(companyNodes.size() <= MAX_DECISIONS);
        for (Obj c : companyNodes) {
            Company company = company(c);
            need(!companies.containsKey(company.id()));
            companies.put(company.id(), company);
        }
        // pathCompanies: the private support references of structural paths. Same closed shape as a company, strictly ascending by
        // id, never a public company or issue; their exact closure over the complete paths is checked with the relations below.
        Map<String, Company> pathCompanies = new LinkedHashMap<>();
        List<Obj> pathCompanyNodes = bundle.objects("pathCompanies");
        need(pathCompanyNodes.size() <= MAX_DECISIONS);
        for (Obj c : pathCompanyNodes) {
            Company company = company(c);
            need(!pathCompanies.containsKey(company.id()) && !companies.containsKey(company.id()));
            pathCompanies.put(company.id(), company);
        }
        need(sortedUnique(new ArrayList<>(pathCompanies.keySet())));

        // issues --------------------------------------------------------------------------------------------------------
        Map<String, Issue> issues = new LinkedHashMap<>();
        List<Obj> issueNodes = bundle.objects("issues");
        need(issueNodes.size() <= MAX_ISSUES);
        for (Obj i : issueNodes) {
            i.exactly(Set.of("id", "canonicalId", "title", "action", "target", "eventTime", "timePrecision", "period",
                    "assertionStatus", "geography", "evidenceIds", "sourceEvents", "mentions", "decisionRef",
                    "representative", "fieldProvenance", "fieldVerdicts", "sourceSupport", "summary"));
            String id = text(i, "id", ID);
            text(i, "canonicalId", ID);
            text(i, "decisionRef", ID);
            String title = i.string("title");
            String action = i.stringOrNull("action");
            String target = i.stringOrNull("target");
            String eventTime = i.stringOrNull("eventTime");
            i.stringOrNull("period");
            String assertionStatus = i.stringOrNull("assertionStatus");
            String timePrecision = i.string("timePrecision");
            need(TIME_PRECISIONS.contains(timePrecision));
            Obj geography = i.object("geography").exactly(Set.of("value", "decisionRef", "decisionVersion", "policyVersion",
                    "countries", "verification", "evidenceIds", "basis"));
            String geographyValue = geography.string("value");
            String geographyPolicy = geography.string("policyVersion");
            need((geographyValue.equals("domestic") || geographyValue.equals("international")) && POLICY.equals(geographyPolicy));
            need("operator-field-verdict".equals(geography.string("verification")));
            text(geography, "decisionRef", ID);
            text(geography, "decisionVersion", ID);
            List<String> countries = strings(geography, "countries", 10);
            need(countriesClass(countries).equals(geographyValue));
            List<String> evidenceIds = evidenceIds(i, "evidenceIds", 1, evidence, referenced);
            List<String> geographyEvidence = evidenceIds(geography, "evidenceIds", 1, evidence, referenced);

            List<Obj> events = i.objects("sourceEvents");
            need(events.size() >= 1 && events.size() <= 1000);
            List<String> eventKeys = new ArrayList<>();
            for (Obj event : events) {
                sourceEvent(event, upstreams);
                eventKeys.add(Canonical.write(event.node()));
            }
            need(sortedUnique(eventKeys));
            Set<String> mentionEvidence = mentions(i, events, articles, companies, evidence, referenced);
            Set<String> expectedEvidence = new HashSet<>(mentionEvidence);
            expectedEvidence.addAll(geographyEvidence);
            Obj representativeNode = i.isNull("representative") ? null : i.object("representative");
            expectedEvidence.addAll(fieldSelection(i, representativeNode, evidence, referenced));
            need(expectedEvidence.equals(new HashSet<>(evidenceIds)));
            sourceSupport(i.object("sourceSupport"), evidenceIds, evidence, articles);
            List<Obj> basis = geography.objects("basis");
            need(basis.size() <= 1000 && basis.size() == events.size());
            for (int index = 0; index < basis.size(); index++) {
                Obj item = basis.get(index).exactly(Set.of("upstream", "kind", "ref", "mentionId", "documentId",
                        "documentVersion", "observation", "countries"));
                ObjectNode stripped = StrictJson.newObject();
                for (String name : item.node().propertyNames()) {
                    if (!name.equals("countries")) {
                        stripped.set(name, item.node().get(name));
                    }
                }
                sourceEvent(Obj.of(stripped), upstreams);
                need(item.strings("countries").equals(countries));
                need(Canonical.write(stripped).equals(eventKeys.get(index)));
            }
            if (!i.isNull("representative")) {
                Obj representative = i.object("representative").exactly(SOURCE_EVENT_KEYS);
                sourceEvent(representative, upstreams);
                need(eventKeys.contains(Canonical.write(representative.node())));
            }
            // fieldProvenance and fieldVerdicts were checked above, together with the headline values they decide.
            // The summary is recomputed from the bundle's own mentions, verdicts, evidence and articles (zero-call decision table).
            HandoffIssueSummary.verify(i, evidence, articles, executionMode, recordingKind);
            need(!issues.containsKey(id) && !companies.containsKey(id) && !pathCompanies.containsKey(id));
            issues.put(id, new Issue(id, title, action, target, eventTime, timePrecision, assertionStatus,
                    geographyValue, geographyPolicy, geographyEvidence, evidenceIds));
        }

        // relations -----------------------------------------------------------------------------------------------------
        Set<String> relationIds = new HashSet<>();
        Map<String, Integer> typeCounts = new LinkedHashMap<>();
        for (String type : PUBLIC_TYPES) {
            typeCounts.put(type, 0);
        }
        Set<String> linkedIssues = new HashSet<>();
        Set<String> linkedCompanies = new HashSet<>();
        List<Relation> relations = new ArrayList<>();
        Map<String, Set<String>> participants = new HashMap<>();
        Map<String, InvolvesFact> involves = new LinkedHashMap<>();
        List<PendingPath> pendingPaths = new ArrayList<>();
        List<Obj> relationNodes = bundle.objects("relations");
        need(relationNodes.size() <= MAX_RELATIONS);
        for (Obj r : relationNodes) {
            r.exactly(Set.of("id", "type", "source", "target", "role", "assertionStatus", "evidenceIds", "basis",
                    "provenance", "decisionRef", "sourceRefs", "structuralPath"));
            String id = text(r, "id", ID);
            String type = r.string("type");
            need(PUBLIC_TYPES.contains(type) && relationIds.add(id));
            typeCounts.merge(type, 1, Integer::sum);
            boolean follows = type.equals("FOLLOWS");
            String source = r.string("source");
            String target = r.string("target");
            need(issues.containsKey(source));
            need(follows ? issues.containsKey(target) : companies.containsKey(target));
            need(!source.equals(target));
            linkedIssues.add(source);
            if (follows) {
                linkedIssues.add(target);
            } else {
                linkedCompanies.add(target);
                if (type.equals("INVOLVES")) {
                    participants.computeIfAbsent(source, key -> new HashSet<>()).add(target);
                }
            }
            String role = r.stringOrNull("role");
            String assertionStatus = r.stringOrNull("assertionStatus");
            String decisionRef = r.isNull("decisionRef") ? null : text(r, "decisionRef", ID);
            List<String> evidenceIds = evidenceIds(r, "evidenceIds", 1, evidence, referenced);
            List<Obj> basisNodes = r.objects("basis");
            need(basisNodes.size() <= 2);
            need(type.equals("STRUCTURALLY_RELATED_TO") == (basisNodes.size() >= 1));
            List<Basis> basis = new ArrayList<>();
            List<String> basisRefs = new ArrayList<>();
            ArrayNode relationKeys = StrictJson.newArray();
            for (Obj b : basisNodes) {
                b.exactly(Set.of("sourceRelation", "relationKey", "relationType", "validFrom", "validUntil", "countries",
                        "verifiedAt", "sourceArticles", "evidenceIds", "businessScope", "productScope"));
                Obj sourceRelation = b.object("sourceRelation").exactly(Set.of("jobId", "relationCandidateId"));
                String jobId = text(sourceRelation, "jobId", ID);
                String candidate = text(sourceRelation, "relationCandidateId", RC);
                need(jobs.contains(jobId) && usedReviews.get(jobId).containsKey(candidate));
                basisRefs.add("s3-relation\n" + jobId + "\n" + candidate);
                String relationKey = text(b, "relationKey", HASH);
                relationKeys.add(relationKey);
                need("SUPPLIES".equals(b.string("relationType")));
                String verifiedAt = b.string("verifiedAt");
                // The structural verification time is the time of the event that made the relation eligible, not a producer clock.
                need(verifiedAt.equals(usedReviews.get(jobId).get(candidate).decidedAt()));
                String validFrom = b.stringOrNull("validFrom");
                String validUntil = b.stringOrNull("validUntil");
                strings(b, "countries", 10);
                // The scopes are the operator's S3 text copied as it stands: text, never an entity id and never a node.
                for (String scope : List.of("businessScope", "productScope")) {
                    String value = b.stringOrNull(scope);
                    need(value == null || value.codePointCount(0, value.length()) <= MAX_SCOPE_CODE_POINTS);
                }
                List<String> basisEvidence = evidenceIds(b, "evidenceIds", 1, evidence, referenced);
                List<Obj> links = b.objects("sourceArticles");
                need(links.size() <= 1000);
                List<String> actualLinks = new ArrayList<>();
                for (Obj link : links) {
                    link.exactly(Set.of("articleId", "articleVersion"));
                    String linkedArticle = text(link, "articleId", ARTICLE_ID);
                    String linkedVersion = text(link, "articleVersion", HASH);
                    need(articles.containsKey(articleKey(linkedArticle, linkedVersion)));
                    actualLinks.add(articleKey(linkedArticle, linkedVersion));
                }
                TreeSet<String> expectedLinks = new TreeSet<>();
                for (String evidenceId : basisEvidence) {
                    Evidence cited = evidence.get(evidenceId);
                    expectedLinks.add(articleKey(cited.articleId(), cited.articleVersion()));
                }
                need(actualLinks.equals(new ArrayList<>(expectedLinks)));
                basis.add(new Basis(verifiedAt, validFrom, validUntil));
            }
            boolean allAutomatic = true;
            List<String> sourcePairs = new ArrayList<>();
            List<Obj> refs = r.objects("sourceRefs");
            need(refs.size() >= 1 && refs.size() <= MAX_RELATIONS);
            List<String> refKeys = new ArrayList<>();
            for (Obj ref : refs) {
                ref.exactly(Set.of("kind", "jobId", "id"));
                String kind = ref.string("kind");
                String jobId = text(ref, "jobId", ID);
                String refId = ref.string("id");
                need(!refId.isEmpty());
                if (follows) {
                    need(kind.equals("s2-comparison") && FOLLOWS_REF.matcher(refId).matches()
                            && upstreamJobs.contains(jobId));
                } else {
                    need(kind.equals("s3-relation") && RC.matcher(refId).matches() && jobs.contains(jobId)
                            && usedReviews.get(jobId).containsKey(refId));
                    allAutomatic &= AUTOMATIC.equals(usedReviews.get(jobId).get(refId).kind());
                    sourcePairs.add(pair(jobId, refId));
                }
                refKeys.add(kind + "\n" + jobId + "\n" + refId);
            }
            need(new HashSet<>(refKeys).size() == refs.size());

            Obj provenance = r.object("provenance");
            ObjectNode preimage = StrictJson.newObject();
            preimage.put("type", type);
            preimage.put("source", source);
            preimage.put("target", target);
            switch (type) {
                case "INVOLVES" -> {
                    provenance.exactly(Set.of("origin", "s3SemanticValidation"));
                    // The automatic literal is true only when every contributing S3 relation was decided by the verifier.
                    need("s3-relation".equals(provenance.string("origin")) && (allAutomatic
                            ? "independent-verifier-supported-all-claims" : "manual-operator-final-approval")
                                    .equals(provenance.string("s3SemanticValidation")));
                    need(r.isNull("decisionRef") && r.isNull("role") && basisNodes.isEmpty());
                }
                case "STRUCTURALLY_RELATED_TO" -> {
                    provenance.exactly(Set.of("origin", "s3SemanticValidation", "status", "reviewer", "decisionRef",
                            "decisionVersion", "bindingDigest", "basisEligibility"));
                    need("manual-operator-review".equals(provenance.string("origin"))
                            && "none".equals(provenance.string("s3SemanticValidation"))
                            && "operator-asserted".equals(provenance.string("status"))
                            && (allAutomatic ? "s3-independent-verifier-supported-all-claims"
                                    : "s3-operator-final-approval").equals(provenance.string("basisEligibility")));
                    for (String name : List.of("reviewer", "decisionRef", "decisionVersion")) {
                        text(provenance, name, ID);
                    }
                    text(provenance, "bindingDigest", HASH);
                    need(decisionRef != null && decisionRef.equals(provenance.string("decisionRef")) && r.isNull("role")
                            && refKeys.equals(basisRefs));
                    preimage.set("basis", relationKeys);
                }
                default -> {
                    provenance.exactly(Set.of("origin", "s3SemanticValidation", "s2Relation", "evidenceGate", "groupDigest",
                            "decisionRef", "decisionVersion"));
                    need("s2-comparison-with-operator-decision".equals(provenance.string("origin"))
                            && "none".equals(provenance.string("s3SemanticValidation"))
                            && "FOLLOWS".equals(provenance.string("s2Relation"))
                            && "exact-source-citation-in-incoming-article".equals(provenance.string("evidenceGate")));
                    text(provenance, "groupDigest", HASH);
                    text(provenance, "decisionRef", ID);
                    text(provenance, "decisionVersion", ID);
                    need(decisionRef != null && decisionRef.equals(provenance.string("decisionRef")) && r.isNull("role")
                            && r.isNull("assertionStatus") && refs.size() == 1 && basisNodes.isEmpty());
                }
            }
            if (type.equals("STRUCTURALLY_RELATED_TO")) {
                pendingPaths.add(new PendingPath(source, target, r.object("structuralPath"), basisNodes.size()));
            } else {
                need(r.isNull("structuralPath"));
            }
            need(id.equals("edge-" + Canonical.digest(preimage)));
            if (type.equals("INVOLVES")) {
                Set<String> articleVersions = new HashSet<>();
                for (String evidenceId : evidenceIds) {
                    Evidence cited = evidence.get(evidenceId);
                    articleVersions.add(articleKey(cited.articleId(), cited.articleVersion()));
                }
                involves.put(id, new InvolvesFact(source, target, new HashSet<>(sourcePairs), articleVersions));
            }
            relations.add(new Relation(id, type, source, target, role, assertionStatus, evidenceIds, basis,
                    provenance.string("origin")));
        }
        need(issues.keySet().equals(linkedIssues));
        need(companies.keySet().equals(linkedCompanies));
        // Impacts close over the INVOLVES sourceRefs and are the only other referrers of evidence: they run before the orphan check.
        int impactCount = impacts(bundle, involves, usedReviews, evidence, referenced, executionMode);
        need(evidence.keySet().equals(referenced));
        // The structural paths close over the INVOLVES participants of their issue, the public companies and the private support
        // references: no orphan middle company, no public node is invented for a path.
        need(structuralPaths(pendingPaths, participants, companies, pathCompanies).equals(pathCompanies.keySet()));

        // exclusions, counts, checks, readiness, digests ----------------------------------------------------------------
        Obj exclusions = bundle.object("exclusions").exactly(Set.of("counts", "items"));
        JsonNode items = exclusions.array("items");
        need(items.size() <= MAX_EXCLUSIONS);
        Map<String, Integer> tally = new TreeMap<>();
        for (JsonNode itemNode : items.values()) {
            Obj item = Obj.of(itemNode).keys(Set.of("kind", "id", "jobId", "code"), Set.of("detail"));
            need(Set.of("issue", "relation", "structural", "follows").contains(item.string("kind")));
            item.string("id");
            if (!item.isNull("jobId")) {
                text(item, "jobId", ID);
            }
            String code = text(item, "code", ID);
            if (item.has("detail")) {
                if (code.equals("issue_metadata_conflict")) {
                    Obj detail = item.object("detail").exactly(Set.of("fields"));
                    List<String> fields = detail.strings("fields");
                    need(!fields.isEmpty() && new HashSet<>(fields).size() == fields.size()
                            && Set.of("title", "action", "target", "eventTime", "period", "assertionStatus")
                                    .containsAll(fields));
                } else if (code.equals("applicability_binding_mismatch")) {
                    Obj detail = item.object("detail").exactly(Set.of("expectedBindingDigest"));
                    text(detail, "expectedBindingDigest", HASH);
                } else {
                    need(false);
                }
            }
            tally.merge(code, 1, Integer::sum);
        }
        Obj exclusionCounts = exclusions.object("counts");
        need(Set.copyOf(exclusionCounts.node().propertyNames()).equals(tally.keySet()));
        for (Map.Entry<String, Integer> entry : tally.entrySet()) {
            need(exclusionCounts.count(entry.getKey()) == entry.getValue());
        }

        Obj counts = bundle.object("counts").exactly(Set.of("companies", "pathCompanies", "issues", "relations", "evidence",
                "articles", "exclusions", "impacts"));
        need(counts.count("companies") == companies.size() && counts.count("pathCompanies") == pathCompanies.size()
                && counts.count("issues") == issues.size() && counts.count("evidence") == evidence.size()
                && counts.count("articles") == articles.size() && counts.count("exclusions") == items.size()
                && counts.count("impacts") == impactCount);
        Obj relationCounts = counts.object("relations").exactly(Set.copyOf(PUBLIC_TYPES));
        for (String type : PUBLIC_TYPES) {
            need(relationCounts.count(type) == typeCounts.get(type));
        }

        Obj checks = bundle.object("checks").exactly(Set.of("producerConfirmed", "appImportPending"));
        need(checks.strings("producerConfirmed").equals(PRODUCER_CHECKS));
        need(checks.strings("appImportPending").equals(APP_IMPORT_PENDING));
        Obj readiness = bundle.object("readiness").exactly(Set.of("app", "evidenceRegistration", "publicActivation",
                "graphDb"));
        need("import-pending".equals(readiness.string("app")) && "not-registered".equals(readiness.string("evidenceRegistration"))
                && "none".equals(readiness.string("publicActivation")) && "none".equals(readiness.string("graphDb")));
        Obj digests = bundle.object("digests").exactly(Set.of("content"));
        need(digests.string("content").equals(contentDigest(node)));

        List<Approval> approvals = new ArrayList<>();
        usedReviews.values().forEach(perJob -> approvals.addAll(perJob.values()));
        return new HandoffBundle(handoffId, manifestDigest, sourceKind, executionMode, recordingKind, policyVersion, files,
                pins, new ArrayList<>(companies.values()), new ArrayList<>(pathCompanies.values()),
                new ArrayList<>(issues.values()), relations, new ArrayList<>(evidence.values()),
                new ArrayList<>(articles.values()), approvals);
    }

    /** One emitted INVOLVES edge as the impact rows must close over it: endpoints, S3 source refs and evidence article versions. */
    private record InvolvesFact(String source, String target, Set<String> sourcePairs, Set<String> articleVersions) {
    }

    /**
     * The closed {@code impacts[]} of a bundle-6: exactly one row per S3 relation behind an INVOLVES edge ({@code sourceRefs}), sorted
     * by {@code (edgeId, jobId, relationCandidateId)}, never aggregated per edge. A row's status, code and nullability follow the
     * producer's S3 state table; {@code not-applicable} is the operator's final approval and nothing else (and only then), so a
     * verifier label can never be claimed for a human-approved relation. A {@code verified} row lists the verifier-mapped quote
     * effects as app evidence ids of the edge's own article versions; its label is recomputed, never trusted, and every effect id
     * counts as referenced (no orphan evidence). The proposal is the producer's own unverified content ({@code verification: none}).
     * A {@code verifier_reply_invalid} row can only come from a replay; a replay's {@code called} is an authored fixture.
     *
     * @return the number of rows, for {@code counts.impacts}
     */
    private static int impacts(Obj bundle, Map<String, InvolvesFact> involves, Map<String, Map<String, Approval>> usedReviews,
            Map<String, Evidence> evidence, Set<String> referenced, String executionMode) {
        List<Obj> nodes = bundle.objects("impacts");
        need(nodes.size() <= MAX_RELATIONS);
        Set<String> covered = new HashSet<>();
        Set<String> candidates = new HashSet<>();
        String[] previous = null;
        for (Obj row : nodes) {
            row.exactly(IMPACT_KEYS);
            String edgeId = text(row, "edgeId", ID);
            InvolvesFact fact = involves.get(edgeId);
            need(fact != null);
            need(fact.source().equals(row.string("issueId")) && fact.target().equals(row.string("companyId")));
            Obj sourceRelation = row.object("sourceRelation").exactly(Set.of("jobId", "relationCandidateId"));
            String jobId = text(sourceRelation, "jobId", ID);
            String relationCandidateId = text(sourceRelation, "relationCandidateId", RC);
            String[] key = {edgeId, jobId, relationCandidateId};
            need(previous == null || compareTuples(previous, key) < 0);
            previous = key;
            need(fact.sourcePairs().contains(pair(jobId, relationCandidateId)));
            Approval approval = usedReviews.get(jobId).get(relationCandidateId);
            need(approval != null);
            need(covered.add(pair(edgeId, pair(jobId, relationCandidateId))));

            String status = row.string("status");
            String code = row.stringOrNull("code");
            String candidate = row.isNull("impactCandidateId") ? null : text(row, "impactCandidateId", IMPACT_CANDIDATE);
            String verifier = row.string("verifier");
            need(verifier.equals("called") || verifier.equals("not-called"));
            boolean called = verifier.equals("called");
            String requestDigest = row.isNull("verifierRequestDigest") ? null : text(row, "verifierRequestDigest", HASH);
            Obj proposal = row.isNull("proposal") ? null : row.object("proposal");
            if (proposal != null) {
                proposal(proposal);
            }
            // The operator's final approval made no impact call: not-applicable if and only if it decided the relation.
            need(OPERATOR_FINAL.equals(approval.kind()) == status.equals("not-applicable"));

            boolean hasCandidate = false;
            boolean verifierCalled = false;
            boolean hasProposal = false;
            switch (status) {
                case "not-applicable", "not-proposed" -> need(code == null);
                case "technical-reject" -> {
                    need(code != null);
                    switch (code) {
                        case "producer_reply_invalid" -> {
                        }
                        case "impact_precheck_rejected" -> hasCandidate = true;
                        case "verifier_reply_invalid" -> {
                            // A live verifier cannot answer with a reply the S3 ledger refused; only an authored replay holds one.
                            need("replay".equals(executionMode));
                            hasCandidate = true;
                            verifierCalled = true;
                            hasProposal = true;
                        }
                        default -> need(false);
                    }
                }
                case "no-evidence" -> {
                    need(code == null);
                    hasCandidate = true;
                    hasProposal = true;
                }
                case "verifier-reject", "verified" -> {
                    need(code == null);
                    hasCandidate = true;
                    verifierCalled = true;
                    hasProposal = true;
                }
                case "withheld" -> {
                    need("impact_evidence_outside_relation_documents".equals(code) || "impact_quote_ambiguous".equals(code));
                    hasCandidate = true;
                    verifierCalled = true;
                    hasProposal = true;
                }
                default -> need(false);
            }
            need((candidate != null) == hasCandidate && called == verifierCalled && (requestDigest != null) == verifierCalled
                    && (proposal != null) == hasProposal);
            // (jobId, impactCandidateId) names one S3 impact candidate; two relations of one job never share it.
            need(candidate == null || candidates.add(pair(jobId, candidate)));

            String label = row.stringOrNull("label");
            String targetVerdict = row.stringOrNull("targetVerdict");
            switch (status) {
                case "verified" -> need("supported".equals(targetVerdict) || "insufficient".equals(targetVerdict));
                case "verifier-reject" -> need("contradicted".equals(targetVerdict));
                default -> need(targetVerdict == null);
            }
            if (!status.equals("verified")) {
                need(label == null && row.isNull("effects"));
                continue;
            }
            need(label != null && IMPACT_LABELS.contains(label));
            Obj effects = row.object("effects").exactly(Set.copyOf(EFFECT_SIDES));
            Map<String, List<String>> sides = new LinkedHashMap<>();
            Set<String> union = new HashSet<>();
            Set<String> sourceEvidence = new HashSet<>();
            for (String side : EFFECT_SIDES) {
                List<String> ids = strings(effects, side, MAX_IMPACT_EVIDENCE);
                need(sortedUnique(ids));
                for (String id : ids) {
                    need(EVIDENCE_ID.matcher(id).matches());
                    Evidence cited = evidence.get(id);
                    need(cited != null && union.add(id));
                    // Impact evidence sits on the edge's own article versions, so the visibility and rights of the edge cover it.
                    need(fact.articleVersions().contains(articleKey(cited.articleId(), cited.articleVersion())));
                    need(sourceEvidence.add(cited.sourceEvidenceId()));
                }
                sides.put(side, ids);
            }
            need(union.size() >= 1 && union.size() <= MAX_IMPACT_EVIDENCE);
            need(label.equals(impactLabel(targetVerdict, sides)));
            referenced.addAll(union);
        }
        // Exact coverage: every INVOLVES source ref has its row, and (rows being strictly sorted and bound to a ref) no other exists.
        Set<String> expected = new HashSet<>();
        involves.forEach((edgeId, fact) -> fact.sourcePairs().forEach(sourcePair -> expected.add(pair(edgeId, sourcePair))));
        need(covered.equals(expected));
        return nodes.size();
    }

    /**
     * The label of a verified impact, recomputed from what the verifier said: an uncertain quote effect or an insufficient target is
     * {@code undetermined} (no label comes out of the remaining quotes); otherwise both sides cited is {@code mixed}, one side is that
     * side, and neither (neutral only) is {@code undetermined}. Never a probability and never a price direction.
     */
    static String impactLabel(String targetVerdict, Map<String, List<String>> sides) {
        if (!sides.get("uncertain").isEmpty() || "insufficient".equals(targetVerdict)) {
            return "undetermined";
        }
        boolean positive = !sides.get("positive").isEmpty();
        boolean negative = !sides.get("negative").isEmpty();
        return positive && negative ? "mixed" : positive ? "positive" : negative ? "negative" : "undetermined";
    }

    /** The producer's proposal, unverified: closed, lengths counted in Unicode code points (not UTF-16 units). */
    private static void proposal(Obj proposal) {
        proposal.exactly(PROPOSAL_KEYS);
        need(IMPACT_LABELS.contains(proposal.string("direction")));
        String reason = proposal.string("reason");
        int reasonLength = reason.codePointCount(0, reason.length());
        need(reasonLength >= 1 && reasonLength <= MAX_PROPOSAL_REASON_CODE_POINTS);
        String limitations = proposal.stringOrNull("limitations");
        need(limitations == null || limitations.codePointCount(0, limitations.length()) <= MAX_PROPOSAL_LIMITATIONS_CODE_POINTS);
        need("none".equals(proposal.string("verification")));
    }

    private static int compareTuples(String[] a, String[] b) {
        for (int index = 0; index < a.length; index++) {
            int order = compareCodePoints(a[index], b[index]);
            if (order != 0) {
                return order;
            }
        }
        return 0;
    }

    /** One closed company object: the id, the label the app catalogue must hold, and the producer's own canonical id and ref. */
    private static Company company(Obj node) {
        node.exactly(Set.of("id", "canonicalId", "label", "decisionRef"));
        String id = text(node, "id", ID);
        text(node, "canonicalId", ID);
        text(node, "decisionRef", ID);
        return new Company(id, node.string("label"));
    }

    /** A STRUCTURALLY_RELATED_TO relation's path, held until every INVOLVES relation of the bundle is known. */
    private record PendingPath(String issue, String target, Obj path, int basis) {
    }

    /**
     * The closed {@code structuralPath} of every structural relation, checked against the issue's INVOLVES participants and the
     * company sets. A {@code complete} path is the ordered company chain {@code [P, C]} or {@code [P, M, C]}, one link per
     * basis: {@code P} is a participant of the relation's own issue, {@code C} is the relation target and not a participant, all
     * ids are distinct, the middle is a mapped company (public, or a private path company), and each link's two endpoints are the
     * adjacent chain ids in either order (the link's direction is the S3 supplier/customer direction, kept as stated). A path is
     * {@code unavailable} only for a two-basis chain whose middle company is unmapped; a one-basis edge always has the complete
     * two-company chain, and nothing is ever truncated or invented.
     *
     * @return the private path companies the complete paths use: the middles that are not public companies
     */
    private static Set<String> structuralPaths(List<PendingPath> pending, Map<String, Set<String>> participants,
            Map<String, Company> companies, Map<String, Company> pathCompanies) {
        Set<String> used = new HashSet<>();
        for (PendingPath item : pending) {
            Obj path = item.path();
            String status = path.string("status");
            if (status.equals("unavailable")) {
                path.exactly(Set.of("status", "reason"));
                need(UNMAPPED_MIDDLE.equals(path.string("reason")) && item.basis() == 2);
                continue;
            }
            need(status.equals("complete"));
            path.exactly(Set.of("status", "companyIds", "links"));
            List<String> ids = strings(path, "companyIds", 3);
            need(ids.size() >= 2 && ids.size() == item.basis() + 1 && new HashSet<>(ids).size() == ids.size());
            for (String id : ids) {
                need(ID.matcher(id).matches());
            }
            Set<String> involved = participants.getOrDefault(item.issue(), Set.of());
            String first = ids.get(0);
            String last = ids.get(ids.size() - 1);
            need(involved.contains(first) && last.equals(item.target()) && !involved.contains(last));
            need(companies.containsKey(first) && companies.containsKey(last));
            for (int index = 1; index < ids.size() - 1; index++) {
                String middle = ids.get(index);
                need(companies.containsKey(middle) || pathCompanies.containsKey(middle));
                if (!companies.containsKey(middle)) {
                    used.add(middle);
                }
            }
            List<Obj> links = path.objects("links");
            need(links.size() == ids.size() - 1);
            for (int index = 0; index < links.size(); index++) {
                Obj link = links.get(index).exactly(Set.of("supplierCompanyId", "customerCompanyId"));
                String supplier = text(link, "supplierCompanyId", ID);
                String customer = text(link, "customerCompanyId", ID);
                String from = ids.get(index);
                String to = ids.get(index + 1);
                need((supplier.equals(from) && customer.equals(to)) || (supplier.equals(to) && customer.equals(from)));
            }
        }
        return used;
    }

    /**
     * One S3 relation's effective eligibility decision. The deciding review revision repeats in {@code approvalBasis.revision}; an
     * automatic verdict has no reviewer and a human's final approval names one. Neither says anything about the other: the
     * approval basis is audit metadata, and a human approval is never read as an independent-verifier verdict.
     */
    private static Approval approval(String jobId, String candidate, int revision, Obj basis) {
        basis.exactly(APPROVAL_KEYS);
        String kind = basis.string("kind");
        need(kind.equals(AUTOMATIC) || kind.equals(OPERATOR_FINAL));
        need(basis.count("revision") == revision);
        String reviewer = basis.stringOrNull("reviewer");
        // The reviewer is the review wire's own free text (1..200 characters, e.g. an e-mail address): no id pattern is imposed.
        need(kind.equals(AUTOMATIC) ? reviewer == null : reviewer != null && !reviewer.isBlank() && reviewer.length() <= 200);
        String decidedAt = basis.string("decidedAt");
        try {
            OffsetDateTime.parse(decidedAt);
        } catch (DateTimeException notATimestamp) {
            throw new StrictJson.Malformed();
        }
        return new Approval(jobId, candidate, kind, revision, reviewer, decidedAt);
    }

    /** An operator's declared origin of a document version; {@code verification} is the literal that says it was declared. */
    private static Origin origin(Obj origin) {
        origin.exactly(ORIGIN_KEYS);
        need("operator-declared-origin".equals(origin.string("verification")));
        return new Origin(text(origin, "originId", ID), text(origin, "reviewer", ID), text(origin, "decisionRef", ID),
                text(origin, "decisionVersion", ID));
    }

    /**
     * The issue's {@code sourceSupport}, recomputed from the declared origins and the exact article texts; nothing the producer
     * says is trusted. The issue's articles are the distinct articles its evidence rows cite, and an issue may cite one version
     * of an article only (a second version is refused, never merged). Two articles are in one lineage group when they share a
     * declared origin or their prepared text is exactly equal (SHA-256 of the text, a union-find, as in the PoC
     * {@code _source_support}). {@code knownLineageCount} is the number of lineage GROUPS that contain a declared origin, not a
     * number of articles; {@code unknownLineageArticles} are the articles without a declared origin; {@code independentSourceCount}
     * is {@code null} when any article has no origin or a group holds more than one distinct origin, otherwise it equals the
     * known group count; {@code duplicateGroups} are the groups of exactly equal text (two or more articles), never groups joined
     * only through a shared origin. Publisher, URL, host, source id and title are never used.
     */
    private static void sourceSupport(Obj node, List<String> evidenceIds, Map<String, Evidence> evidence,
            Map<String, Article> articles) {
        node.exactly(SUPPORT_KEYS);
        TreeMap<String, Article> members = new TreeMap<>(HandoffBundleVerifier::compareCodePoints);
        for (String evidenceId : evidenceIds) {
            Evidence row = evidence.get(evidenceId);
            Article article = articles.get(articleKey(row.articleId(), row.articleVersion()));
            need(article != null);
            Article previous = members.put(row.articleId(), article);
            need(previous == null || previous == article);
        }
        List<String> ids = new ArrayList<>(members.keySet());
        List<Article> list = new ArrayList<>(members.values());
        int[] parent = new int[list.size()];
        for (int index = 0; index < parent.length; index++) {
            parent[index] = index;
        }
        Map<String, Integer> firstOfOrigin = new HashMap<>();
        Map<String, Integer> firstOfText = new HashMap<>();
        List<String> unknown = new ArrayList<>();
        for (int index = 0; index < list.size(); index++) {
            Article article = list.get(index);
            if (article.origin() == null) {
                unknown.add(ids.get(index));
            } else {
                Integer same = firstOfOrigin.putIfAbsent(article.origin().originId(), index);
                if (same != null) {
                    parent[root(parent, index)] = root(parent, same);
                }
            }
            Integer copy = firstOfText.putIfAbsent(article.textSha256(), index);
            if (copy != null) {
                parent[root(parent, index)] = root(parent, copy);
            }
        }
        Map<Integer, Set<String>> lineages = new HashMap<>();
        for (int index = 0; index < list.size(); index++) {
            Set<String> origins = lineages.computeIfAbsent(root(parent, index), key -> new HashSet<>());
            if (list.get(index).origin() != null) {
                origins.add(list.get(index).origin().originId());
            }
        }
        int known = 0;
        boolean ambiguous = false;
        for (Set<String> origins : lineages.values()) {
            known += origins.isEmpty() ? 0 : 1;
            ambiguous |= origins.size() > 1;
        }
        Integer independent = unknown.isEmpty() && !ambiguous ? known : null;
        Map<String, List<String>> byText = new HashMap<>();
        for (int index = 0; index < list.size(); index++) {
            byText.computeIfAbsent(list.get(index).textSha256(), key -> new ArrayList<>()).add(ids.get(index));
        }
        List<List<String>> groups = new ArrayList<>();
        for (List<String> group : byText.values()) {
            if (group.size() > 1) {
                groups.add(group);
            }
        }
        groups.sort((first, second) -> {
            for (int index = 0; index < Math.min(first.size(), second.size()); index++) {
                int order = compareCodePoints(first.get(index), second.get(index));
                if (order != 0) {
                    return order;
                }
            }
            return Integer.compare(first.size(), second.size());
        });

        need(node.count("articleCount") == list.size());
        need(node.count("knownLineageCount") == known);
        need(node.strings("unknownLineageArticles").equals(unknown));
        need(independent == null ? node.isNull("independentSourceCount")
                : !node.isNull("independentSourceCount") && node.count("independentSourceCount") == independent);
        List<List<String>> actual = new ArrayList<>();
        for (JsonNode group : node.array("duplicateGroups").values()) {
            need(group.isArray());
            List<String> members2 = new ArrayList<>();
            for (JsonNode id : group.values()) {
                need(id.isString());
                members2.add(id.stringValue());
            }
            actual.add(members2);
        }
        need(actual.equals(groups));
    }

    private static int root(int[] parent, int index) {
        int current = index;
        while (parent[current] != current) {
            parent[current] = parent[parent[current]];
            current = parent[current];
        }
        return current;
    }

    // ------------------------------------------------------------------------------------------------ helpers ------------

    /**
     * The issue's original mentions: exactly the identities ({@code documentId}, {@code documentVersion}, S2 local
     * {@code mentionId}) of its source events, one record each, strictly ascending. Each mention names the one bundle article of
     * its document version, every carrying source event closes against that article, and every cited evidence row is on it. The
     * values are the producer's S2 candidate or snapshot values ({@code verification} is always {@code none}); nothing is
     * derived from the merged issue. Returns the union of the mentions' evidence ids.
     */
    private static Set<String> mentions(Obj issue, List<Obj> events, Map<String, Article> articles,
            Map<String, Company> companies, Map<String, Evidence> evidence, Set<String> referenced) {
        List<Obj> nodes = issue.objects("mentions");
        need(nodes.size() >= 1 && nodes.size() <= MAX_MENTIONS);
        List<String> keys = new ArrayList<>();
        Map<String, Article> articleOf = new HashMap<>();
        Set<String> union = new HashSet<>();
        for (Obj mention : nodes) {
            mention.exactly(MENTION_KEYS);
            String documentId = text(mention, "documentId", ID);
            String documentVersion = text(mention, "documentVersion", HASH);
            String mentionId = mention.string("mentionId");
            need(!mentionId.isEmpty());
            String key = mentionKey(documentId, documentVersion, mentionId);
            keys.add(key);
            String articleId = text(mention, "articleId", ARTICLE_ID);
            String articleVersion = text(mention, "articleVersion", HASH);
            Article own = null;
            int matching = 0;
            for (Article article : articles.values()) {
                if (article.documentId().equals(documentId) && article.documentVersion().equals(documentVersion)) {
                    own = article;
                    matching++;
                }
            }
            need(matching == 1 && own.articleId().equals(articleId) && own.articleVersion().equals(articleVersion));
            articleOf.put(key, own);

            need("none".equals(mention.string("verification")));
            mention.string("title");
            mention.string("action");
            mention.stringOrNull("target");
            mention.stringOrNull("period");
            String timePrecision = mention.string("timePrecision");
            need(TIME_PRECISIONS.contains(timePrecision));
            HandoffTime.mentionEventTime(mention.stringOrNull("eventTime"), timePrecision);
            need(ASSERTION_STATUSES.contains(mention.string("assertionStatus")));
            mention.bool("background");

            List<Obj> participants = mention.objects("participants");
            need(participants.size() <= MAX_PARTICIPANTS);
            for (Obj participant : participants) {
                participant.exactly(PARTICIPANT_KEYS);
                String sourceCompanyId = participant.stringOrNull("sourceCompanyId");
                String companyId = participant.stringOrNull("companyId");
                need(companyId == null || (sourceCompanyId != null && companies.containsKey(companyId)));
                participant.string("name");
                participant.string("role");
            }

            List<String> cited = evidenceIds(mention, "evidenceIds", 1, evidence, referenced);
            for (String evidenceId : cited) {
                Evidence row = evidence.get(evidenceId);
                need(row.articleId().equals(articleId) && row.articleVersion().equals(articleVersion));
            }
            union.addAll(cited);
        }
        need(sortedUnique(keys));

        Set<String> carried = new HashSet<>();
        for (Obj event : events) {
            String key = mentionKey(event.string("documentId"), event.string("documentVersion"), event.string("mentionId"));
            carried.add(key);
            Article article = articleOf.get(key);
            need(article != null);
            Obj observation = event.object("observation");
            String rawVersion = observation.string("rawVersion");
            String roundId = observation.string("roundId");
            String sourceId = observation.string("sourceId");
            int page = observation.count("page");
            int ordinal = observation.count("ordinal");
            need(article.rawVersion().equals(rawVersion) && article.observations().stream().anyMatch(
                    ob -> ob.roundId().equals(roundId) && ob.sourceId().equals(sourceId) && ob.page() == page
                            && ob.ordinal() == ordinal));
        }
        need(carried.equals(new HashSet<>(keys)));
        return union;
    }

    /**
     * The issue's headline values, its {@code fieldProvenance} and its operator {@code fieldVerdicts}, recomputed together from
     * the ORIGINAL mentions; nothing the producer says about them is trusted.
     *
     * <p>The <b>selected</b> value of a field is the operator representative's own mention value, or, when there is no
     * representative, the one value every mention states (a unanimous issue whose mentions disagree is refused). Each verdict
     * judges one original mention's {@code eventTime} or {@code period} string exactly as it stands there ({@code value}, never
     * null), by closed decision and reason code (ALLOW/stated and HOLD/ambiguous and REJECT/contradicted cite at least one span;
     * HOLD/unstated none), with only evidence rows of that mention's own article, one verdict per (mention, field), strictly
     * ascending by mention identity and then field order. A field is <b>withheld</b> exactly when some HOLD or REJECT judges
     * it on the selection basis (the representative's mention, or any mention when unanimous): the issue then carries
     * {@code null} for it (and {@code unknown} precision for {@code eventTime}), never another mention's value; a field with
     * no such verdict carries the selected value unchanged, and {@code timePrecision} is the selected mention's own.
     * {@code fieldProvenance.withheld} must equal that recomputed list. {@code sameValueMentions} lists, in mention order, the
     * mentions whose ORIGINAL value equals the selected one (JSON equality, {@code null} matches {@code null}, never the
     * redacted {@code null}); it records selection, never verification. Returns the verdicts' evidence ids.
     */
    private static Set<String> fieldSelection(Obj issue, Obj representative, Map<String, Evidence> evidence,
            Set<String> referenced) {
        List<Obj> mentions = issue.objects("mentions");
        List<String> everyone = new ArrayList<>();
        Map<String, Obj> byKey = new HashMap<>();
        for (Obj mention : mentions) {
            String key = mentionKey(mention.string("documentId"), mention.string("documentVersion"), mention.string("mentionId"));
            everyone.add(key);
            byKey.put(key, mention);
        }
        String chosen = representative == null ? null : mentionKey(representative.string("documentId"),
                representative.string("documentVersion"), representative.string("mentionId"));
        need(chosen == null || byKey.containsKey(chosen));
        Obj selectedMention = chosen == null ? mentions.get(0) : byKey.get(chosen);

        // the verdicts --------------------------------------------------------------------------------------------------
        List<Obj> verdicts = issue.objects("fieldVerdicts");
        need(verdicts.size() <= MAX_VERDICTS);
        Set<String> verdictEvidence = new HashSet<>();
        Set<String> withheld = new HashSet<>();
        String previousKey = null;
        int previousField = -1;
        for (Obj verdict : verdicts) {
            verdict.exactly(VERDICT_KEYS);
            String key = mentionKey(text(verdict, "documentId", ID), text(verdict, "documentVersion", HASH),
                    verdict.string("mentionId"));
            Obj mention = byKey.get(key);
            need(mention != null && !verdict.string("mentionId").isEmpty());
            String field = verdict.string("field");
            int fieldIndex = VERDICT_FIELDS.indexOf(field);
            need(fieldIndex >= 0);
            if (previousKey != null) {
                int order = compareCodePoints(previousKey, key);
                need(order < 0 || (order == 0 && previousField < fieldIndex));
            }
            previousKey = key;
            previousField = fieldIndex;
            // The reviewed value is the mention's own current string: a verdict on an absent value has nothing to judge.
            need(!mention.isNull(field) && verdict.string("value").equals(mention.string(field)));
            String decision = verdict.string("decision");
            String reason = verdict.string("reasonCode");
            List<String> cited = evidenceIds(verdict, "evidenceIds", 0, evidence, referenced);
            need(cited.size() <= MAX_VERDICT_EVIDENCE);
            for (String evidenceId : cited) {
                Evidence row = evidence.get(evidenceId);
                need(row.articleId().equals(mention.string("articleId"))
                        && row.articleVersion().equals(mention.string("articleVersion")));
            }
            switch (decision) {
                case "ALLOW" -> need(reason.equals("stated") && !cited.isEmpty());
                case "HOLD" -> need((reason.equals("unstated") && cited.isEmpty())
                        || (reason.equals("ambiguous") && !cited.isEmpty()));
                case "REJECT" -> need(reason.equals("contradicted") && !cited.isEmpty());
                default -> need(false);
            }
            need("operator-field-verdict".equals(verdict.string("verification")));
            for (String name : List.of("reviewer", "decisionRef", "decisionVersion")) {
                text(verdict, name, ID);
            }
            verdictEvidence.addAll(cited);
            if (!decision.equals("ALLOW") && (chosen == null || key.equals(chosen))) {
                withheld.add(field);
            }
        }

        // fieldProvenance -----------------------------------------------------------------------------------------------
        Obj provenance = issue.object("fieldProvenance").exactly(Set.of("selection", "verification", "withheld",
                "sameValueMentions"));
        need(provenance.string("selection").equals(representative != null ? "operator-representative" : "unanimous"));
        need("none".equals(provenance.string("verification")));
        List<String> expectedWithheld = new ArrayList<>();
        for (String field : VERDICT_FIELDS) {
            if (withheld.contains(field)) {
                expectedWithheld.add(field);
            }
        }
        need(provenance.strings("withheld").equals(expectedWithheld));
        Obj same = provenance.object("sameValueMentions").exactly(new HashSet<>(PROVENANCE_FIELDS));
        for (String field : PROVENANCE_FIELDS) {
            JsonNode selected = selectedMention.raw(field);
            List<String> expected = new ArrayList<>();
            for (int index = 0; index < mentions.size(); index++) {
                if (mentions.get(index).raw(field).equals(selected)) {
                    expected.add(everyone.get(index));
                }
            }
            List<Obj> references = same.objects(field);
            need(references.size() <= MAX_MENTIONS);
            List<String> actual = new ArrayList<>();
            for (Obj reference : references) {
                reference.exactly(MENTION_REF_KEYS);
                actual.add(mentionKey(reference.string("documentId"), reference.string("documentVersion"),
                        reference.string("mentionId")));
            }
            need(!expected.isEmpty() && actual.equals(expected));
            need(chosen == null ? expected.equals(everyone) : expected.contains(chosen));
            // the headline: the selected value, or nothing at all when a verdict withholds it
            if (withheld.contains(field)) {
                need(issue.isNull(field));
            } else {
                need(issue.raw(field).equals(selected));
            }
        }
        need(issue.string("timePrecision").equals(withheld.contains("eventTime") ? "unknown"
                : selectedMention.string("timePrecision")));
        return verdictEvidence;
    }

    /** The canonical JSON of the S2 mention identity: the document version and the document-local mention id. */
    private static String mentionKey(String documentId, String documentVersion, String mentionId) {
        ObjectNode identity = StrictJson.newObject();
        identity.put("documentId", documentId);
        identity.put("documentVersion", documentVersion);
        identity.put("mentionId", mentionId);
        return Canonical.write(identity);
    }

    private static void sourceEvent(Obj event, Set<String> upstreams) {
        event.exactly(SOURCE_EVENT_KEYS);
        Obj upstream = event.object("upstream").exactly(Set.of("jobId", "inputDigest"));
        need(upstreams.contains(pair(text(upstream, "jobId", ID), text(upstream, "inputDigest", HASH))));
        String kind = event.string("kind");
        need(kind.equals("event-candidate") || kind.equals("snapshot-event"));
        String ref = text(event, "ref", kind.equals("event-candidate") ? EVC : null);
        need(!ref.isEmpty() && !event.string("mentionId").isEmpty());
        String documentId = text(event, "documentId", ID);
        String documentVersion = text(event, "documentVersion", HASH);
        Obj observation = event.object("observation").exactly(OBSERVATION_KEYS);
        for (String name : List.of("roundId", "sourceId", "documentId")) {
            need(!observation.string(name).isEmpty());
        }
        text(observation, "rawVersion", HASH);
        text(observation, "documentVersion", HASH);
        observation.count("page");
        observation.count("ordinal");
        need(observation.string("documentId").equals(documentId) && observation.string("documentVersion").equals(documentVersion));
    }

    /** A non-empty, strictly ascending list of known evidence ids; every id is recorded as referenced. */
    private static List<String> evidenceIds(Obj owner, String name, int minimum, Map<String, Evidence> evidence,
            Set<String> referenced) {
        List<String> ids = strings(owner, name, 100_000);
        for (String id : ids) {
            need(EVIDENCE_ID.matcher(id).matches());
        }
        need(ids.size() >= minimum && sortedUnique(ids) && evidence.keySet().containsAll(ids));
        referenced.addAll(ids);
        return ids;
    }

    /** {@code invalid} and the empty list never equal a public class; KR alone is domestic, anything else international. */
    static String countriesClass(List<String> countries) {
        if (countries.isEmpty()) {
            return "unknown";
        }
        for (String country : countries) {
            if (country.length() != 2 || !isUpperAscii(country.charAt(0)) || !isUpperAscii(country.charAt(1))) {
                return "invalid";
            }
        }
        return new HashSet<>(countries).equals(Set.of("KR")) ? "domestic" : "international";
    }

    private static boolean isUpperAscii(char c) {
        return c >= 'A' && c <= 'Z';
    }

    /** Strictly ascending in Unicode code point order (Python's string order), which also rules out duplicates. */
    static boolean sortedUnique(List<String> values) {
        for (int index = 1; index < values.size(); index++) {
            if (compareCodePoints(values.get(index - 1), values.get(index)) >= 0) {
                return false;
            }
        }
        return true;
    }

    static int compareCodePoints(String a, String b) {
        int i = 0;
        int j = 0;
        while (i < a.length() && j < b.length()) {
            int x = a.codePointAt(i);
            int y = b.codePointAt(j);
            if (x != y) {
                return Integer.compare(x, y);
            }
            i += Character.charCount(x);
            j += Character.charCount(y);
        }
        return Integer.compare(a.length() - i, b.length() - j);
    }

    static String articleKey(String articleId, String version) {
        return articleId + "\n" + version;
    }

    private static String pair(String first, String second) {
        return first + "\n" + second;
    }

    private static String text(Obj owner, String name, Pattern pattern) {
        String value = owner.string(name);
        need(pattern == null || pattern.matcher(value).matches());
        return value;
    }

    private static List<String> strings(Obj owner, String name, int maximum) {
        List<String> values = owner.strings(name);
        need(values.size() <= maximum);
        return values;
    }

    private static void need(boolean condition) {
        if (!condition) {
            throw new StrictJson.Malformed();
        }
    }
}
