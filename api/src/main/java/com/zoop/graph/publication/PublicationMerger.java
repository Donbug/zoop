package com.zoop.graph.publication;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.function.Function;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.graph.publication.GraphPublicationReader.Contribution;
import com.zoop.graph.publication.GraphPublicationReader.IssueOwners;
import com.zoop.graph.publication.GraphPublicationReader.IssueRef;
import com.zoop.graph.publication.GraphPublicationReader.RelationOwners;
import com.zoop.graph.publication.GraphPublicationReader.RelationRef;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Issue;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Relation;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

/** Exact union of admitted projections, with explicit field ownership for every headline. */
public final class PublicationMerger {
    public static final String DECISIONS_SCHEMA = "zoop-graph-publication-decisions-1";
    public static final List<String> FIELDS = List.of("label", "action", "target", "assertionStatus", "eventTime", "period", "geography");
    private static final Comparator<IssueRef> ISSUE_ORDER = Comparator.comparing(IssueRef::sourceVersionId).thenComparing(IssueRef::issueId);
    private static final Comparator<RelationRef> RELATION_ORDER = Comparator.comparing(RelationRef::sourceVersionId).thenComparing(RelationRef::relationId);

    private PublicationMerger() {}

    public record Merged(List<PublicGraphSnapshot.Company> companies, List<Issue> issues, List<Relation> relations,
            List<PublicGraphSnapshot.Article> articles, List<PublicGraphSnapshot.Evidence> evidence,
            Map<String, IssueOwners> issueSources, Map<String, RelationOwners> relationSources) {
        public PublicGraphSnapshot snapshot(String versionId, String publicationId) {
            int format = issues.stream().anyMatch(Issue::hasExplicitUnknownGeography)
                    ? PublicGraphSnapshot.EXPLICIT_UNKNOWN_FORMAT : PublicGraphSnapshot.FORMAT;
            return new PublicGraphSnapshot(format, versionId, publicationId, companies, issues, relations, articles, evidence);
        }
    }

    public static Obj emptyDecisions() {
        ObjectNode root = StrictJson.newObject(); root.put("schemaVersion", DECISIONS_SCHEMA);
        root.putArray("issueMappings"); root.putArray("fieldSelections"); root.putArray("relationSelections");
        return Obj.of(root);
    }

    public static Obj combine(Obj previous, Obj incoming) {
        validateRoot(previous); validateRoot(incoming);
        ObjectNode root = StrictJson.newObject(); root.put("schemaVersion", DECISIONS_SCHEMA);
        for (String collection : List.of("issueMappings", "fieldSelections", "relationSelections")) {
            Map<String, JsonNode> items = new TreeMap<>();
            for (Obj item : previous.objects(collection)) items.put(decisionKey(collection, item), item.node());
            Set<String> supplied = new HashSet<>();
            for (Obj item : incoming.objects(collection)) {
                String key = decisionKey(collection, item);
                if (!supplied.add(key)) throw failure("request_invalid");
                if ("issueMappings".equals(collection) && items.containsKey(key) && !items.get(key).equals(item.node()))
                    throw failure("identity_conflict");
                items.put(key, item.node());
            }
            var array = root.putArray(collection); items.values().forEach(array::add);
        }
        return Obj.of(root);
    }

    private static String decisionKey(String collection, Obj item) {
        return switch (collection) {
            case "issueMappings" -> Canonical.write(item.raw("from"));
            case "fieldSelections" -> item.string("issueId") + "\n" + item.string("field");
            case "relationSelections" -> item.string("relationId");
            default -> throw new IllegalArgumentException(collection);
        };
    }

    public static Merged merge(List<Contribution> contributions, Obj decisions, Set<String> alreadyPublicIds) {
        return merge(contributions, decisions, alreadyPublicIds, Map.of());
    }

