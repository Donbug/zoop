"""Reuse the explicitly supplied team's PoC contracts and event identity rules.

No provider, repository, pipeline worker or private source is bundled here. The
operator supplies ``poc_root``; audited source hashes fail closed on drift. Domain,
search and numerical decisions are imported from that checkout. Only the pure
post-response guards and assignment expressions of Pipeline are compiled from
its original AST, avoiding its Python 3.12/provider/database dependencies. This is
not execution of the full PoC pipeline or a publication/rights approval.

Source: investmate-poc fa446e7c72edfa06ec1a0e8e999199a21d31c695.
This private team dependency is not redistributed; repository publication and any
license permission must be resolved separately before distributing its source.
"""
from __future__ import annotations

import ast
import hashlib
import importlib
import sys
import types
from pathlib import Path

VERSION = "zoop-team-issue-rules-1"
SOURCE_REVISION = "fa446e7c72edfa06ec1a0e8e999199a21d31c695"
SOURCE_HASHES = {
    "domain.py": "0870f3e011aae6082b491f63860ea8831ea0e5fbb416bedec2ddbbd0c05f8d3f",
    "search.py": "5a3d3b88f44996fbf80e9a54026283eb2f0f312acd0d96c8b122b7bb5cf55061",
    "decision.py": "0e55ef30f682e9b0b97b6fb21f5cf47a68de40d53070af0f30d272784fe3ac8c",
    "pipeline.py": "d1e71a1dd05adc74814da11b1b01bcdf7efa05ef02b5df548e4f352175d1eda9",
    "ports.py": "4b2ea782163b14e19b907e31f42f08d8dc6dbe55c65fbccd7aa35acc20f02bf4",
}


class IssueRulesError(ValueError):
    pass


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _assignment(node, name):
    return isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)


