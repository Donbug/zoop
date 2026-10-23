"""Ordered structural paths of the public graph handoff (bundle `-5`).

A STRUCTURALLY_RELATED_TO edge names the operator-attested chain participant -> (middle ->) target over its S3 SUPPLIES basis, with one directed link per basis relation and
the S3 scopes copied exactly. It is an operator-mapped basis chain: never causality, never price direction, never a graph node. A middle company the operator mapped but the
bundle does not publish is a PRIVATE `pathCompanies` support reference (never a company, an issue or a mention participant); an unmapped middle makes the path honestly
`unavailable`. Expectations are written by hand from the authored world (`scripts/graph_handoff_smoke.py`: `chain_decisions`, `expected_chain`); the closed validator is
exercised with one broken rule per bundle and a REFRESHED content digest, so only the structural-path rule can refuse it.
"""
from __future__ import annotations

import json

import pytest

from scripts import graph_handoff_smoke as hs
from tests.test_handoff import Rig, chain_world, excluded, rehashed, rig, shared, structural_edges, supply_of  # noqa: F401
from zoop_ai_pipeline.handoff import Planner
from zoop_ai_pipeline.handoff_contracts import ExtractionFailure, content_digest, validate_bundle

MIDDLES = ("known", "private", "unmapped")


def chain_rig(world, tmp_path, middle: str) -> Rig:
    return Rig(world, tmp_path, docs={"canonical": hs.canonical_doc(world), "decisions": hs.chain_decisions(world, middle), "bindings": hs.bindings_doc(world)})


@pytest.fixture(scope="module")
def bundles(chain_world, tmp_path_factory) -> dict:
    return {middle: chain_rig(chain_world, tmp_path_factory.mktemp(f"zoop-handoff-path-{middle}"), middle).bundle(f"path-{middle}") for middle in MIDDLES}


def edge(bundle: dict, target: str) -> dict:
    return next(r for r in bundle["relations"] if r["type"] == "STRUCTURALLY_RELATED_TO" and r["target"] == target)


# ---------------------------------------------------------------- producer ------------------------------------------------------------

@pytest.mark.parametrize("middle", MIDDLES)
def test_the_chain_world_export_equals_the_hand_written_paths_companies_and_scopes(chain_world, bundles, middle):
    hs.check_chain_export(chain_world, bundles[middle], middle)
    validate_bundle(bundles[middle])


def test_a_one_relation_edge_of_the_base_world_names_participant_and_target_with_one_directed_link(rig):
    bundle = rig.bundle()
    (one,) = structural_edges(bundle)
    assert one["structuralPath"] == {"status": "complete", "companyIds": ["KRX:005930", "KRX:000660"],
                                     "links": [{"supplierCompanyId": "KRX:000660", "customerCompanyId": "KRX:005930"}]}
    assert bundle["pathCompanies"] == [] and bundle["counts"]["pathCompanies"] == 0
    assert [(b["businessScope"], b["productScope"]) for b in one["basis"]] == [(None, "배터리 부품")]
    assert all(r["structuralPath"] is None for r in bundle["relations"] if r["type"] != "STRUCTURALLY_RELATED_TO")


def test_a_mapped_middle_the_bundle_does_not_publish_is_a_private_support_company_and_never_a_public_node(bundles):
    bundle = bundles["private"]
    assert [c["id"] for c in bundle["companies"]] == ["KRX:000999", "KRX:005930"]
    assert bundle["pathCompanies"] == [{"id": "KRX:000660", "canonicalId": "co:synth-3", "label": "합성부품", "decisionRef": "catalog-2026-10-16:3"}]
    assert edge(bundle, "KRX:000999")["structuralPath"]["companyIds"] == ["KRX:005930", "KRX:000660", "KRX:000999"]
    assert not any(r["target"] == "KRX:000660" for r in bundle["relations"]), "a private company is the endpoint of no edge"
    participants = {p["companyId"] for m in supply_of(bundle)["mentions"] for p in m["participants"] if p["sourceCompanyId"] == "SYNTH-3"}
    assert participants == {None}, "a mention participant resolves only against the published companies"
    assert content_digest(bundle) == bundle["digests"]["content"] != content_digest({**bundle, "pathCompanies": []}), "the private companies are covered by the content digest"