    public static Merged merge(List<Contribution> contributions, Obj decisions, Set<String> alreadyPublicIds,
            Map<String, IssueOwners> previousOwners) {
        validateRoot(decisions);
        Index index = index(contributions);
        Map<String, Contribution> sources = index.sources();
        Map<IssueRef, Issue> originals = index.originals();
        Map<RelationRef, Relation> originalRelations = index.relations();
        Map<IssueRef, IssueRef> mappings = new HashMap<>();
        for (Obj mapping : decisions.objects("issueMappings")) {
            mapping.exactly(Set.of("from", "to", "decision", "evidenceRefs", "reviewer", "decisionRef", "decisionVersion"));
            audit(mapping);
            IssueRef from = issueRef(mapping.object("from")); IssueRef to = issueRef(mapping.object("to"));
            if (!"same-event".equals(mapping.string("decision")) || from.equals(to) || !originals.containsKey(from)
                    || !originals.containsKey(to) || mappings.put(from, to) != null) throw failure("identity_conflict");
            if (!from.issueId().equals(to.issueId()) && alreadyPublicIds.contains(from.issueId())) throw failure("identity_conflict");
            Issue left = originals.get(from); Issue right = originals.get(to);
            if (!Objects.equals(left.action(), right.action()) || !Objects.equals(left.assertionStatus(), right.assertionStatus())
                    || !companyIds(sources.get(from.sourceVersionId()), from.issueId()).equals(companyIds(sources.get(to.sourceVersionId()), to.issueId()))
                    || companyIds(sources.get(from.sourceVersionId()), from.issueId()).isEmpty()) throw failure("mapping_unproven");
            Set<IssueRef> grounded = evidenceRefs(mapping, originals, sources);
            if (!grounded.containsAll(Set.of(from, to))) throw failure("mapping_unproven");
        }
        Map<IssueRef, String> publicIds = new HashMap<>();
        Map<String, String> identityTargets = new HashMap<>();
        for (IssueRef ref : originals.keySet()) {
            IssueRef target = resolve(ref, mappings);
            publicIds.put(ref, target.issueId());
            String previous = identityTargets.putIfAbsent(ref.issueId(), target.issueId());
            if (previous != null && !previous.equals(target.issueId())) throw failure("identity_conflict");
        }
        Map<String, List<IssueRef>> groups = new TreeMap<>();
        publicIds.forEach((ref, id) -> groups.computeIfAbsent(id, ignored -> new ArrayList<>()).add(ref));
        groups.values().forEach(list -> list.sort(ISSUE_ORDER));
        Map<String, Obj> fields = indexed(decisions.objects("fieldSelections"), o -> o.string("issueId") + "\n" + o.string("field"));
        Set<String> usedFields = new HashSet<>();
        Map<String, IssueOwners> issueOwners = new TreeMap<>();
        List<Issue> issues = new ArrayList<>();
        for (var group : groups.entrySet()) {
            String publicId = group.getKey(); List<IssueRef> members = group.getValue();
            Issue first = originals.get(members.getFirst());
            if (members.stream().anyMatch(ref -> !first.equals(originals.get(ref)))
                    && members.stream().noneMatch(mappings::containsKey)
                    && FIELDS.stream().noneMatch(field -> fields.containsKey(publicId + "\n" + field)))
                throw failure("correction_required");
            Map<String, IssueRef> owners = new TreeMap<>();
            for (String field : FIELDS) {
                Obj choice = fields.get(publicId + "\n" + field);
                IssueRef owner = defaultOwner(publicId, members, mappings);
                IssueOwners previous = previousOwners.get(publicId);
                if (previous != null) {
                    owner = previous.headlineSources().get(field);
                    if (owner == null || !members.contains(owner)) throw failure("basis_mismatch");
                }
                JsonNode initial = field(originals.get(owner), field);
                boolean conflict = members.stream().anyMatch(r -> !field(originals.get(r), field).equals(initial));
                if (choice == null && conflict) throw failure("correction_required");
                if (choice != null) {
                    usedFields.add(publicId + "\n" + field);
                    choice.exactly(Set.of("issueId", "field", "expectedValueDigest", "takeFrom", "evidenceRefs", "reviewer", "decisionRef", "decisionVersion"));
                    audit(choice);
                    IssueRef selected = issueRef(choice.object("takeFrom"));
                    if (!members.contains(selected)) throw failure("mapping_unproven");
                    String expected = choice.string("expectedValueDigest");
                    if (!StrictJson.SHA256.matcher(expected).matches() || members.stream()
                            .noneMatch(r -> expected.equals(Canonical.digest(field(originals.get(r), field))))) throw failure("identity_conflict");
                    if (!evidenceRefs(choice, originals, sources).contains(selected)) throw failure("mapping_unproven");
                    owner = selected;
                }
                owners.put(field, owner);
            }
            Issue headline = originals.get(owners.get("label"));
            Issue time = originals.get(owners.get("eventTime")); Issue geo = originals.get(owners.get("geography"));
            TreeSet<String> articleIds = new TreeSet<>(); TreeSet<String> evidenceIds = new TreeSet<>();
            Map<String, PublicGraphSnapshot.MentionRef> mentions = new TreeMap<>();
            List<String> times = new ArrayList<>();
            for (IssueRef ref : members) {
                Issue issue = originals.get(ref); articleIds.addAll(issue.articleIds()); evidenceIds.addAll(issue.evidenceIds());
                issue.mentions().forEach(m -> exact(mentions, m.mentionId(), m));
                times.add(issue.latestPublishedAt());
            }
            String latest = com.zoop.graph.importer.HandoffSnapshotWriter.latestPublished(times);
            issues.add(new Issue(publicId, headline.label(), time.eventTime(), time.timePrecision(), originals.get(owners.get("period")).period(),
                    originals.get(owners.get("assertionStatus")).assertionStatus(), originals.get(owners.get("action")).action(),
                    originals.get(owners.get("target")).target(), geo.geography(), geo.geographyPolicyVersion(), geo.geographyEvidenceIds(),
                    List.copyOf(articleIds), List.copyOf(evidenceIds), List.copyOf(mentions.values()), headline.representativeMentionId(), latest));
            issueOwners.put(publicId, new IssueOwners(publicId, members, owners));
        }
        if (!usedFields.equals(fields.keySet())) throw failure("mapping_unproven");
        Map<String, List<RelationRef>> relationGroups = new TreeMap<>();
        originalRelations.keySet().forEach(r -> relationGroups.computeIfAbsent(r.relationId(), ignored -> new ArrayList<>()).add(r));
        Map<String, Obj> selections = indexed(decisions.objects("relationSelections"), o -> o.string("relationId"));
        Set<String> usedRelations = new HashSet<>();
        Map<String, RelationOwners> relationOwners = new TreeMap<>(); List<Relation> relations = new ArrayList<>();
        Map<RelationRef, Relation> projectedRelations = new HashMap<>();
        originalRelations.forEach((ref, relation) -> {
            Relation projected = project(relation, ref, publicIds);
            if (projected.source() == null || projected.target() == null || projected.source().equals(projected.target())) throw failure("identity_conflict");
            projectedRelations.put(ref, projected);
        });
        Map<String, Issue> byPublicIssue = new HashMap<>();
        issues.forEach(issue -> byPublicIssue.put(issue.issueId(), issue));
        for (var group : relationGroups.entrySet()) {
            List<RelationRef> members = group.getValue(); members.sort(RELATION_ORDER);
            RelationRef selected = members.getFirst(); Relation baseline = originalRelations.get(selected);
            boolean conflict = members.stream().anyMatch(r -> !originalRelations.get(r).equals(baseline));
            Obj choice = selections.get(group.getKey());
            if (conflict && choice == null) throw failure("correction_required");
            if (choice != null) {
                usedRelations.add(group.getKey());
                choice.exactly(Set.of("relationId", "expectedValueDigest", "takeFrom", "evidenceRefs", "reviewer", "decisionRef", "decisionVersion"));
                audit(choice); selected = relationRef(choice.object("takeFrom"));
                if (!members.contains(selected) || members.stream().noneMatch(r -> choice.string("expectedValueDigest")
                        .equals(Canonical.digest(GraphPublicationReader.json(projectedRelations.get(r)))))) throw failure("identity_conflict");
                var grounded = evidenceRefs(choice, originals, sources);
                Relation chosen = originalRelations.get(selected);
                if (!grounded.contains(new IssueRef(selected.sourceVersionId(), chosen.source()))) throw failure("mapping_unproven");
                String selectedSource = selected.sourceVersionId();
                if (choice.objects("evidenceRefs").stream().noneMatch(e -> selectedSource.equals(e.string("sourceVersionId"))
                        && chosen.evidenceIds().contains(e.string("evidenceId")))) throw failure("mapping_unproven");
            }
            Relation chosen = originalRelations.get(selected);
            Relation projected = projectedRelations.get(selected);
            String source = projected.source(), target = projected.target();
            for (RelationRef member : members) {
                Relation original = projectedRelations.get(member);
                if (!source.equals(original.source()) || !target.equals(original.target())) throw failure("identity_conflict");
            }
            // Native structural applicability was proved for the original headline tuple, not an arbitrary mapped event.
            if ("STRUCTURALLY_RELATED_TO".equals(chosen.relationType()) && "native".equals(sources.get(selected.sourceVersionId()).sourceKind())) {
                Issue original = originals.get(new IssueRef(selected.sourceVersionId(), chosen.source()));
                Issue published = byPublicIssue.get(source);
                if (!field(original, "geography").equals(field(published, "geography"))
                        || !field(original, "eventTime").equals(field(published, "eventTime"))) throw failure("identity_conflict");
            }
            relations.add(projected);
            relationOwners.put(chosen.relationId(), new RelationOwners(chosen.relationId(), members, source, target));
        }
        if (!usedRelations.equals(selections.keySet())) throw failure("mapping_unproven");
        checkAcyclic(relations);
        var companies = union(contributions, s -> s.projection().companies(), PublicGraphSnapshot.Company::companyId);
        var articles = union(contributions, s -> s.projection().articles(), a -> a.articleId() + "\n" + a.version());
        var evidence = union(contributions, s -> s.projection().evidence(), PublicGraphSnapshot.Evidence::evidenceId);
        Set<String> companyIds = companies.stream().map(PublicGraphSnapshot.Company::companyId).collect(java.util.stream.Collectors.toSet());
        if (issues.stream().anyMatch(i -> companyIds.contains(i.issueId()))) throw failure("identity_conflict");
        return new Merged(companies, List.copyOf(issues), List.copyOf(relations), articles, evidence, Map.copyOf(issueOwners), Map.copyOf(relationOwners));
    }

