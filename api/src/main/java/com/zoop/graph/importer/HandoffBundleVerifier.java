package com.zoop.graph.importer;

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
import com.zoop.graph.importer.HandoffBundle.Article;
import com.zoop.graph.importer.HandoffBundle.Basis;
import com.zoop.graph.importer.HandoffBundle.Company;
import com.zoop.graph.importer.HandoffBundle.Evidence;
import com.zoop.graph.importer.HandoffBundle.Issue;
import com.zoop.graph.importer.HandoffBundle.ObservationPin;
import com.zoop.graph.importer.HandoffBundle.Relation;
import com.zoop.graph.importer.HandoffBundle.SourcePin;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * The strict, closed validator of a {@code zoop-graph-handoff-bundle-2} and of its frozen manifest: a Java port of the
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
    static final String BUNDLE_SCHEMA = "zoop-graph-handoff-bundle-2";
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
    private static final Set<String> ASSERTION_STATUSES = Set.of("occurred", "announced", "planned", "forecast",
            "cancelled", "unknown");
    private static final int MAX_MENTIONS = 1_000;
    private static final int MAX_PARTICIPANTS = 1_000;

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
        for (String key : List.of("companies", "issues", "relations", "evidence", "articles")) {
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
                "sources", "companies", "issues", "relations", "evidence", "articles", "exclusions", "counts", "checks",
                "readiness", "digests"));
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
        need(executionMode.equals("replay") && recordingKind.equals("authored-test"));

        Obj policy = bundle.object("policy").exactly(Set.of("version", "files", "evidenceIdKind", "offsetUnit", "geography",
                "structural", "sequence"));
        String policyVersion = policy.string("version");
        need(POLICY.equals(policyVersion) && EVIDENCE_KIND.equals(policy.string("evidenceIdKind"))
                && OFFSET_UNIT.equals(policy.string("offsetUnit")));
        need("operator-field-verdict".equals(policy.string("geography")));
        need("manual-operator-review".equals(policy.string("structural")));
        need("s2-comparison-with-operator-decision".equals(policy.string("sequence")));
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
        Map<String, Set<String>> usedReviews = new HashMap<>();
        for (Obj source : sourceNodes) {
            source.exactly(Set.of("relation", "upstream", "reviewDigest", "policies", "reviewUsed", "audit"));
            Obj relation = source.object("relation").exactly(Set.of("jobId", "inputDigest"));
            String jobId = text(relation, "jobId", ID);
            String relationInput = text(relation, "inputDigest", HASH);
            Obj upstream = source.object("upstream").exactly(Set.of("jobId", "inputDigest", "digest"));
            String upstreamJob = text(upstream, "jobId", ID);
            String upstreamInput = text(upstream, "inputDigest", HASH);
            String upstreamDigest = text(upstream, "digest", HASH);
            String reviewDigest = text(source, "reviewDigest", HASH);
            Obj versions = source.object("policies").exactly(Set.of("producer", "verifier", "impactProducer",
                    "impactVerifier", "policy", "revalidationPolicy", "impactPolicy"));
            for (String name : versions.node().propertyNames()) {
                need(!versions.string(name).isEmpty());
            }
            JsonNode usedNodes = source.array("reviewUsed");
            need(usedNodes.size() <= MAX_RELATIONS);
            Set<String> used = new HashSet<>();
            for (JsonNode item : usedNodes.values()) {
                need(item.isArray() && item.size() == 2);
                JsonNode candidate = item.get(0);
                JsonNode revision = item.get(1);
                need(candidate.isString() && RC.matcher(candidate.stringValue()).matches());
                need(revision.isIntegralNumber() && revision.canConvertToInt() && revision.intValue() >= 1);
                need(used.add(candidate.stringValue()));
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
                    "publishedAt", "publicationPrecision", "observations"));
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
                    publishedAt, precision, observations));
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
            c.exactly(Set.of("id", "canonicalId", "label", "decisionRef"));
            String id = text(c, "id", ID);
            text(c, "canonicalId", ID);
            text(c, "decisionRef", ID);
            String label = c.string("label");
            need(!companies.containsKey(id));
            companies.put(id, new Company(id, label));
        }

        // issues --------------------------------------------------------------------------------------------------------
        Map<String, Issue> issues = new LinkedHashMap<>();
        List<Obj> issueNodes = bundle.objects("issues");
        need(issueNodes.size() <= MAX_ISSUES);
        for (Obj i : issueNodes) {
            i.exactly(Set.of("id", "canonicalId", "title", "action", "target", "eventTime", "timePrecision", "period",
                    "assertionStatus", "geography", "evidenceIds", "sourceEvents", "mentions", "decisionRef",
                    "representative"));
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
            need(expectedEvidence.equals(new HashSet<>(evidenceIds)));
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
            need(!issues.containsKey(id) && !companies.containsKey(id));
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
        List<Obj> relationNodes = bundle.objects("relations");
        need(relationNodes.size() <= MAX_RELATIONS);
        for (Obj r : relationNodes) {
            r.exactly(Set.of("id", "type", "source", "target", "role", "assertionStatus", "evidenceIds", "basis",
                    "provenance", "decisionRef", "sourceRefs"));
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
                        "verifiedAt", "sourceArticles", "evidenceIds"));
                Obj sourceRelation = b.object("sourceRelation").exactly(Set.of("jobId", "relationCandidateId"));
                String jobId = text(sourceRelation, "jobId", ID);
                String candidate = text(sourceRelation, "relationCandidateId", RC);
                need(jobs.contains(jobId) && usedReviews.get(jobId).contains(candidate));
                basisRefs.add("s3-relation\n" + jobId + "\n" + candidate);
                String relationKey = text(b, "relationKey", HASH);
                relationKeys.add(relationKey);
                need("SUPPLIES".equals(b.string("relationType")));
                String verifiedAt = b.string("verifiedAt");
                String validFrom = b.stringOrNull("validFrom");
                String validUntil = b.stringOrNull("validUntil");
                strings(b, "countries", 10);
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
                            && usedReviews.get(jobId).contains(refId));
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
                    need("s3-relation".equals(provenance.string("origin"))
                            && "independent-verifier-supported-all-claims".equals(provenance.string("s3SemanticValidation")));
                    need(r.isNull("decisionRef") && r.isNull("role") && basisNodes.isEmpty());
                }
                case "STRUCTURALLY_RELATED_TO" -> {
                    provenance.exactly(Set.of("origin", "s3SemanticValidation", "status", "reviewer", "decisionRef",
                            "decisionVersion", "bindingDigest", "basisEligibility"));
                    need("manual-operator-review".equals(provenance.string("origin"))
                            && "none".equals(provenance.string("s3SemanticValidation"))
                            && "operator-asserted".equals(provenance.string("status"))
                            && "s3-independent-verifier-supported-all-claims".equals(provenance.string("basisEligibility")));
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
            need(id.equals("edge-" + Canonical.digest(preimage)));
            relations.add(new Relation(id, type, source, target, role, assertionStatus, evidenceIds, basis,
                    provenance.string("origin")));
        }
        need(issues.keySet().equals(linkedIssues));
        need(companies.keySet().equals(linkedCompanies));
        need(evidence.keySet().equals(referenced));

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

        Obj counts = bundle.object("counts").exactly(Set.of("companies", "issues", "relations", "evidence", "articles",
                "exclusions"));
        need(counts.count("companies") == companies.size() && counts.count("issues") == issues.size()
                && counts.count("evidence") == evidence.size() && counts.count("articles") == articles.size()
                && counts.count("exclusions") == items.size());
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

        return new HandoffBundle(handoffId, manifestDigest, sourceKind, executionMode, recordingKind, policyVersion, files,
                pins, new ArrayList<>(companies.values()), new ArrayList<>(issues.values()), relations,
                new ArrayList<>(evidence.values()), new ArrayList<>(articles.values()));
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

    private static String articleKey(String articleId, String version) {
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
