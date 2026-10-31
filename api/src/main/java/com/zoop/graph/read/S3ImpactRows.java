package com.zoop.graph.read;

import java.util.*;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.briefing.impact.BriefingImpacts.Provenance;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Relation;
import com.zoop.graph.publication.GraphPublicationReader.Publication;

/** Version-bound retained S3 data. Labels are recomputed; distinct source verdicts are never aggregated. */
final class S3ImpactRows {
    static final List<String> SIDES = List.of("positive", "negative", "neutral", "uncertain");
    private static final Set<String> KEYS = Set.of("edgeId", "issueId", "companyId", "sourceRelation", "impactCandidateId",
            "status", "code", "label", "targetVerdict", "effects", "verifier", "verifierRequestDigest", "proposal");
    private static final Set<String> STATES = Set.of("verified", "not-applicable", "not-proposed", "no-evidence",
            "technical-reject", "verifier-reject", "withheld");
    record Row(String key, String relationId, String companyId, String status, String label,
            Provenance provenance, Map<String, String> effects) { }

    static List<Row> read(Publication publication, List<Relation> visible) {
        List<Row> result = new ArrayList<>();
        for (Relation relation : visible) {
            if (!"INVOLVES".equals(relation.relationType())) continue;
            var owners = publication.relationSources().get(relation.relationId());
            need(owners != null && owners.publicSource().equals(relation.source())
                    && owners.publicTarget().equals(relation.target()));
            for (var owner : publication.selectedRelationSources(relation.relationId())) {
                var source = publication.source(owner.sourceVersionId());
                if ("legacy-real".equals(source.sourceKind())) continue;
                Relation original = source.projection().relations().stream()
                        .filter(r -> owner.relationId().equals(r.relationId())).findFirst().orElseThrow(StrictJson.Malformed::new);
                need("INVOLVES".equals(original.relationType())
                        && publication.publicIssue(source.issueRef(original.source())).equals(relation.source())
                        && original.target().equals(relation.target()));
                for (Row row : read(source.bundle(), List.of(original))) {
                    result.add(new Row(publication.composed() ? source.sourceVersionId() + "\n" + row.key() : row.key(),
                            relation.relationId(), relation.target(), row.status(), row.label(), row.provenance(), row.effects()));
                }
            }
        }
        return List.copyOf(result);
    }

    static List<Row> read(Obj bundle, List<Relation> visible) {
        String schema = bundle.string("schemaVersion");
        if (com.zoop.graph.importer.LegacyRealPackage.isBundleSchema(schema)) return List.of();
        if (!Set.of("zoop-graph-handoff-bundle-6", "zoop-graph-handoff-bundle-7", "zoop-graph-handoff-bundle-8",
                "zoop-graph-handoff-bundle-9").contains(schema)) {
            // Legacy receipts predate impacts. An unknown future shape is not a missing assessment.
            if (Set.of("zoop-graph-handoff-bundle-1", "zoop-graph-handoff-bundle-2", "zoop-graph-handoff-bundle-3",
                    "zoop-graph-handoff-bundle-4", "zoop-graph-handoff-bundle-5").contains(schema)) return List.of();
            throw new StrictJson.Malformed();
        }
        Map<String, Obj> relations = index(bundle.objects("relations"), "id");
        Map<String, Obj> evidence = index(bundle.objects("evidence"), "id");
        Map<String, Obj> sources = new HashMap<>();
        for (Obj source : bundle.objects("sources"))
            need(sources.putIfAbsent(source.object("relation").string("jobId"), source) == null);
        List<Row> result = new ArrayList<>();
        for (Relation ref : visible) {
            if (!"INVOLVES".equals(ref.relationType())) continue;
            Obj relation = relations.get(ref.relationId());
            need(relation != null && "INVOLVES".equals(relation.string("type"))
                    && ref.source().equals(relation.string("source")) && ref.target().equals(relation.string("target")));
            Set<String> expected = new HashSet<>(), seen = new HashSet<>();
            for (Obj source : relation.objects("sourceRefs"))
                need(expected.add(source.string("jobId") + "\n" + source.string("id")));
            Set<String> articleVersions = new HashSet<>();
            for (String id : relation.strings("evidenceIds")) {
                Obj quote = evidence.get(id); need(quote != null);
                articleVersions.add(article(quote));
            }
            for (Obj row : bundle.objects("impacts")) {
                if (!ref.relationId().equals(row.string("edgeId"))) continue;
                row.exactly(KEYS);
                need(ref.source().equals(row.string("issueId")) && ref.target().equals(row.string("companyId")));
                Obj source = row.object("sourceRelation").exactly(Set.of("jobId", "relationCandidateId"));
                String key = source.string("jobId") + "\n" + source.string("relationCandidateId");
                need(expected.contains(key) && seen.add(key));
                Obj job = sources.get(source.string("jobId")); need(job != null);
                need(job.objects("reviewUsed").stream().anyMatch(r -> source.string("relationCandidateId").equals(r.string("relationCandidateId"))));
                Obj p = job.object("provenance").exactly(Set.of("sourceKind", "executionMode", "recordingKind"));
                var provenance = new Provenance(p.string("sourceKind"), p.string("executionMode"), p.string("recordingKind"));
                need(Set.of("collected", "synthetic").contains(provenance.sourceKind())
                        && (("live".equals(provenance.executionMode()) && "provider".equals(provenance.recordingKind()))
                            || ("replay".equals(provenance.executionMode()) && "authored-test".equals(provenance.recordingKind()))));
                String state = row.string("status"); need(STATES.contains(state));
                Map<String, String> effects = new LinkedHashMap<>();
                String label = null;
                if ("verified".equals(state)) {
                    need("called".equals(row.string("verifier")) && StrictJson.SHA256.matcher(row.string("verifierRequestDigest")).matches());
                    String verdict = row.string("targetVerdict"); need(Set.of("supported", "insufficient").contains(verdict));
                    Obj sides = row.object("effects").exactly(Set.copyOf(SIDES));
                    for (String side : SIDES) for (String id : sides.strings(side)) {
                        Obj quote = evidence.get(id); need(quote != null && articleVersions.contains(article(quote)));
                        need(effects.putIfAbsent(id, side) == null);
                    }
                    need(!effects.isEmpty() && effects.size() <= 40);
                    label = "insufficient".equals(verdict) || effects.containsValue("uncertain") ? "undetermined"
                            : effects.containsValue("positive") && effects.containsValue("negative") ? "mixed"
                            : effects.containsValue("positive") ? "positive" : effects.containsValue("negative") ? "negative" : "undetermined";
                    need(label.equals(row.string("label")));
                } else {
                    need(row.raw("label").isNull() && row.raw("effects").isNull());
                }
                result.add(new Row(key, ref.relationId(), ref.target(), state, label, provenance, effects));
            }
            need(seen.equals(expected));
        }
        return List.copyOf(result);
    }

    private static Map<String, Obj> index(List<Obj> values, String key) {
        Map<String, Obj> result = new HashMap<>();
        for (Obj value : values) need(result.putIfAbsent(value.string(key), value) == null);
        return result;
    }
    private static String article(Obj e) { return e.string("articleId") + "\n" + e.string("articleVersion"); }
    private static void need(boolean yes) { if (!yes) throw new StrictJson.Malformed(); }
}
