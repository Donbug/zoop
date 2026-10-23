package com.zoop.document.evidence.service;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.document.evidence.graph.GraphEvidence.ImpactRef;

/**
 * The one fact the public graph evidence read takes from a graph import's {@code verification_receipt} for an IMPACT-ONLY span: that
 * a visible INVOLVES relation (company to event) has a {@code verified} impact row whose verifier-mapped quote effects list the
 * evidence id. The pinned snapshot carries no impact; it only says which visible INVOLVES relations cite the span's article
 * version ({@link ImpactRef}). The receipt is retained data, never authority: it decides membership only, and every current-rights,
 * row, text, availability and access gate of the read still applies. Nothing of the row (label, effects, proposal, verifier digest)
 * is read out: the evidence read answers with the quote and the visible issues only.
 *
 * <p>The receipt is the already-verified bundle of exactly the graph version being served ({@link GraphReceiptGrants#bundle}). A
 * receipt without an {@code impacts} key (bundle {@code -1} to {@code -5}) proves nothing: {@code false}, never an error and
 * never read as "not proposed". Otherwise, for each candidate reference exactly one bundle relation must carry its id and equal its
 * type, source and target; every impact row of that relation must be a closed row of that issue and company whose
 * {@code sourceRelation} is one of the relation's own {@code sourceRefs}; and no source relation may be listed twice. A missing,
 * duplicated or mismatching relation, row or source relation makes the whole receipt {@link GraphReceiptGrants.Malformed} for this
 * read (fail closed, never "the other candidate was fine"). The evidence is served when at least one such row is {@code verified}
 * and lists the id in one of its effect sides; every other state (not proposed, no evidence, rejected, withheld) proves nothing.
 * A valid receipt that simply does not prove membership returns {@code false}; structural malformation always throws, so the caller
 * evaluates this seam and {@link GraphReceiptBasis} both before it combines them.
 */
final class GraphReceiptImpact {
    private static final Set<String> ROW = Set.of("edgeId", "issueId", "companyId", "sourceRelation", "impactCandidateId", "status",
            "code", "label", "targetVerdict", "effects", "verifier", "verifierRequestDigest", "proposal");
    private static final Set<String> SIDES = Set.of("positive", "negative", "neutral", "uncertain");

    private GraphReceiptImpact() {
    }

    /**
     * @return whether a referenced INVOLVES relation of the receipt has a verified impact row listing {@code evidenceId}; false when
     *         there is no reference, the receipt has no {@code impacts}, or no row does
     * @throws GraphReceiptGrants.Malformed when a referenced relation or one of its impact rows is missing, duplicated or malformed
     */
    static boolean proves(Obj bundle, String evidenceId, List<ImpactRef> refs) {
        if (refs.isEmpty() || !bundle.has("impacts")) {
            return false;
        }
        try {
            Map<String, Obj> byId = new HashMap<>();
            Set<String> duplicated = new HashSet<>();
            for (Obj candidate : bundle.objects("relations")) {
                String id = candidate.string("id");
                if (byId.putIfAbsent(id, candidate) != null) {
                    duplicated.add(id);
                }
            }
            Map<String, List<Obj>> rowsByEdge = new HashMap<>();
            for (Obj row : bundle.objects("impacts")) {
                rowsByEdge.computeIfAbsent(row.string("edgeId"), edge -> new ArrayList<>()).add(row);
            }
            boolean cited = false;
            for (ImpactRef ref : new LinkedHashSet<>(refs)) {
                if (duplicated.contains(ref.relationId())) {
                    throw new GraphReceiptGrants.Malformed("receipt_relation_ambiguous");
                }
                Obj relation = byId.get(ref.relationId());
                if (relation == null) {
                    throw new GraphReceiptGrants.Malformed("receipt_relation_missing");
                }
                if (!ref.relationType().equals(relation.string("type")) || !ref.source().equals(relation.string("source"))
                        || !ref.target().equals(relation.string("target"))) {
                    throw new GraphReceiptGrants.Malformed("receipt_relation_mismatch");
                }
                Set<String> sourceRefs = new HashSet<>();
                for (Obj sourceRef : relation.objects("sourceRefs")) {
                    sourceRefs.add(sourceRef.string("jobId") + "\n" + sourceRef.string("id"));
                }
                Set<String> seen = new HashSet<>();
                for (Obj row : rowsByEdge.getOrDefault(ref.relationId(), List.of())) {
                    cited |= rowProves(row, evidenceId, ref, sourceRefs, seen);
                }
            }
            return cited;
        } catch (StrictJson.Malformed malformed) {
            throw new GraphReceiptGrants.Malformed("receipt_shape");
        }
    }

    /** One row of the referenced relation: structurally closed and bound, then {@code true} only if verified and listing the id. */
    private static boolean rowProves(Obj row, String evidenceId, ImpactRef ref, Set<String> sourceRefs, Set<String> seen) {
        row.exactly(ROW);
        if (!ref.source().equals(row.string("issueId")) || !ref.target().equals(row.string("companyId"))) {
            throw new GraphReceiptGrants.Malformed("receipt_impact_mismatch");
        }
        Obj sourceRelation = row.object("sourceRelation").exactly(Set.of("jobId", "relationCandidateId"));
        String key = sourceRelation.string("jobId") + "\n" + sourceRelation.string("relationCandidateId");
        if (!sourceRefs.contains(key)) {
            throw new GraphReceiptGrants.Malformed("receipt_impact_source_missing");
        }
        if (!seen.add(key)) {
            throw new GraphReceiptGrants.Malformed("receipt_impact_ambiguous");
        }
        if (!"verified".equals(row.string("status"))) {
            return false;
        }
        Obj effects = row.object("effects").exactly(SIDES);
        boolean listed = false;
        for (String side : SIDES) {
            listed |= effects.strings(side).contains(evidenceId);
        }
        return listed;
    }
}
