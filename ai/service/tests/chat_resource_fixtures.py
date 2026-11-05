"""Generated worker-owned wire examples for service boundary tests."""
import copy
import json
from pathlib import Path

FIXTURE = json.loads((Path(__file__).absolute().parents[3] / "docs/api/fixtures/chat-internal-contracts.json").read_text(encoding="utf-8"))["resourceContracts"]


def allocation(stage="chat-router", mode="replay"):
    return copy.deepcopy(FIXTURE["allocations"][stage + ":" + mode])
