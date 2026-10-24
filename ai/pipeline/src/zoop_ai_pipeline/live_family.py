"""Value types of a live runtime FAMILY: one frozen set of stages (OpenAI-compatible generation specs plus one native Jev verifier)
that `live_runtime.LiveRuntime` binds, prepares and decodes under its own `version`.

Pure and import-light on purpose: family modules (`issue_summary_jev`) import these types, so this module never imports
`live_runtime`. A family is static data; nothing registers itself and no stage of one family exists in another.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Verifier:
    """The independent native-Jev side of a family. `build[stage](payload, model) -> (request body, expect)`; `expect` is the decode
    context kept in the receipt. `interpret[stage](raw, expect, model) -> (answer, audit)` raises ValueError(code) on any contract
    deviation. `identity()` binds every question text, option set and threshold; `policy()` is the secret-free threshold record."""

    api: str
    model: str
    revision: str
    identity: Callable[[], str]
    policy: Callable[[], dict[str, Any]]
    prompt_prefix: str
    build: Mapping[str, Callable[[dict, str], tuple[dict, dict]]]
    interpret: Mapping[str, Callable[[Any, dict, str], tuple[dict, list]]]


@dataclass(frozen=True)
class Family:
    """`version` is the binding version; `generation` maps a generation stage to its `live_prompts.Spec`."""

    version: str
    generation: Mapping[str, Any]
    verifier: Verifier

    @property
    def generation_stages(self) -> tuple[str, ...]:
        return tuple(self.generation)

    @property
    def verify_stages(self) -> tuple[str, ...]:
        return tuple(self.verifier.build)

    @property
    def stages(self) -> tuple[str, ...]:
        return self.generation_stages + self.verify_stages