    /** The reviewer recorded on decisions the automatic preparation proposes; people's decisions use any other reviewer. */
    public static final String AUTO_REVIEWER = "graph-publication-prepare";
    private static final String AUTO_DECISION_REF = "graph-publication-prepare:newest-native";
    private static final String AUTO_DECISION_VERSION = "1";

    /** The incoming sources of a prepared composition, oldest first. */
    public record Automatic(List<String> incomingOldestFirst) {
        public Automatic {
            incomingOldestFirst = List.copyOf(incomingOldestFirst);
            if (incomingOldestFirst.isEmpty() || Set.copyOf(incomingOldestFirst).size() != incomingOldestFirst.size()) throw failure("request_invalid");
        }
    }

    /** One published value the proposal replaces: {@code field} is null for a relation; digests are of the value before and after. */
    public record AutoResolution(String kind, String id, String field, String sourceVersionId, List<String> replacedSourceVersionIds,
            String previousValueDigest, String valueDigest) {
        public AutoResolution { replacedSourceVersionIds = List.copyOf(replacedSourceVersionIds); }
    }

    /** Decisions to compose with (a closed decisions document) and the published values they change. */
    public record Proposal(Obj decisions, List<AutoResolution> resolutions) {
        public Proposal { resolutions = List.copyOf(resolutions); }
    }

