"""Pure source-support summary of one issue: the PoC union-find rule (shared declared origin OR exactly equal text), written out by hand.

No I/O, no storage, no model. The expectations are the retired PoC's own documented cases (reprints of one origin, unknown lineage, conflicting origins joined
through an identical text, duplicate groups that are NOT connected components) plus the rules this port adds explicitly: an origin is never inferred, an article is
cited once.
"""
from __future__ import annotations

import pytest

from zoop_ai_pipeline.source_support import KEYS, source_support

T1, T2, T3 = "1" * 64, "2" * 64, "3" * 64


def row(article: str, text: str, origin: str | None = None, **extra) -> dict:
    return {"articleId": "doc-" + article * 64, "textSha256": text, "originId": origin, **extra}


def ident(article: str) -> str:
    return "doc-" + article * 64


def test_two_reprints_of_one_origin_are_one_known_lineage_group_not_two():
    out = source_support([row("a", T1, "wire"), row("b", T2, "wire")])
    assert out == {"articleCount": 2, "knownLineageCount": 1, "unknownLineageArticles": [], "independentSourceCount": 1, "duplicateGroups": []}
    assert tuple(out) == KEYS


def test_an_article_without_a_declared_origin_makes_the_independent_count_unknown_never_a_number():
    out = source_support([row("a", T1, "wire"), row("b", T2)])
    assert out == {"articleCount": 2, "knownLineageCount": 1, "unknownLineageArticles": [ident("b")], "independentSourceCount": None, "duplicateGroups": []}
    none = source_support([row("a", T1), row("b", T2)])
    assert none["knownLineageCount"] == 0 and none["independentSourceCount"] is None and none["unknownLineageArticles"] == [ident("a"), ident("b")]


def test_two_origins_whose_texts_are_exactly_equal_are_one_group_with_conflicting_origins_so_independence_is_unknown():
    out = source_support([row("a", T1, "x"), row("b", T1, "y")])
    assert out == {"articleCount": 2, "knownLineageCount": 1, "unknownLineageArticles": [], "independentSourceCount": None, "duplicateGroups": [[ident("a"), ident("b")]]}


def test_distinct_origins_and_distinct_texts_are_independent():
    out = source_support([row("a", T1, "x"), row("b", T2, "y"), row("c", T3, "z")])
    assert out == {"articleCount": 3, "knownLineageCount": 3, "unknownLineageArticles": [], "independentSourceCount": 3, "duplicateGroups": []}


def test_duplicate_groups_are_exact_text_equality_only_never_the_connected_component_of_shared_origins():
    # a and c share an origin (one lineage group) but their texts differ: they are NOT a duplicate group; d repeats a's text exactly.
    out = source_support([row("a", T1, "x"), row("c", T2, "x"), row("d", T1)])
    assert out["duplicateGroups"] == [[ident("a"), ident("d")]]
    assert out["knownLineageCount"] == 1 and out["unknownLineageArticles"] == [ident("d")] and out["independentSourceCount"] is None
    # groups and members are sorted whatever the input order.
    shuffled = source_support([row("f", T2), row("e", T2), row("b", T1), row("a", T1)])
    assert shuffled["duplicateGroups"] == [[ident("a"), ident("b")], [ident("e"), ident("f")]]


def test_identical_text_without_any_origin_is_a_duplicate_group_and_still_unknown():
    out = source_support([row("a", T1), row("b", T1)])
    assert out == {"articleCount": 2, "knownLineageCount": 0, "unknownLineageArticles": [ident("a"), ident("b")], "independentSourceCount": None,
                   "duplicateGroups": [[ident("a"), ident("b")]]}


def test_nothing_but_the_declared_origin_and_the_exact_text_hash_is_read():
    # A publisher, URL or host on the row changes nothing: the same two rows with and without them give the same summary.
    plain = source_support([row("a", T1), row("b", T2)])
    decorated = source_support([row("a", T1, publisher="합성일보", url="https://same.example.invalid/x", host="same.example.invalid"),
                                row("b", T2, publisher="합성일보", url="https://same.example.invalid/y", host="same.example.invalid")])
    assert plain == decorated and decorated["independentSourceCount"] is None


def test_an_article_cited_twice_is_refused_because_one_version_per_article_is_the_callers_rule():
    with pytest.raises(ValueError):
        source_support([row("a", T1), row("a", T2)])


def test_an_issue_without_articles_is_all_zero_and_the_input_is_not_modified():
    assert source_support([]) == {"articleCount": 0, "knownLineageCount": 0, "unknownLineageArticles": [], "independentSourceCount": 0, "duplicateGroups": []}
    rows = [row("b", T1, "x"), row("a", T1, "x")]
    before = [dict(r) for r in rows]
    source_support(rows)
    assert rows == before