def _compile(name, parameters, statements, namespace, filename):
    function = ast.FunctionDef(name=name,
        args=ast.arguments(posonlyargs=[], args=[ast.arg(arg=p) for p in parameters],
                           kwonlyargs=[], kw_defaults=[], defaults=[]),
        body=statements, decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    exec(compile(module, filename, "exec"), namespace)
    return namespace[name]


class IssueRules:
    def __init__(self, poc_root):
        root = Path(poc_root).expanduser().resolve()
        package = root / "src" / "investmate"
        sources = {}
        for name, expected in SOURCE_HASHES.items():
            path = package / name
            if not path.is_file() or path.is_symlink():
                raise IssueRulesError("team_poc_source_missing")
            raw = path.read_bytes()
            if _sha(raw) != expected:
                raise IssueRulesError("team_poc_source_changed:" + name)
            sources[name] = raw
        # Isolate import identities; do not execute an unverified package __init__.
        namespace = "_zoop_team_issue_" + _sha(str(root).encode())[:20]
        if namespace not in sys.modules:
            module = types.ModuleType(namespace)
            module.__path__ = [str(package)]
            module.__package__ = namespace
            sys.modules[namespace] = module
        previous_bytecode = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            self.domain = importlib.import_module(namespace + ".domain")
            self.search = importlib.import_module(namespace + ".search")
            self.decision = importlib.import_module(namespace + ".decision")
        except (ImportError, SyntaxError) as exc:
            raise IssueRulesError("team_poc_dependency_unavailable") from exc
        finally:
            sys.dont_write_bytecode = previous_bytecode
        tree = ast.parse(sources["pipeline.py"], filename=str(package / "pipeline.py"))
        pipeline = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Pipeline")
        methods = {n.name: n for n in pipeline.body if isinstance(n, ast.FunctionDef)}
        compare = methods["_compare"].body
        start = next(i for i, n in enumerate(compare) if _assignment(n, "result"))
        guard = compare[start + 1:]
        if len(guard) != 5 or not isinstance(guard[-1], ast.Return):
            raise IssueRulesError("team_poc_guard_shape_changed")
        shared = {"PairDecision": self.domain.PairDecision,
                  "incompatible": self.search.incompatible, "digest": self.domain.digest}
        self._guard = _compile("team_effective_comparison", ["mention", "issue", "article", "result"],
                               guard, shared, str(package / "pipeline.py"))
        work = methods["_work_snapshot"].body
        first = next(i for i, n in enumerate(work) if _assignment(n, "same"))
        last = next(i for i, n in enumerate(work) if _assignment(n, "issue_id"))
        assignment = work[first:last + 1]
        if len(assignment) != 5:
            raise IssueRulesError("team_poc_assignment_shape_changed")
        result = ast.Return(value=ast.Tuple(elts=[ast.Name(id=n, ctx=ast.Load())
                                                 for n in ["issue_id", "hold", "selected"]], ctx=ast.Load()))
        self._assign = _compile("team_issue_assignment", ["mention", "article", "decisions"],
                                assignment + [result], shared, str(package / "pipeline.py"))
        self.root = root

    def identity(self):
        return {"adapterVersion": VERSION, "sourceRevision": SOURCE_REVISION,
                "sourceHashes": dict(SOURCE_HASHES),
                "reused": ["domain.Article/Evidence/Mention/Extraction", "search.incompatible",
                           "decision.classify_observation", "Pipeline._compare:post-response-guards",
                           "Pipeline._work_snapshot:identity-assignment"],
                "fullPipelineExecuted": False, "rightsOrPublicationApproved": False}

    def article(self, raw):
        return self.domain.Article.model_validate(raw, strict=True)

    def extraction(self, raw, article):
        article = self.article(article)
        result = self.domain.Extraction.model_validate(raw, strict=True)
        seen = set()
        for mention in result.mentions:
            if not mention.mention_id.strip() or mention.mention_id in seen:
                raise IssueRulesError("duplicate_or_empty_mention_id")
            seen.add(mention.mention_id)
            if (mention.article_id, mention.article_version) != (article.article_id, article.version):
                raise IssueRulesError("mention_article_version_mismatch")
            if not mention.evidence or any(not e.matches(article) for e in mention.evidence):
                raise IssueRulesError("mention_exact_evidence_missing")
        return result

    def issue_snapshot(self, raw):
        result = self.domain.IssueSnapshot.model_validate(raw, strict=True)
        if not result.issue_id.strip() or not result.mentions or not result.articles:
            raise IssueRulesError("issue_snapshot_empty")
        sources = {(a.article_id, a.version): a for a in result.articles}
        for mention in result.mentions:
            article = sources.get((mention.article_id, mention.article_version))
            if article is None:
                raise IssueRulesError("snapshot_mention_source_missing")
            self.extraction({"mentions": [mention]}, article)
        return result

    def effective_comparison(self, mention, issue, article, raw):
        article = self.article(article)
        mention = self.extraction({"mentions": [mention]}, article).mentions[0]
        issue = self.issue_snapshot(issue)
        decision = self.domain.PairDecision.model_validate(raw, strict=True)
        return self._guard(mention, issue, article, decision)

    def assign(self, mention, article, comparisons):
        article = self.article(article)
        mention = self.extraction({"mentions": [mention]}, article).mentions[0]
        checked, seen = [], set()
        for issue, decision in comparisons:
            issue = self.issue_snapshot(issue)
            if issue.issue_id in seen:
                raise IssueRulesError("duplicate_comparison_target")
            seen.add(issue.issue_id)
            checked.append((issue, self.effective_comparison(mention, issue, article, decision)))
        issue_id, hold, selected = self._assign(mention, article, checked)
        return {"status": "HOLD" if hold else "MERGE" if selected is not None else "NEW",
                "issueId": issue_id, "holdReason": hold,
                "sameTargets": [i.issue_id for i, d in checked if d.relation == "SAME"],
                "follows": [i.issue_id for i, d in checked if d.relation == "FOLLOWS"],
                "comparisons": [{"issueId": i.issue_id, "effective": d.model_dump(mode="json")}
                                for i, d in checked],
                "approved": False}

    def classify_observation(self, raw, policy=None):
        observation = self.domain.VerificationObservation.model_validate(raw, strict=True)
        policy = self.domain.DecisionPolicy() if policy is None else self.domain.DecisionPolicy.model_validate(policy, strict=True)
        return self.decision.classify_observation(observation, policy)