    /** True when an operator-supplied decisions document claims the automatic reviewer, which only the preparation may write. */
    public static boolean claimsAutomaticReviewer(Obj decisions) {
        for (String collection : List.of("issueMappings", "fieldSelections", "relationSelections"))
            for (Obj item : decisions.objects(collection))
                if (item.has("reviewer") && AUTO_REVIEWER.equals(item.string("reviewer"))) return true;
        return false;
    }

    /**
     * The decisions a prepared composition adds, so that {@link #merge} (and every later read of the publication) applies them like any
     * other decision. A public issue whose members are all native, that has an incoming member, whose incoming records agree with each
     * other, that has no issue mapping and none of whose headline fields a person decided takes the newest incoming value. A relation
     * takes the newest incoming record under the same conditions when no person selected it and neither endpoint issue was left to
     * people. Everything else gets no proposal and keeps the operator rules ({@code correction_required} where it disagrees): sources
     * admitted together have no order, and a legacy package, a mapping or a person's decision (reviewer other than
     * {@link #AUTO_REVIEWER}) is never overridden. An earlier automatic decision is replaced when newer incoming records disagree with
     * it. {@code expectedValueDigest} is the value published before, as the composer requires of every new decision.
     */
    public static Proposal propose(List<Contribution> contributions, Obj inherited, Map<String, IssueOwners> previousOwners, Automatic automatic) {
        validateRoot(inherited);
        Index index = index(contributions);
        Map<String, Integer> order = new HashMap<>();
        for (String id : automatic.incomingOldestFirst()) {
            if (!index.sources().containsKey(id)) throw failure("request_invalid");
            order.put(id, order.size());
        }
        Map<IssueRef, IssueRef> mappings = new HashMap<>();
        for (Obj mapping : inherited.objects("issueMappings")) mappings.put(issueRef(mapping.object("from")), issueRef(mapping.object("to")));
        Map<IssueRef, String> publicIds = new HashMap<>();
        Map<String, List<IssueRef>> groups = new TreeMap<>();
        for (IssueRef ref : index.originals().keySet()) {
            String id = resolve(ref, mappings).issueId();
            publicIds.put(ref, id); groups.computeIfAbsent(id, ignored -> new ArrayList<>()).add(ref);
        }
        groups.values().forEach(list -> list.sort(ISSUE_ORDER));
        Map<String, Obj> fields = indexed(inherited.objects("fieldSelections"), o -> o.string("issueId") + "\n" + o.string("field"));
        Map<String, Obj> selections = indexed(inherited.objects("relationSelections"), o -> o.string("relationId"));
        Map<IssueRef, Map<String, JsonNode>> values = new HashMap<>();
        Function<IssueRef, Map<String, JsonNode>> valuesOf = ref -> values.computeIfAbsent(ref, r -> {
            Map<String, JsonNode> fieldValues = new HashMap<>();
            for (String field : FIELDS) fieldValues.put(field, field(index.originals().get(r), field));
            return fieldValues;
        });
        ObjectNode root = (ObjectNode) emptyDecisions().node().deepCopy();
        var fieldOut = (tools.jackson.databind.node.ArrayNode) root.get("fieldSelections");
        var relationOut = (tools.jackson.databind.node.ArrayNode) root.get("relationSelections");
        List<AutoResolution> resolutions = new ArrayList<>();
        Set<String> leftToPeople = new HashSet<>();
        for (var group : groups.entrySet()) {
            String publicId = group.getKey(); List<IssueRef> members = group.getValue();
            if (members.stream().noneMatch(r -> order.containsKey(r.sourceVersionId()))) continue;
            IssueRef newest = newestAgreeing(members, order, index.sources(), IssueRef::sourceVersionId, index.originals()::get);
            boolean peopleDecided = FIELDS.stream().map(f -> fields.get(publicId + "\n" + f))
                    .anyMatch(choice -> choice != null && !AUTO_REVIEWER.equals(choice.string("reviewer")));
            if (newest == null || peopleDecided || members.stream().anyMatch(r -> mappings.containsKey(r) || mappings.containsValue(r))) {
                leftToPeople.add(publicId); continue;
            }
            if (members.stream().allMatch(r -> order.containsKey(r.sourceVersionId()))) continue;
            IssueOwners previous = previousOwners.get(publicId);
            Map<String, IssueRef> owners = new HashMap<>();
            for (String field : FIELDS) {
                Obj choice = fields.get(publicId + "\n" + field);
                IssueRef owner = choice != null ? issueRef(choice.object("takeFrom"))
                        : previous != null ? previous.headlineSources().get(field) : defaultOwner(publicId, members, mappings);
                if (owner == null || !index.originals().containsKey(owner)) owner = null;
                owners.put(field, owner);
            }
            if (owners.containsValue(null)) { leftToPeople.add(publicId); continue; }
            ObjectNode newestEvidence = issueEvidence(newest, index);
            List<ObjectNode> proposed = new ArrayList<>();
            for (String field : FIELDS) {
                boolean inheritedChoice = fields.containsKey(publicId + "\n" + field);
                IssueRef owner = owners.get(field);
                JsonNode before = valuesOf.apply(owner).get(field), after = valuesOf.apply(newest).get(field);
                boolean fieldDiffers = members.stream().anyMatch(r -> !valuesOf.apply(r).get(field).equals(after));
                if (before.equals(after) && (inheritedChoice || !fieldDiffers)) continue;
                if (newestEvidence == null) { proposed = null; break; }
                proposed.add(selection(publicId, field, Canonical.digest(before), newest, newestEvidence));
                if (!before.equals(after)) resolutions.add(new AutoResolution("issue", publicId, field, newest.sourceVersionId(),
                        replaced(members, r -> valuesOf.apply(r).get(field), after, IssueRef::sourceVersionId), Canonical.digest(before), Canonical.digest(after)));
            }
            if (proposed == null) { leftToPeople.add(publicId); resolutions.removeIf(r -> "issue".equals(r.kind()) && r.id().equals(publicId)); continue; }
            Issue newestIssue = index.originals().get(newest);
            boolean recordsDiffer = members.stream().anyMatch(r -> !index.originals().get(r).equals(newestIssue));
            if (recordsDiffer && proposed.isEmpty() && FIELDS.stream().noneMatch(f -> fields.containsKey(publicId + "\n" + f))) {
                // Records that differ only outside the headline fields (evidence, mentions) still need one decision to be merged; it
                // keeps the published owner, so nothing published changes except the union of the parts' evidence.
                IssueRef owner = owners.get("label");
                ObjectNode ownerEvidence = issueEvidence(owner, index);
                if (ownerEvidence == null) { leftToPeople.add(publicId); continue; }
                proposed.add(selection(publicId, "label", Canonical.digest(valuesOf.apply(owner).get("label")), owner, ownerEvidence));
            }
            proposed.forEach(fieldOut::add);
        }
        Map<String, List<RelationRef>> relationGroups = new TreeMap<>();
        index.relations().keySet().forEach(r -> relationGroups.computeIfAbsent(r.relationId(), ignored -> new ArrayList<>()).add(r));
        for (var group : relationGroups.entrySet()) {
            List<RelationRef> members = group.getValue(); members.sort(RELATION_ORDER);
            Obj choice = selections.get(group.getKey());
            if (choice != null && !AUTO_REVIEWER.equals(choice.string("reviewer"))) continue;
            RelationRef newest = newestAgreeing(members, order, index.sources(), RelationRef::sourceVersionId, index.relations()::get);
            if (newest == null) continue;
            Function<RelationRef, Relation> projected = r -> project(index.relations().get(r), r, publicIds);
            Relation chosenProjection = projected.apply(newest);
            if (chosenProjection.source() == null || leftToPeople.contains(chosenProjection.source())
                    || ("FOLLOWS".equals(chosenProjection.relationType()) && leftToPeople.contains(chosenProjection.target()))) continue;
            RelationRef previous = choice != null ? relationRef(choice.object("takeFrom"))
                    : members.stream().filter(r -> !order.containsKey(r.sourceVersionId())).findFirst().orElse(null);
            if (previous == null || !index.relations().containsKey(previous)) continue;
            JsonNode before = GraphPublicationReader.json(projected.apply(previous)), after = GraphPublicationReader.json(chosenProjection);
            Relation chosen = index.relations().get(newest);
            boolean differs = members.stream().anyMatch(r -> !index.relations().get(r).equals(chosen));
            if (before.equals(after) && (choice != null || !differs)) continue;
            IssueRef owner = new IssueRef(newest.sourceVersionId(), chosen.source());
            Issue issue = index.originals().get(owner);
            Set<String> known = index.evidence().get(owner.sourceVersionId());
            String evidenceId = issue == null ? null
                    : chosen.evidenceIds().stream().filter(e -> issue.evidenceIds().contains(e) && known.contains(e)).findFirst().orElse(null);
            if (evidenceId == null) continue;
            ObjectNode out = relationOut.addObject();
            out.put("relationId", group.getKey()); out.put("expectedValueDigest", Canonical.digest(before));
            out.set("takeFrom", GraphPublicationReader.json(newest));
            ObjectNode ref = out.putArray("evidenceRefs").addObject();
            ref.put("sourceVersionId", owner.sourceVersionId()); ref.put("issueId", owner.issueId()); ref.put("evidenceId", evidenceId);
            autoAudit(out);
            if (!before.equals(after)) resolutions.add(new AutoResolution("relation", group.getKey(), null, newest.sourceVersionId(),
                    replaced(members, r -> GraphPublicationReader.json(projected.apply(r)), after, RelationRef::sourceVersionId),
                    Canonical.digest(before), Canonical.digest(after)));
        }
        resolutions.sort(Comparator.comparing(AutoResolution::kind).thenComparing(AutoResolution::id)
                .thenComparing(r -> r.field() == null ? "" : r.field()));
        return new Proposal(Obj.of(root), resolutions);
    }