def test_a_middle_the_bundle_publishes_is_a_company_and_not_a_private_one(bundles):
    bundle = bundles["known"]
    assert bundle["pathCompanies"] == [] and "KRX:000660" in {c["id"] for c in bundle["companies"]}
    assert [len(edge(bundle, t)["structuralPath"]["companyIds"]) for t in ("KRX:000660", "KRX:000999")] == [2, 3]


def test_an_unmapped_middle_is_unavailable_never_invented_and_the_two_basis_edge_is_still_exported(bundles):
    bundle = bundles["unmapped"]
    two = edge(bundle, "KRX:000999")
    assert two["structuralPath"] == {"status": "unavailable", "reason": "intermediate_company_unmapped"}
    assert len(two["basis"]) == 2 and bundle["pathCompanies"] == [] and "KRX:000660" not in json.dumps(bundle["companies"] + two["basis"])
    assert not {"companyIds", "links"} & set(two["structuralPath"])


def test_the_edge_id_formula_and_the_basis_evidence_are_not_changed_by_a_path(chain_world, bundles):
    for middle, bundle in bundles.items():
        two = edge(bundle, "KRX:000999")
        keys = [hs.find(chain_world.jobs["rel-a"], "SUPPLIES", s, c)["relationKey"] for s, c in hs.TWO_HOP[1]]
        assert two["id"] == "edge-" + hs.digest({"type": "STRUCTURALLY_RELATED_TO", "source": "issue:supply-2026q3", "target": "KRX:000999", "basis": keys}), middle
        assert two["provenance"]["basisEligibility"] == "s3-independent-verifier-supported-all-claims"
    assert hs.evidence_id(chain_world, "a", hs.CHAIN) in edge(bundles["private"], "KRX:000999")["basis"][1]["evidenceIds"]
    assert hs.evidence_id(chain_world, "a", hs.CHAIN) not in edge(bundles["private"], "KRX:000999")["evidenceIds"], "basis evidence is never unioned into the edge's own evidence"


def test_the_receipt_counts_the_private_companies_and_a_stored_artifact_is_the_exported_bundle(chain_world, tmp_path):
    rig = chain_rig(chain_world, tmp_path, "private")
    frozen = rig.freeze("path-1")
    assert frozen["receipt"]["counts"]["pathCompanies"] == 1 and frozen["receipt"]["bundleSchema"] == "zoop-graph-handoff-bundle-6"
    out = rig.run("export", rig.sel("path-1"))
    assert out["bundle"]["counts"] == frozen["receipt"]["counts"] and out["delivery"]["status"] == "current"
    assert hs.canonical(out["bundle"]).encode() == (rig.state / "bundles" / f"{frozen['receipt']['bundleDigest']}.json").read_bytes()


def test_a_basis_that_does_not_connect_a_participant_keeps_its_existing_exclusion_and_publishes_no_private_company(chain_world, tmp_path):
    rig = chain_rig(chain_world, tmp_path, "private")
    structural = rig.docs["decisions"]["structural"][0]
    structural["basis"].reverse()                  # the walk must start at the issue's participant: SYNTH-4 -> SYNTH-3 does not
    rig.write()
    bundle = rig.bundle()
    assert excluded(bundle)[("structural", "issue:supply>co:synth-4")] == "basis_path_disconnected"
    assert not structural_edges(bundle) and bundle["pathCompanies"] == [] and bundle["counts"]["pathCompanies"] == 0


def test_a_target_that_already_participates_keeps_its_existing_exclusion(chain_world, tmp_path):
    rig = chain_rig(chain_world, tmp_path, "known")
    rig.docs["decisions"]["structural"][0]["company"] = "co:synth-1"
    rig.write()
    assert excluded(rig.bundle())[("structural", "issue:supply>co:synth-1")] == "structural_target_is_participant"


