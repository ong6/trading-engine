#!/usr/bin/env python
"""Proposal validator + applier — the code side of the agentic-books discipline.

`agentic-strategies-design.md` §The discipline, 1: *"A code-side validator
applies a proposal ONLY if it is inside that book's pre-registered bounds
(schema-enforced, not trust-the-model). Out-of-bounds → rejected + logged."*
This module is that validator. It is deliberately dull, deterministic and
model-free.

Two proposal kinds, one entry point:

* **tuner** (`adaptive_mr`, `agentic_alloc`, `stop_tuner_turtle`) — a JSON
  proposal to change numeric strategy parameters. Validated against the bounds
  block frozen in `agents/<book>/charter.md`, then written into the book's
  `portfolios.config` JSON with `agent_version` bumped.
* **gater** (`news_gated_momo`, `earnings_context_pead`) — a JSON list of
  veto/downscale decisions. Validated, then written to
  `agents/<book>/gate-<date>.json`, which `sim/strategies/base.py::apply_agent_gate`
  reads during the nightly.

Both paths append one row to `agents/<book>/changes.jsonl` — **for applied AND
rejected proposals alike**, because a record that only keeps the accepted
proposals cannot answer "what did the agent try to do?" at the 26-week review.

Parameter version recoverability: `changes.jsonl` carries `version_from` /
`version_to` and the dated diff, and the CURRENT version is stamped in the
config JSON. Any equity date therefore maps to the parameters it ran — walk
changes.jsonl forward from version 1 to the last row on or before that date.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from engine.lib.settings import REPO_ROOT

AGENTS_DIR = Path(__file__).resolve().parent
BOUNDS_RE = re.compile(r"<!--\s*BOUNDS\s*-->\s*```json\s*(.*?)```", re.S)


class Rejected(Exception):
    """An out-of-bounds / malformed proposal. Carries the reviewable reason."""


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# charter
# --------------------------------------------------------------------------- #
def load_bounds(book: str, agents_dir: Path = AGENTS_DIR) -> dict:
    """Parse the frozen bounds block out of `agents/<book>/charter.md`.

    The charter is the single source of truth: there is no second bounds file
    that could drift from the prose a human reads and reviews.
    """
    charter = agents_dir / book / "charter.md"
    m = BOUNDS_RE.search(charter.read_text(encoding="utf-8"))
    if not m:
        raise Rejected(f"charter {charter} has no <!-- BOUNDS --> json block")
    b = json.loads(m.group(1))
    if b.get("book") != book:
        raise Rejected(f"charter bounds name book {b.get('book')!r}, not {book!r}")
    if b.get("kind") not in ("tuner", "gater"):
        raise Rejected(f"charter bounds have unknown kind {b.get('kind')!r}")
    return b


# --------------------------------------------------------------------------- #
# tuner validation
# --------------------------------------------------------------------------- #
def _as_number(spec: dict, name: str, v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise Rejected(f"{name}: value {v!r} is not a number")
    if spec["type"] == "integer":
        if float(v) != int(v):
            raise Rejected(f"{name}: {v!r} is not an integer "
                           f"(this parameter is an integer by registration)")
        return int(v)
    return float(v)


def _check_simplex(name: str, spec: dict, current, proposed) -> dict:
    keys = spec["keys"]
    if not isinstance(proposed, dict):
        raise Rejected(f"{name}: expected an object keyed by {keys}")
    missing = [k for k in keys if k not in proposed]
    extra = [k for k in proposed if k not in keys]
    if missing or extra:
        raise Rejected(f"{name}: keys must be exactly {keys} "
                       f"(missing={missing}, unexpected={extra})")
    out = {}
    for k in keys:
        v = proposed[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise Rejected(f"{name}.{k}: value {v!r} is not a number")
        v = float(v)
        if v < spec["min"] - 1e-12 or v > spec["max"] + 1e-12:
            raise Rejected(f"{name}.{k} = {v} is outside the registered bound "
                           f"[{spec['min']}, {spec['max']}]")
        out[k] = v
    total = sum(out.values())
    tol = float(spec.get("sum_tol", 1e-6))
    if abs(total - float(spec["sum"])) > tol:
        raise Rejected(f"{name}: weights sum to {total:.6f}, must be "
                       f"{spec['sum']} ± {tol}")
    cur = {k: float((current or {}).get(k, spec["start"][k])) for k in keys}
    turnover = sum(abs(out[k] - cur[k]) for k in keys)
    cap = spec.get("max_total_turnover")
    if cap is not None and turnover > float(cap) + 1e-12:
        raise Rejected(f"{name}: total turnover Σ|Δw| = {turnover:.4f} exceeds "
                       f"the registered per-session cap of {cap}")
    return out


def _cross_checks(bounds: dict, params: dict) -> None:
    for c in bounds.get("cross_checks") or []:
        kind = c.get("kind")
        if kind == "product_max":
            vals = [float(params.get(p, 0)) for p in c["params"]]
            prod = 1.0
            for v in vals:
                prod *= v
            if prod > float(c["max"]) + 1e-12:
                raise Rejected(
                    f"cross-check failed: {' x '.join(c['params'])} = "
                    f"{prod:.4f} > {c['max']} — {c.get('why', '')}")
        elif kind == "ge":
            lo, hi = float(params.get(c["right"], 0)), float(params.get(c["left"], 0))
            if hi < lo - 1e-12:
                raise Rejected(
                    f"cross-check failed: {c['left']} ({hi}) must be >= "
                    f"{c['right']} ({lo}) — {c.get('why', '')}")
        else:
            raise Rejected(f"unknown cross-check kind {kind!r} in charter")


def validate_tuner(bounds: dict, current_params: dict, proposal: dict) -> tuple[dict, list]:
    """Return (new_params, changes) or raise Rejected.

    ALL-OR-NOTHING by design: one out-of-bounds entry rejects the whole
    proposal. Partially applying a proposal would apply a change stripped of
    the reasoning that justified it, and the rationale in changes.jsonl would
    then describe something that never happened.
    """
    if proposal.get("book") != bounds["book"]:
        raise Rejected(f"proposal names book {proposal.get('book')!r}, "
                       f"validator was invoked for {bounds['book']!r}")
    entries = proposal.get("proposal")
    if entries is None:
        raise Rejected("proposal has no `proposal` list (use [] for no change)")
    if not isinstance(entries, list):
        raise Rejected("`proposal` must be a list")

    specs = bounds["params"]
    seen: set[str] = set()
    new = dict(current_params)
    changes = []
    for e in entries:
        if not isinstance(e, dict) or "param" not in e or "to" not in e:
            raise Rejected(f"malformed proposal entry {e!r} "
                           f"(need {{'param': ..., 'to': ...}})")
        name = e["param"]
        if name not in specs:
            raise Rejected(
                f"{name!r} is NOT an adjustable parameter for this book. "
                f"Adjustable: {sorted(specs)}")
        if name in seen:
            raise Rejected(f"{name!r} appears more than once in the proposal")
        seen.add(name)
        spec = specs[name]
        cur = current_params.get(name, spec.get("start"))

        if spec["type"] == "simplex":
            val = _check_simplex(name, spec, cur, e["to"])
            if val == {k: float(v) for k, v in (cur or {}).items()}:
                continue
        else:
            val = _as_number(spec, name, e["to"])
            if val < spec["min"] - 1e-12 or val > spec["max"] + 1e-12:
                raise Rejected(f"{name} = {val} is outside the registered bound "
                               f"[{spec['min']}, {spec['max']}]")
            step_cap = bounds.get("max_relative_step")
            if step_cap is not None and cur not in (None, 0):
                rel = abs(val - float(cur)) / abs(float(cur))
                if rel > float(step_cap) + 1e-12:
                    raise Rejected(
                        f"{name}: {cur} → {val} is a {rel * 100:.1f}% move, "
                        f"above the registered per-session step cap of "
                        f"{float(step_cap) * 100:.0f}%")
            if val == cur:
                continue
        new[name] = val
        changes.append({"param": name, "from": cur, "to": val})

    max_ch = bounds.get("max_changes_per_session")
    if max_ch is not None and len(changes) > int(max_ch):
        raise Rejected(f"{len(changes)} parameter(s) changed, above the "
                       f"registered per-session limit of {max_ch}")
    _cross_checks(bounds, new)
    return new, changes


# --------------------------------------------------------------------------- #
# gater validation
# --------------------------------------------------------------------------- #
def validate_gater(bounds: dict, proposal: dict, n_candidates: int | None = None
                   ) -> tuple[dict, list[str]]:
    """Return (gate_dict, per-decision drop reasons) or raise Rejected.

    Two severities, on purpose:
      * a FILE-level violation (wrong book, too many decisions, vetoing more
        than the registered share of candidates) rejects the whole gate — no
        file is written and the nightly runs pure algo;
      * a ROW-level violation (bad action, out-of-range scale, missing reason)
        drops that ONE decision and keeps the rest. Discarding nine sound
        vetoes because a tenth row was malformed would be a worse outcome than
        the malformed row itself, and every drop is logged.
    """
    g = bounds["gate"]
    if proposal.get("book") != bounds["book"]:
        raise Rejected(f"proposal names book {proposal.get('book')!r}, "
                       f"validator was invoked for {bounds['book']!r}")
    raw = proposal.get("decisions")
    if raw is None or not isinstance(raw, list):
        raise Rejected("gate proposal has no `decisions` list")
    if len(raw) > int(g["max_decisions"]):
        raise Rejected(f"{len(raw)} decisions, above the registered maximum of "
                       f"{g['max_decisions']}")

    kept, dropped = [], []
    for d in raw:
        if not isinstance(d, dict):
            dropped.append(f"non-object decision {d!r}")
            continue
        tk = str(d.get("ticker") or "").strip().upper()
        act = d.get("action")
        if not tk:
            dropped.append(f"decision with no ticker: {d!r}")
            continue
        if act in (None, "pass", "take"):
            # Informational row (e.g. book 5's reaction class on a taken name).
            # Kept in the file for the 26-week review; apply_agent_gate ignores
            # anything that is not a veto/downscale.
            kept.append({"ticker": tk, "action": None,
                         "class": d.get("class"),
                         "reason": str(d.get("reason") or "")[:400]})
            continue
        if act not in g["allowed_actions"]:
            dropped.append(f"{tk}: action {act!r} not in {g['allowed_actions']} "
                           f"— an agent on this book may only subtract")
            continue
        reason = str(d.get("reason") or "").strip()
        if len(reason) < int(g["reason_min_chars"]):
            dropped.append(f"{tk}: reason too short ({len(reason)} chars, "
                           f"minimum {g['reason_min_chars']}) — an unstated "
                           f"veto is unreviewable")
            continue
        row = {"ticker": tk, "action": act, "reason": reason[:400],
               "class": d.get("class")}
        if act == "downscale":
            try:
                s = float(d.get("scale"))
            except (TypeError, ValueError):
                dropped.append(f"{tk}: downscale with no numeric scale")
                continue
            if s < float(g["min_scale"]) - 1e-12 or s > float(g["max_scale"]) + 1e-12:
                dropped.append(f"{tk}: scale {s} outside registered "
                               f"[{g['min_scale']}, {g['max_scale']}]")
                continue
            row["scale"] = s
        kept.append(row)

    n_veto = sum(1 for d in kept if d["action"] == "veto")
    share_cap = g.get("max_veto_share_of_candidates")
    if share_cap is not None and n_candidates:
        share = n_veto / float(n_candidates)
        if share > float(share_cap) + 1e-12:
            raise Rejected(
                f"{n_veto} veto(es) against {n_candidates} candidate(s) = "
                f"{share * 100:.0f}%, above the registered cap of "
                f"{float(share_cap) * 100:.0f}% — at that rate the agent is "
                f"replacing the strategy, not gating it")

    gate = {
        "book": bounds["book"],
        "generated_utc": utcnow(),
        "decisions": kept,
        "notes": str(proposal.get("notes") or "")[:2000],
        "n_candidates_seen": n_candidates,
    }
    return gate, dropped


# --------------------------------------------------------------------------- #
# persistence
# --------------------------------------------------------------------------- #
def append_change(book: str, row: dict, agents_dir: Path = AGENTS_DIR) -> None:
    p = agents_dir / book / "changes.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def append_lesson(book: str, when: str, lesson: str,
                  agents_dir: Path = AGENTS_DIR) -> None:
    lesson = (lesson or "").strip()
    if not lesson:
        return
    p = agents_dir / book / "lessons.md"
    with p.open("a", encoding="utf-8") as f:
        f.write(f"\n## {when} — session lesson\n\n{lesson}\n")


def read_config(con, book: str) -> dict:
    row = con.execute("SELECT config FROM portfolios WHERE id = ?",
                      [book]).fetchone()
    if not row or not row[0]:
        raise Rejected(f"book {book!r} has no portfolios row / no config JSON")
    return json.loads(row[0])


def write_config(con, book: str, cfg: dict) -> None:
    con.execute("UPDATE portfolios SET config = ? WHERE id = ?",
                [json.dumps(cfg), book])


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
def apply_proposal(db_path: str, book: str, proposal: dict, *,
                   run_date: str, session: str,
                   agents_dir: Path = AGENTS_DIR,
                   n_candidates: int | None = None,
                   dry_run: bool = False) -> dict:
    """Validate and (unless dry_run) apply. Always logs a changes.jsonl row.

    Returns a result dict; never raises for an out-of-bounds proposal — that is
    a normal, expected outcome and is recorded, not an error.
    """
    from engine.lib import db  # noqa: PLC0415

    bounds = load_bounds(book, agents_dir)
    kind = bounds["kind"]
    base = {"ts": utcnow(), "date": run_date, "book": book, "kind": kind,
            "session": session, "rationale": str(proposal.get("rationale")
                                                 or proposal.get("notes") or "")[:4000],
            "evidence": [str(e)[:500] for e in (proposal.get("evidence") or [])][:20]}

    # ---- gater ---------------------------------------------------------- #
    if kind == "gater":
        try:
            gate, dropped = validate_gater(bounds, proposal, n_candidates)
        except Rejected as exc:
            row = dict(base, status="rejected", version_from=None,
                       version_to=None, changes=[], reject_reason=str(exc))
            append_change(book, row, agents_dir)
            print(f"[validator] REJECTED gate for {book}: {exc}")
            return {"status": "rejected", "reason": str(exc)}
        gate["date"] = run_date
        gate["dropped"] = dropped
        out = agents_dir / book / f"gate-{run_date}.json"
        if not dry_run:
            out.write_text(json.dumps(gate, indent=2, sort_keys=True) + "\n")
        acts = [d for d in gate["decisions"] if d["action"]]
        row = dict(base, status="applied", version_from=None, version_to=None,
                   changes=[{"param": "gate", "from": None,
                             "to": f"{sum(1 for d in acts if d['action'] == 'veto')} veto / "
                                   f"{sum(1 for d in acts if d['action'] == 'downscale')} downscale"}],
                   reject_reason=None, dropped_decisions=dropped,
                   gate_file=str(out.relative_to(REPO_ROOT)))
        append_change(book, row, agents_dir)
        append_lesson(book, run_date, proposal.get("lesson", ""), agents_dir)
        for d in dropped:
            print(f"[validator] dropped decision — {d}")
        print(f"[validator] {book}: wrote {out.name} with {len(acts)} "
              f"actionable decision(s), {len(dropped)} dropped")
        return {"status": "applied", "gate_file": str(out),
                "n_actionable": len(acts), "dropped": dropped}

    # ---- tuner ---------------------------------------------------------- #
    con = None
    try:
        con = db.connect(db_path)
        cfg = read_config(con, book)
        cur = dict(cfg.get("params", {}))
        version = int(cur.get("agent_version", 1))
        new_params, changes = validate_tuner(bounds, cur, proposal)
    except Rejected as exc:
        if con is not None:
            con.close()
        row = dict(base, status="rejected", version_from=None, version_to=None,
                   changes=[], reject_reason=str(exc))
        append_change(book, row, agents_dir)
        print(f"[validator] REJECTED proposal for {book}: {exc}")
        return {"status": "rejected", "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 — a locked store is the common case
        if con is not None:
            con.close()
        reason = f"could not read the book's config: {exc}"
        row = dict(base, status="rejected", version_from=None, version_to=None,
                   changes=[], reject_reason=reason)
        append_change(book, row, agents_dir)
        print(f"[validator] REJECTED (infrastructure) for {book}: {reason}")
        return {"status": "rejected", "reason": reason}

    if not changes:
        con.close()
        row = dict(base, status="applied", version_from=version,
                   version_to=version, changes=[], reject_reason=None)
        append_change(book, row, agents_dir)
        append_lesson(book, run_date, proposal.get("lesson", ""), agents_dir)
        print(f"[validator] {book}: proposal is a NO-CHANGE "
              f"(version stays {version})")
        return {"status": "applied", "version": version, "changes": []}

    new_version = version + 1
    new_params["agent_version"] = new_version
    new_params["agent_version_since"] = run_date
    cfg["params"] = new_params
    if not dry_run:
        write_config(con, book, cfg)
    con.close()
    row = dict(base, status="applied", version_from=version,
               version_to=new_version, changes=changes, reject_reason=None)
    append_change(book, row, agents_dir)
    append_lesson(book, run_date, proposal.get("lesson", ""), agents_dir)
    diff = ", ".join(f"{c['param']} {c['from']}→{c['to']}" for c in changes)
    print(f"[validator] {book}: APPLIED v{version}→v{new_version} — {diff}"
          + ("  (dry run, config NOT written)" if dry_run else ""))
    return {"status": "applied", "version": new_version, "changes": changes}


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate + apply an agent proposal.")
    ap.add_argument("--book", required=True)
    ap.add_argument("--proposal", required=True, help="path to the JSON proposal")
    ap.add_argument("--db", default=None)
    ap.add_argument("--agents-dir", default=str(AGENTS_DIR))
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--session", default="manual")
    ap.add_argument("--n-candidates", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    from engine.lib import db  # noqa: PLC0415
    db_path = a.db or str(db.DEFAULT_DB)
    try:
        proposal = json.loads(Path(a.proposal).read_text())
    except Exception as exc:  # noqa: BLE001
        print(f"[validator] unreadable proposal file: {exc}")
        return 1
    res = apply_proposal(db_path, a.book, proposal, run_date=a.date,
                         session=a.session, agents_dir=Path(a.agents_dir),
                         n_candidates=a.n_candidates, dry_run=a.dry_run)
    print(json.dumps(res, indent=2, default=str))
    # A rejected proposal is a NORMAL outcome, not a script failure: the wrapper
    # must not treat "the agent proposed something out of bounds" as an error
    # that needs a human. Exit 0 either way; the record is in changes.jsonl.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