    private record Index(Map<String, Contribution> sources, Map<IssueRef, Issue> originals, Map<RelationRef, Relation> relations,
            Map<String, Set<String>> evidence) {}

    private static Index index(List<Contribution> contributions) {
        Map<String, Contribution> sources = new HashMap<>();
        Map<IssueRef, Issue> originals = new HashMap<>();
        Map<RelationRef, Relation> relations = new HashMap<>();
        Map<String, Set<String>> evidence = new HashMap<>();
        for (Contribution source : contributions) {
            if (sources.put(source.sourceVersionId(), source) != null) throw failure("source_conflict");
            for (Issue issue : source.projection().issues()) originals.put(source.issueRef(issue.issueId()), issue);
            for (Relation relation : source.projection().relations()) relations.put(new RelationRef(source.sourceVersionId(), relation.relationId()), relation);
            Set<String> ids = new HashSet<>();
            source.projection().evidence().forEach(e -> ids.add(e.evidenceId()));
            evidence.put(source.sourceVersionId(), ids);
        }
        return new Index(sources, originals, relations, evidence);
    }

    /** The headline owner of a group nobody decided: the member that carries the public id itself, else the first member. */
    private static IssueRef defaultOwner(String publicId, List<IssueRef> members, Map<IssueRef, IssueRef> mappings) {
        return members.stream().filter(r -> r.issueId().equals(publicId) && !mappings.containsKey(r)).findFirst().orElse(members.getFirst());
    }

