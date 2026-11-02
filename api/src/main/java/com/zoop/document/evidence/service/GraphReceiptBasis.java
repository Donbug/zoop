package com.zoop.document.evidence.service;

import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.document.evidence.graph.GraphEvidence.BasisRef;

/**
 * The one fact the public graph evidence read takes from a graph import's {@code verification_receipt} for a BASIS-ONLY span: that
 * a visible structural relation's visible basis really cites the evidence id. The pinned snapshot only says which structural bases
 * reference the span's article version ({@link BasisRef}); it does not record which evidence a basis rests on, and the relation's
 * own {@code evidenceIds} are never extended with basis evidence (a basis the asOf filter removed would leak through them). The
 * receipt is retained data, never authority: it decides membership only, and every current-rights, row, text and article gate of
 * the read still applies.
 *
 * <p>The receipt is the already-verified bundle of exactly the graph version being served ({@link GraphReceiptGrants#bundle}),
 * read from the same bytes as the grant pins. For each candidate reference exactly one bundle relation must carry its id and
 * equal its type, source and target, and exactly one of that relation's bases must carry its {@code relationKey}; a missing,
 * duplicated or mismatching relation or basis makes the whole receipt {@link GraphReceiptGrants.Malformed} for this read (fail
 * closed, never "the other candidate was fine"). {@link #proves} is true when at least one such basis lists the id and false for
 * a structurally valid receipt whose referenced bases do not (the caller may then try {@link GraphReceiptImpact}); structural
 * malformation always throws, so it can never hide behind a true answer of the other seam. A receipt whose bundle predates the
 * shape ({@code relations[].basis[].relationKey} and {@code evidenceIds}) fails closed the same way.
 */
final class GraphReceiptBasis {

    private GraphReceiptBasis() {
    }

    /**
     * @return whether a referenced basis of the receipt cites {@code evidenceId}; false when there is no reference or none does
     * @throws GraphReceiptGrants.Malformed when a referenced relation or basis is missing, duplicated or does not match
     */
    static boolean proves(Obj bundle, String evidenceId, List<BasisRef> refs) {
        if (bundle.has("schemaVersion") && com.zoop.graph.importer.LegacyRealPackage.isBundleSchema(bundle.string("schemaVersion"))) return false;
        if (refs.isEmpty()) {
            return false;
        }
        try {
            // One pass over the receipt's relations: an id carried twice is remembered and refuses only a reference that names it.
            Map<String, Obj> byId = new HashMap<>();
            Set<String> duplicated = new HashSet<>();
            for (Obj candidate : bundle.objects("relations")) {
                String id = candidate.string("id");
                if (byId.putIfAbsent(id, candidate) != null) {
                    duplicated.add(id);
                }
            }
            boolean cited = false;
            for (BasisRef ref : new LinkedHashSet<>(refs)) {
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
                Obj basis = null;
                for (Obj candidate : relation.objects("basis")) {
                    if (ref.basisId().equals(candidate.string("relationKey"))) {
                        if (basis != null) {
                            throw new GraphReceiptGrants.Malformed("receipt_basis_ambiguous");
                        }
                        basis = candidate;
                    }
                }
                if (basis == null) {
                    throw new GraphReceiptGrants.Malformed("receipt_basis_missing");
                }
                cited |= basis.strings("evidenceIds").contains(evidenceId);
            }
            return cited;
        } catch (StrictJson.Malformed malformed) {
            throw new GraphReceiptGrants.Malformed("receipt_shape");
        }
    }
}