# ---------------------------------------------------------------- the pure chain ---------------------------------------------------------

def rows(*pairs):
    """Planner basis rows as `(loaded, relation, subject canonical, object canonical)`: S3 SUPPLIES `subject supplies object`."""
    return [(None, None, subject, obj) for subject, obj in pairs]


@pytest.mark.parametrize("pairs,participants,target,chain", [
    ([("s", "p")], {"p"}, "s", ["p", "s"]),                                    # the participant is the customer of the target
    ([("p", "s")], {"p"}, "s", ["p", "s"]),                                    # ... or its supplier: the walk is undirected, the link direction stays the S3 one
    ([("m", "p"), ("t", "m")], {"p"}, "t", ["p", "m", "t"]),
    ([("m", "p"), ("m", "t")], {"p"}, "t", ["p", "m", "t"]),
    ([("p", "m"), ("m", "t")], {"p"}, "t", ["p", "m", "t"]),
    ([("a", "b"), ("b", "c")], {"a", "b"}, "c", ["a", "b", "c"]),             # both ends of the first relation participate: the first usable start wins, deterministically
    ([("s", "p")], {"p"}, "x", None),                                          # the basis does not reach the target
    ([("s", "p")], {"q"}, "s", None),                                          # no participant starts the walk
    ([("m", "p"), ("t", "n")], {"p"}, "t", None),                              # the second relation does not continue from the middle
    ([("m", "p"), ("p", "m")], {"p"}, "p", None),                              # no company repeats
    ([("p", "p")], {"p"}, "p", None),
])
def test_the_chain_is_the_ordered_undirected_walk_over_the_basis_or_nothing(pairs, participants, target, chain):
    assert Planner.chain(rows(*pairs), participants, target) == chain


# ---------------------------------------------------------------- the closed validator --------------------------------------------------

@pytest.mark.parametrize("name", list(hs.path_mutations()))
def test_a_broken_structural_path_or_private_company_is_refused_even_with_a_refreshed_content_digest(bundles, name):
    middle, change, at = hs.path_mutations()[name]
    validate_bundle(bundles[middle])
    broken = rehashed(bundles[middle], change)
    assert broken["digests"]["content"] == content_digest(broken)
    with pytest.raises(ExtractionFailure) as exc:
        validate_bundle(broken)
    assert exc.value.code == "handoff_bundle_invalid" and exc.value.detail == {"at": at}, name


def test_a_private_company_changed_without_refreshing_the_digest_is_refused(bundles):
    broken = json.loads(json.dumps(bundles["private"]))
    broken["pathCompanies"][0]["label"] = "다른 이름"
    with pytest.raises(ExtractionFailure) as exc:
        validate_bundle(broken)
    assert exc.value.detail == {"at": "digests.content"}


def test_the_private_companies_must_be_sorted(bundles):
    def unsorted(b):
        for ident in ("KRX:000777", "KRX:000770"):
            b["pathCompanies"].append({"id": ident, "canonicalId": "co:synth-7", "label": "합성미사용", "decisionRef": "catalog-2026-10-16:7"})
        b["counts"]["pathCompanies"] += 2
    with pytest.raises(ExtractionFailure) as exc:
        validate_bundle(rehashed(bundles["private"], unsorted))
    assert exc.value.detail == {"at": "pathCompanies.order"}


def test_the_bundle_is_closed_over_its_new_keys(bundles):
    for name, change in (("a bundle without pathCompanies", lambda b: b.pop("pathCompanies")),
                         ("a relation without structuralPath", lambda b: b["relations"][0].pop("structuralPath")),
                         ("a bundle with another collection", lambda b: b.update(paths=[]))):
        broken = json.loads(json.dumps(bundles["private"]))
        change(broken)
        with pytest.raises(ExtractionFailure) as exc:
            validate_bundle(broken)
        assert exc.value.code == "handoff_bundle_invalid", name