    /** A relation with its issue endpoints renamed to public ids; an endpoint outside the merge is null. */
    private static Relation project(Relation relation, RelationRef ref, Map<IssueRef, String> publicIds) {
        String source = publicIds.get(new IssueRef(ref.sourceVersionId(), relation.source()));
        String target = "FOLLOWS".equals(relation.relationType()) ? publicIds.get(new IssueRef(ref.sourceVersionId(), relation.target())) : relation.target();
        return new Relation(relation.relationId(), relation.relationType(), source, target, relation.role(), relation.assertionStatus(),
                relation.evidenceIds(), relation.basis());
    }

    private static <R, V> R newestAgreeing(List<R> members, Map<String, Integer> order, Map<String, Contribution> sources,
            Function<R, String> sourceOf, Function<R, V> value) {
        List<R> incoming = members.stream().filter(r -> order.containsKey(sourceOf.apply(r)))
                .sorted(Comparator.comparing(r -> order.get(sourceOf.apply(r)))).toList();
        if (incoming.isEmpty() || members.stream().anyMatch(r -> !"native".equals(sources.get(sourceOf.apply(r)).sourceKind()))) return null;
        V agreed = value.apply(incoming.getFirst());
        return incoming.stream().allMatch(r -> agreed.equals(value.apply(r))) ? incoming.getLast() : null;
    }
    private static <R> List<String> replaced(List<R> members, Function<R, JsonNode> value, JsonNode after, Function<R, String> sourceOf) {
        return members.stream().filter(r -> !value.apply(r).equals(after)).map(sourceOf).distinct().sorted().toList();
    }
    private static ObjectNode issueEvidence(IssueRef ref, Index index) {
        Set<String> known = index.evidence().get(ref.sourceVersionId());
        String id = index.originals().get(ref).evidenceIds().stream().filter(known::contains).findFirst().orElse(null);
        if (id == null) return null;
        ObjectNode node = StrictJson.newObject();
        node.put("sourceVersionId", ref.sourceVersionId()); node.put("issueId", ref.issueId()); node.put("evidenceId", id);
        return node;
    }
    private static ObjectNode selection(String issueId, String field, String expected, IssueRef takeFrom, ObjectNode evidence) {
        ObjectNode out = StrictJson.newObject();
        out.put("issueId", issueId); out.put("field", field); out.put("expectedValueDigest", expected);
        out.set("takeFrom", GraphPublicationReader.json(takeFrom)); out.putArray("evidenceRefs").add(evidence.deepCopy());
        autoAudit(out);
        return out;
    }
    private static void autoAudit(ObjectNode node) {
        node.put("reviewer", AUTO_REVIEWER); node.put("decisionRef", AUTO_DECISION_REF); node.put("decisionVersion", AUTO_DECISION_VERSION);
    }

