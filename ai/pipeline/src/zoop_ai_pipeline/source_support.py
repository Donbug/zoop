"""Pure source-support (origin/lineage and exact-text duplicate) summary of ONE public issue. No I/O, no storage, no model.

Re-implementation of the pure algorithm of the retired PoC (`InvestMateLogicTest` `PostgresRepository._source_support`): the same union-find rule and
the same five public fields, with an explicit input instead of a database view. Nothing is imported from the PoC.

Rules (each one is a fact about the INPUT, never a guess):
* an article's `originId` is an operator-declared, version-bound fact (`origins[]` of the public decisions file) or absent. Absent is UNKNOWN: it is
  never inferred from a publisher, a URL or host, a `sourceId`, a title or a raw hash;
* two articles belong to ONE lineage group when they share a non-empty origin OR their prepared texts are exactly equal (`textSha256`, the SHA-256 of the
  exact UTF-8 text the app stores; equal digests stand for equal text). The union is transitive;
* `knownLineageCount` counts lineage GROUPS that contain at least one origin, not articles;
* `independentSourceCount` is null when any article has no origin or any group holds more than one distinct origin, otherwise it equals
  `knownLineageCount`; it is never null-coalesced to a number;
* `duplicateGroups` lists only EXACT-text equality groups of two or more articles (never groups joined through a shared origin).

An issue must cite exactly one version of each article (`issue_article_versions_multiple` otherwise); this function therefore receives one row per article.
"""
from __future__ import annotations

KEYS = ("articleCount", "knownLineageCount", "unknownLineageArticles", "independentSourceCount", "duplicateGroups")


def source_support(articles: list[dict]) -> dict:
    """`articles`: one dict per distinct article with `articleId`, `textSha256` and `originId` (a string, or None when no origin is declared).

    Returns exactly the five public keys. Raises ValueError for a repeated article id (one version per article is the caller's rule)."""
    ids = [a["articleId"] for a in articles]
    if len(set(ids)) != len(ids):
        raise ValueError("article cited more than once")
    parent = list(range(len(articles)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def join(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    origins: dict = {}
    texts: dict = {}
    for n, article in enumerate(articles):
        if article["originId"]:
            origins.setdefault(article["originId"], []).append(n)
        texts.setdefault(article["textSha256"], []).append(n)
    for members in (*origins.values(), *texts.values()):
        for other in members[1:]:
            join(members[0], other)
    components: dict = {}
    for n, article in enumerate(articles):
        components.setdefault(find(n), set())
        if article["originId"]:
            components[find(n)].add(article["originId"])
    unknown = sorted(a["articleId"] for a in articles if not a["originId"])
    known = sum(1 for found in components.values() if found)
    conflict = any(len(found) > 1 for found in components.values())
    return {"articleCount": len(articles), "knownLineageCount": known, "unknownLineageArticles": unknown,
            "independentSourceCount": None if unknown or conflict else known,
            "duplicateGroups": sorted(sorted(articles[n]["articleId"] for n in members) for members in texts.values() if len(members) > 1)}
