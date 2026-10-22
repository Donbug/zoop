"""Explicit single-round local collection boundary; historical defaults stay unchanged."""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import re
import briefing_replay as base
MODE="local_collection_validation"
SCHEMA="zoop-local-collection-v1"

def load(path, source_sha=None):
    value=base.strict_load(base.regular(Path(path)))
    try:
        window=value["window"];meta=value["localCollection"]
        start=datetime.fromisoformat(window["from"]);end=datetime.fromisoformat(window["to"])
        discovery=datetime.fromisoformat(meta["discoveryTo"])
        valid=(start.tzinfo is not None and end.tzinfo is not None and discovery.tzinfo is not None
            and start<discovery<=end and end<=datetime.now(timezone.utc) and end-start<=timedelta(hours=48)
            and end.astimezone(timezone(timedelta(hours=9))).date().isoformat()==value["date"]
            and value["edition"] in {"morning","evening"} and window["openStart"] is False
            and meta["schemaVersion"]==SCHEMA and meta["manualValidation"] is True
            and meta["collectedBeforeCutoff"] is True and meta["productionAuthorized"] is False
            and re.fullmatch(r"[0-9a-f]{64}",meta["sourceFileSha256"]) and re.fullmatch(r"[0-9a-f]{64}",meta["collectionPlanSha256"]))
        if source_sha is not None:valid=valid and meta["sourceFileSha256"]==source_sha
        if not valid:raise ValueError()
    except (KeyError,TypeError,ValueError):
        raise base.ReplayError("local_collection_window_invalid") from None
    return value

def sources_before_cutoff(rows,spec):
    cutoff=datetime.fromisoformat(spec["window"]["to"])
    for row in rows:
        try:
            captured=datetime.fromisoformat(row.get("collectedAt") or row["bodyAcquiredAt"])
            checked=datetime.fromisoformat(row["clockRecord"]["checkedAt"])
            published=datetime.fromisoformat(row["clockRecord"]["publishedAt"])
            if (captured.tzinfo is None or checked.tzinfo is None or not published<=captured<=cutoff
                or not checked<=cutoff or row["capture"]["sameResponseBodyAndClock"] is not True
                or row["capture"]["htmlSha256"]!=row["clockRecord"]["htmlSha256"]):
                raise ValueError()
        except (KeyError,TypeError,ValueError):
            raise base.ReplayError("local_collection_after_cutoff_or_unbound_body") from None