    public static JsonNode field(Issue issue, String field) {
        JsonNode json = GraphPublicationReader.json(issue);
        if ("eventTime".equals(field)) {
            ObjectNode tuple = StrictJson.newObject(); tuple.set("eventTime", json.get("eventTime")); tuple.set("timePrecision", json.get("timePrecision")); return tuple;
        }
        if ("geography".equals(field)) {
            ObjectNode tuple = StrictJson.newObject();
            for (String key : List.of("geography", "geographyPolicyVersion", "geographyEvidenceIds")) tuple.set(key, json.get(key));
            return tuple;
        }
        if (!FIELDS.contains(field)) throw failure("request_invalid");
        return json.get(field);
    }

    private static Set<IssueRef> evidenceRefs(Obj decision, Map<IssueRef, Issue> issues, Map<String, Contribution> sources) {
        Set<IssueRef> grounded = new HashSet<>(); Set<String> unique = new HashSet<>();
        for (Obj ref : decision.objects("evidenceRefs")) {
            ref.exactly(Set.of("sourceVersionId", "issueId", "evidenceId"));
            IssueRef issueRef = new IssueRef(ref.string("sourceVersionId"), ref.string("issueId"));
            Issue issue = issues.get(issueRef);
            if (issue == null || !issue.evidenceIds().contains(ref.string("evidenceId"))
                    || !unique.add(Canonical.write(ref.node())) || sources.get(issueRef.sourceVersionId()).projection().evidence().stream()
                    .noneMatch(e -> e.evidenceId().equals(ref.string("evidenceId")))) throw failure("mapping_unproven");
            grounded.add(issueRef);
        }
        if (grounded.isEmpty()) throw failure("mapping_unproven");
        return grounded;
    }

