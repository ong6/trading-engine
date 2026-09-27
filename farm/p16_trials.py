"""Pure validation and projection for the canonical P16 trial register."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from engine.lib.provenance import canonical_sha256

KINDS = {"registration", "evaluation_started", "evaluated", "failed", "abandoned",
         "retired", "alias", "identity_verified", "inventory_reconciliation"}
ATTEMPTS = {"evaluation_started", "evaluated", "failed", "abandoned"}
IDENTITY_FIELDS = {"model", "prompt", "tools", "features", "memory_update_rule",
                   "aggregation", "scoring", "portfolio_rule", "label_basis"}
EVIDENCE_CLASSES = {"prospective", "development", "lockbox", "contaminated"}
TRIAL_KINDS = {"policy", "deterministic_baseline"}
PLANS = {f"P{number}" for number in range(5, 17)}


def sha256_valid(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("trial timestamp must have an explicit timezone")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def registration(
    *, policy_id: str, policy_version: str, plan_id: str, registration_identity: dict,
    evidence_class: str, trial_kind: str, parent_trial_ids: list[str], registered_at: datetime,
    identity_status: str,
) -> tuple[str, dict]:
    if (not all(isinstance(value, str) and value for value in (policy_id, policy_version, plan_id))
            or set(registration_identity) != IDENTITY_FIELDS
            or any(value in (None, "", [], {}) for value in registration_identity.values())
            or plan_id not in PLANS or evidence_class not in EVIDENCE_CLASSES
            or trial_kind not in TRIAL_KINDS
            or identity_status not in {"verified", "provisional"}
            or not isinstance(parent_trial_ids, list)
            or any(not sha256_valid(item) for item in parent_trial_ids)
            or parent_trial_ids != sorted(set(parent_trial_ids))):
        raise ValueError("trial registration is invalid")
    at = timestamp(registered_at)
    trial_id = canonical_sha256({"policy_id": policy_id, "policy_version": policy_version,
                                 "registration_identity": registration_identity})
    if trial_id in parent_trial_ids:
        raise ValueError("trial cannot parent itself")
    return trial_id, {"policy_id": policy_id, "policy_version": policy_version,
                      "plan_id": plan_id, "registered_at": at.isoformat(),
                      "registration_identity": registration_identity,
                      "evidence_class": evidence_class, "trial_kind": trial_kind,
                      "parent_trial_ids": parent_trial_ids,
                      "identity_status": identity_status}


def encoded_record(kind: str, trial_id: str | None, event_at: datetime,
                   recorded_at: datetime, payload: dict, source_sha: str | None) -> tuple:
    event, recorded = timestamp(event_at), timestamp(recorded_at)
    if kind not in KINDS or event > recorded or not isinstance(payload, dict):
        raise ValueError("trial record is invalid")
    logical = {"record_kind": kind, "trial_id": trial_id, "event_at": event.isoformat(),
               "source_sha256": source_sha, "payload": payload}
    record_sha = canonical_sha256(logical)
    row_sha = canonical_sha256({"record_sha256": record_sha,
                                "recorded_at": recorded.isoformat()})
    return record_sha, kind, trial_id, event, recorded, source_sha, json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False), row_sha


def decode(row: tuple) -> dict:
    record_sha, kind, trial_id, event, recorded, source_sha, raw, row_sha = row
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("trial record differs") from exc
    expected = encoded_record(kind, trial_id, event.replace(tzinfo=timezone.utc),
                              recorded.replace(tzinfo=timezone.utc), payload, source_sha)
    if tuple(row) != expected:
        raise ValueError("trial record differs")
    if kind not in {"registration", "inventory_reconciliation"} and (
            set(payload) != {"source_ref"} or not isinstance(payload["source_ref"], dict)
            or not payload["source_ref"] or canonical_sha256(payload["source_ref"]) != source_sha):
        raise ValueError("trial event source differs")
    return {"record_sha256": record_sha, "record_kind": kind, "trial_id": trial_id,
            "event_at": event.isoformat(), "recorded_at": recorded.isoformat(),
            "source_sha256": source_sha, "payload": payload, "row_sha256": row_sha}


def register_digest(records: list[dict]) -> str:
    return canonical_sha256(sorted(row["row_sha256"] for row in records
                                   if row["record_kind"] != "inventory_reconciliation"))


def _verified(registration_row: dict, events: list[dict]) -> bool:
    if registration_row["payload"]["identity_status"] == "verified":
        return True
    expected = canonical_sha256(registration_row["payload"]["registration_identity"])
    return any(row["record_kind"] == "identity_verified"
               and set(row["payload"]["source_ref"]) == {
                   "registration_identity_sha256", "evidence_sha256", "reason"}
               and row["payload"]["source_ref"]["registration_identity_sha256"] == expected
               and sha256_valid(row["payload"]["source_ref"]["evidence_sha256"])
               and bool(row["payload"]["source_ref"]["reason"])
               for row in events)


def _redirect_valid(source: dict, target: dict, resolution: object,
                    events: dict[str, list[dict]]) -> bool:
    if (not isinstance(resolution, dict)
            or set(resolution) != {"canonical_trial_id", "evidence_sha256", "reason"}
            or not sha256_valid(resolution["evidence_sha256"]) or not resolution["reason"]
            or source["payload"]["identity_status"] != "provisional"
            or not _verified(target, events[target["trial_id"]])
            or source["payload"]["policy_id"] != target["payload"]["policy_id"]):
        return False
    source_payload, target_payload = source["payload"], target["payload"]
    if source_payload["policy_version"] != target_payload["policy_version"] \
            and not source_payload["policy_version"].startswith("unresolved:"):
        return False
    source_recipe, target_recipe = (source_payload["registration_identity"],
                                    target_payload["registration_identity"])
    return all(source_recipe[key] == target_recipe[key] or (
        isinstance(source_recipe[key], str) and source_recipe[key].startswith("unresolved:"))
        for key in IDENTITY_FIELDS)


def reconciliation_valid(value: dict, records: list[dict]) -> bool:
    if (not isinstance(value, dict)
            or set(value) != {"scope", "covered_plans", "deterministic_baseline_trial_ids",
                       "sources", "entries", "trial_redirects", "register_sha256"}
            or value["scope"] != "all_plans_and_deterministic_baselines_through_p16"
            or not isinstance(value["covered_plans"], list)
            or not set(value["covered_plans"]) <= PLANS
            or value["register_sha256"] != register_digest(records)):
        return False
    registration_rows = {row["trial_id"]: row for row in records
                         if row["record_kind"] == "registration"}
    registrations = {key: row["payload"] for key, row in registration_rows.items()}
    events = {trial_id: [row for row in records if row["trial_id"] == trial_id
                         and row["record_kind"] != "registration"]
              for trial_id in registrations}
    attempted = {row["trial_id"] for row in records if row["record_kind"] in ATTEMPTS}
    aliases = {(row["trial_id"], row["source_sha256"]) for row in records
               if row["record_kind"] == "alias"}
    sources = value["sources"]
    if (not isinstance(sources, list) or any(set(item) != {
            "source", "plan_id", "row_count", "snapshot_sha256"} or not item["source"]
            or item["plan_id"] not in PLANS | {None}
            or type(item["row_count"]) is not int or item["row_count"] < 0
            or not sha256_valid(item["snapshot_sha256"]) for item in sources)
            or len({item["source"] for item in sources}) != len(sources)
            or set(value["covered_plans"]) != {
                item["plan_id"] for item in sources if item["plan_id"] is not None}):
        return False
    names, seen, mapped, entry_aliases = {item["source"] for item in sources}, set(), set(), set()
    if not isinstance(value["entries"], list) or not isinstance(value["trial_redirects"], dict):
        return False
    for entry in value["entries"]:
        if set(entry) != {"source", "source_key_sha256", "trial_id", "disposition", "reason"}:
            return False
        key, disposition = entry.get("source_key_sha256"), entry.get("disposition")
        if entry.get("source") not in names or key in seen or not sha256_valid(key):
            return False
        seen.add(key)
        if disposition == "alias":
            if entry.get("trial_id") not in registrations \
                    or (entry["trial_id"], key) not in aliases:
                return False
            mapped.add(entry["trial_id"])
            entry_aliases.add((entry["trial_id"], key))
        elif disposition != "not_evaluated" or entry.get("trial_id") is not None \
                or not entry.get("reason"):
            return False
    if any(sum(entry.get("source") == item["source"] for entry in value["entries"])
           != item["row_count"] for item in sources) or entry_aliases != aliases:
        return False
    baselines, redirects = value["deterministic_baseline_trial_ids"], value["trial_redirects"]
    if (not isinstance(baselines, list)
            or len(baselines) != len(set(baselines)) or not set(baselines) <= attempted):
        return False
    if any(registrations[trial_id]["trial_kind"] != "deterministic_baseline"
           for trial_id in baselines):
        return False
    return all(isinstance(resolution, dict) and source in registrations
               and resolution.get("canonical_trial_id") in registrations
               and source != resolution["canonical_trial_id"]
               and resolution["canonical_trial_id"] not in redirects
               and _redirect_valid(registration_rows[source], registration_rows[
                   resolution["canonical_trial_id"]], resolution, events)
               for source, resolution in redirects.items())


def project(records: list[dict], *, limit: int) -> dict:
    registrations = {row["trial_id"]: row for row in records
                     if row["record_kind"] == "registration"}
    if len(registrations) != sum(row["record_kind"] == "registration" for row in records):
        raise ValueError("trial registration is duplicated")
    for trial_id, row in registrations.items():
        payload = row["payload"]
        try:
            actual_id, expected = registration(
                **{key: payload[key] for key in ("policy_id", "policy_version", "plan_id",
                   "registration_identity", "evidence_class", "parent_trial_ids",
                   "trial_kind", "identity_status")},
                registered_at=datetime.fromisoformat(payload["registered_at"]).replace(
                    tzinfo=timezone.utc))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("trial registration differs") from exc
        if actual_id != trial_id or expected != payload or row["event_at"] != payload["registered_at"]:
            raise ValueError("trial registration differs")
    events = {trial_id: [row for row in records if row["trial_id"] == trial_id
                         and row["record_kind"] != "registration"]
              for trial_id in registrations}
    if any(row["trial_id"] not in registrations for row in records
           if row["record_kind"] not in {"registration", "inventory_reconciliation"}):
        raise ValueError("trial event has no registration")
    if any(parent not in registrations
           or registrations[parent]["event_at"] > row["event_at"]
           for row in registrations.values() for parent in row["payload"]["parent_trial_ids"]):
        raise ValueError("trial parent differs")
    if any(event["event_at"] < registrations[trial_id]["event_at"]
           or event["recorded_at"] < registrations[trial_id]["recorded_at"]
           for trial_id, trial_events in events.items() for event in trial_events):
        raise ValueError("trial event predates registration")
    reconciliations = [row for row in records
                       if row["record_kind"] == "inventory_reconciliation"]
    latest_row = reconciliations[-1] if reconciliations else None
    sealed_records = [] if latest_row is None else [
        row for row in records if row["record_kind"] == "inventory_reconciliation"
        or row["recorded_at"] <= latest_row["recorded_at"]]
    valid = latest_row is not None and reconciliation_valid(latest_row["payload"], sealed_records)
    latest = latest_row["payload"] if valid else None
    redirects = {} if latest is None else {
        key: value["canonical_trial_id"] for key, value in latest["trial_redirects"].items()}
    current = valid and latest["register_sha256"] == register_digest(records)
    versions, attempted_ids, unresolved = [], set(), 0
    for trial_id, row in sorted(registrations.items()):
        trial_events = events[trial_id]
        attempts = [item for item in trial_events if item["record_kind"] in ATTEMPTS]
        if attempts:
            attempted_ids.add(redirects.get(trial_id, trial_id))
            unresolved += not _verified(row, trial_events) and trial_id not in redirects
        retired = [item for item in trial_events if item["record_kind"] == "retired"]
        latest_attempt = max(attempts, key=lambda item: (item["event_at"], item["record_sha256"])) \
            if attempts else None
        item = {"trial_id": trial_id, **row["payload"],
                "first_evaluated_at": min((item["event_at"] for item in attempts), default=None),
                "retired_at": min((item["event_at"] for item in retired), default=None),
                "status": "retired" if retired else latest_attempt["record_kind"]
                if latest_attempt else "registered",
                "alias_references": sorted(item["source_sha256"] for item in trial_events
                                           if item["record_kind"] == "alias")}
        item["identity_verified"] = _verified(row, trial_events)
        item["reconciled_to"] = redirects.get(trial_id)
        item["alias_count"] = len(item["alias_references"])
        versions.append(item)
    mapped = set() if latest is None else {entry["trial_id"] for entry in latest["entries"]
                                          if entry["disposition"] == "alias"}
    missing_plans = sorted(PLANS - (set() if latest is None else set(latest["covered_plans"])))
    unmapped = sorted({trial_id for trial_id, rows in events.items()
                       if any(row["record_kind"] in ATTEMPTS for row in rows)} - mapped)
    expected_baselines = {redirects.get(trial_id, trial_id) for trial_id, row in registrations.items()
                          if row["payload"]["trial_kind"] == "deterministic_baseline"
                          and any(event["record_kind"] in ATTEMPTS for event in events[trial_id])}
    missing_baselines = sorted(expected_baselines - (
        set() if latest is None else set(latest["deterministic_baseline_trial_ids"])))
    complete = current and not missing_plans and not unmapped and not unresolved \
        and bool(expected_baselines) and not missing_baselines
    status = "not_initialized" if not registrations else "unreconciled" if latest is None else \
        "stale" if not current else "complete" if complete else "incomplete"
    return {"status": status, "inventory_complete": status == "complete",
            "selection_trial_count": len(attempted_ids),
            "registered_trial_count": len(registrations),
            "unresolved_identity_count": unresolved,
            "identity_coverage": 1 - unresolved / len(attempted_ids) if attempted_ids else 1.0,
            "register_sha256": register_digest(records),
            "reconciliation_sha256": None if latest_row is None else latest_row["record_sha256"],
            "covered_plans": [] if latest is None else latest["covered_plans"],
            "missing_plans": missing_plans, "unmapped_trial_ids": unmapped,
            "missing_deterministic_baseline_trial_ids": missing_baselines,
            "versions": versions[:limit],
            "versions_truncated": len(versions) > limit, "execution_authority": "none"}
