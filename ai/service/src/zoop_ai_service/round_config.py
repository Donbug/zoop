"""Explicit single-source continuous profile, separate from archive delivery."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


PROFILE = "ZOOP_AI_SERVICE_ROUND_PROFILE"


@dataclass(frozen=True)
class RoundConfig:
    profile_path: Path
    profile_sha256: str
    ingestion_command: Path
    source_id: str
    scope_id: str
    initial_from: str
    fixture_manifest: Path
    descriptor: dict
    max_age_seconds: int
    limit: int
    handoff_binding: dict

    def binding(self):
        return {"profile": str(self.profile_path), "sha256": self.profile_sha256,
                "ingestionCommand": str(self.ingestion_command), "handoff": self.handoff_binding}


def load_round(environ, *, extraction, relation, handoff, observation, plan_root):
    from .config import ConfigError, _file
    from .plan_verify import InstallError, decode, read_file, sha
    if PROFILE not in environ:
        return None
    if extraction is None or relation is None or handoff is None or observation is None or plan_root is None:
        raise ConfigError(PROFILE, "round_execution_groups_required")
    if handoff.source_contexts is not None or observation.source_contexts is not None:
        raise ConfigError(PROFILE, "round_writable_source_required")
    path = _file(environ[PROFILE], PROFILE)
    try:
        raw = read_file(path, 2_000_000)
        doc = decode(raw)
        if set(doc) != {"schemaVersion", "sourceId", "scopeId", "initialFrom", "fixtureManifest", "descriptor", "selection"} \
                or doc["schemaVersion"] != "zoop-ai-round-profile-1":
            raise ValueError("profile shape")
        if any(not isinstance(doc[k], str) or not 1 <= len(doc[k]) <= 200 for k in ("sourceId", "scopeId")):
            raise ValueError("source scope")
        initial = datetime.fromisoformat(doc["initialFrom"].replace("Z", "+00:00"))
        if initial.tzinfo is None:
            raise ValueError("initial timestamp")
        selection = doc["selection"]
        if set(selection) != {"maxAgeSeconds", "limit", "cadenceMinutes"} or type(selection["maxAgeSeconds"]) is not int \
                or selection["maxAgeSeconds"] <= 0 or type(selection["limit"]) is not int or not 1 <= selection["limit"] <= 8 \
                or type(selection["cadenceMinutes"]) is not int or selection["cadenceMinutes"] != 30:
            raise ValueError("selection policy")
        descriptor = doc["descriptor"]
        if set(descriptor) != {"schemaVersion", "provenance", "promptVersion", "catalogue", "snapshot", "topic"} \
                or descriptor["schemaVersion"] != "zoop-extraction-s2-2":
            raise ValueError("descriptor shape")
        fixture = _file(doc["fixtureManifest"], PROFILE)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, InstallError):
        raise ConfigError(PROFILE, "round_profile_invalid") from None
    handoff_binding = {"command": str(handoff.command), "state": str(handoff.state_dir), "canonical": str(handoff.canonical_path),
                       "decisions": str(handoff.decisions_path), "sources": str(handoff.sources_path)}
    return RoundConfig(path, sha(raw), observation.command, doc["sourceId"], doc["scopeId"], doc["initialFrom"], fixture,
                       descriptor, selection["maxAgeSeconds"], selection["limit"], handoff_binding)