    private static Set<String> companyIds(Contribution source, String issueId) {
        Set<String> ids = new TreeSet<>(); source.projection().relations().stream()
                .filter(r -> r.source().equals(issueId) && "INVOLVES".equals(r.relationType())).forEach(r -> ids.add(r.target()));
        return ids;
    }

    private static IssueRef resolve(IssueRef ref, Map<IssueRef, IssueRef> mappings) {
        Set<IssueRef> seen = new HashSet<>();
        while (mappings.containsKey(ref)) { if (!seen.add(ref)) throw failure("identity_conflict"); ref = mappings.get(ref); }
        return ref;
    }

    public static IssueRef issueRef(Obj value) {
        value.exactly(Set.of("sourceVersionId", "issueId")); return new IssueRef(value.string("sourceVersionId"), value.string("issueId"));
    }
    public static RelationRef relationRef(Obj value) {
        value.exactly(Set.of("sourceVersionId", "relationId")); return new RelationRef(value.string("sourceVersionId"), value.string("relationId"));
    }
    private static void validateRoot(Obj root) {
        root.exactly(Set.of("schemaVersion", "issueMappings", "fieldSelections", "relationSelections"));
        if (!DECISIONS_SCHEMA.equals(root.string("schemaVersion"))) throw failure("request_invalid");
    }
    private static void audit(Obj item) {
        for (String key : List.of("reviewer", "decisionRef", "decisionVersion")) {
            String text = item.string(key);
            if (text.isBlank() || text.codePoints().anyMatch(Character::isISOControl)) throw failure("request_invalid");
        }
    }
    private static <T> List<T> union(List<Contribution> sources, Function<Contribution, List<T>> items, Function<T, String> key) {
        Map<String, T> values = new TreeMap<>();
        for (Contribution source : sources) for (T item : items.apply(source)) exact(values, key.apply(item), item);
        return List.copyOf(values.values());
    }
    private static <T> void exact(Map<String, T> items, String key, T value) {
        T previous = items.putIfAbsent(key, value);
        if (previous != null && !previous.equals(value)) throw failure("identity_conflict");
    }
    private static Map<String, Obj> indexed(List<Obj> items, Function<Obj, String> key) {
        Map<String, Obj> result = new HashMap<>();
        for (Obj item : items) if (result.put(key.apply(item), item) != null) throw failure("request_invalid");
        return result;
    }
    private static void checkAcyclic(List<Relation> relations) {
        Map<String, Set<String>> edges = new HashMap<>(); Map<String, Integer> indegree = new HashMap<>();
        for (Relation relation : relations) if ("FOLLOWS".equals(relation.relationType())) {
            indegree.putIfAbsent(relation.source(), 0);
            if (edges.computeIfAbsent(relation.source(), ignored -> new HashSet<>()).add(relation.target())) indegree.merge(relation.target(), 1, Integer::sum);
        }
        var queue = new java.util.ArrayDeque<String>(); indegree.forEach((id, count) -> { if (count == 0) queue.add(id); });
        int visited = 0;
        while (!queue.isEmpty()) {
            String id = queue.remove(); visited++;
            for (String target : edges.getOrDefault(id, Set.of())) if (indegree.compute(target, (key, count) -> count - 1) == 0) queue.add(target);
        }
        if (visited != indegree.size()) throw failure("identity_conflict");
    }
    private static PublicationException failure(String code) { return new PublicationException(code); }
}
