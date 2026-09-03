#!/usr/bin/env python3
"""Assemble the prompt for ONE tuner book's weekly session — input side only.

The evidence diet is the spec's, and it is a CLOSED list: charter, lessons,
change history, league standings + the AI-vs-twin spread, trade autopsies
(MAE/MFE, hold times, stop hits), the walk-forward report for the book and its
twin, the execution-drag report, the macro_signals composite reading, and the
latest news brief. Nothing else, and the model gets zero tools — every input is
assembled here and every output is written by the wrapper.

Runs Sunday 10:30 UTC, after the 06:00 UTC walk-forward grid (~3h) has landed,
so the session reads a fresh out-of-sample re-validation rather than last
week's.

READ-ONLY throughout. Every section degrades to a stated "unavailable" line
rather than failing the run: a tuner session that cannot see one input should
still be able to decline to change anything, which is the correct default.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

from engine.lib import db
from engine.lib.settings import DATA_DIR, REPO_ROOT

AGENTS_DIR = REPO_ROOT / "agents"
REPORTS = DATA_DIR / "reports"
DB_PATH = db.DEFAULT_DB
PROMPT_FILE = AGENTS_DIR / "tuner_prompt.md"
PY = REPO_ROOT / ".venv" / "bin" / "python"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read(path: Path, limit: int | None = None) -> str:
    try:
        t = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return f"(unavailable: {exc})"
    if limit and len(t) > limit:
        return t[:limit] + f"\n\n_(truncated at {limit} chars)_"
    return t


def tail_jsonl(path: Path, n: int = 30) -> str:
    try:
        lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    except Exception as exc:  # noqa: BLE001
        return f"(unavailable: {exc})"
    if not lines:
        return "_(no proposals yet — this is the first session)_"
    out = []
    for l in lines[-n:]:
        try:
            r = json.loads(l)
        except Exception:  # noqa: BLE001
            continue
        diff = ", ".join(f"{c['param']} {c['from']}→{c['to']}"
                         for c in (r.get("changes") or [])) or "(no change)"
        out.append(f"- **{r.get('date')}** · {r.get('status')} · "
                   f"v{r.get('version_from')}→v{r.get('version_to')} · {diff}"
                   + (f" · REJECTED: {r.get('reject_reason')}"
                      if r.get("reject_reason") else "")
                   + f"\n  rationale: {str(r.get('rationale') or '')[:400]}")
    return "\n".join(out) or "_(no readable proposals yet)_"


def connect_ro(db_path: Path = DB_PATH, retries: int = 6, sleep_s: float = 5.0):
    # Thin wrapper over the one connection factory (engine.lib.db.connect).
    try:
        return db.connect(db_path, read_only=True, wait_s=retries * sleep_s)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"store locked after {retries} attempts: {exc}") from exc


def current_params(con, book: str) -> tuple[dict, int]:
    row = con.execute("SELECT config FROM portfolios WHERE id = ?",
                      [book]).fetchone()
    if not row or not row[0]:
        return {}, 1
    p = json.loads(row[0]).get("params", {})
    return p, int(p.get("agent_version", 1))


def spread_vs_twin(con, book: str, twin: str) -> str:
    """AI-vs-twin spread on the COMMON window, both rebased to 1.00.

    The twins for three of the five books are pre-existing live books with an
    earlier inception, so a raw inception-to-date comparison would be measuring
    the head start, not the agent. Rebasing on the first shared session is the
    only honest reading — see data/reports/agentic/ for the same computation.
    """
    try:
        rows = con.execute(
            "SELECT date, portfolio_id, equity FROM sim_equity "
            "WHERE portfolio_id IN (?, ?) ORDER BY date", [book, twin]).fetchall()
    except Exception as exc:  # noqa: BLE001
        return f"(unavailable: {exc})"
    a = {d: e for d, p, e in rows if p == book}
    b = {d: e for d, p, e in rows if p == twin}
    common = sorted(set(a) & set(b))
    if not common:
        return (f"_(no session yet on which both `{book}` and `{twin}` have "
                f"equity — the spread is not measurable and the correct "
                f"reading of that is 'no evidence', not 'no difference')_")
    d0 = common[0]
    a0, b0 = a[d0], b[d0]
    lines = [f"Common window opens **{d0}** ({len(common)} session(s)). "
             f"Both books rebased to 1.0000 on that date.", "",
             "| Date | AI index | Twin index | Spread |", "|---|---|---|---|"]
    for d in common[-15:]:
        ai, tw = a[d] / a0, b[d] / b0
        lines.append(f"| {d} | {ai:.4f} | {tw:.4f} | "
                     f"{'+' if ai - tw >= 0 else '−'}{abs(ai - tw) * 100:.2f}% |")
    ai, tw = a[common[-1]] / a0, b[common[-1]] / b0
    lines += ["", f"**Latest spread (AI − twin): "
                  f"{'+' if ai - tw >= 0 else '−'}{abs(ai - tw) * 100:.2f}%** "
                  f"over {len(common)} session(s)."]
    return "\n".join(lines)


def macro_reading(con, as_of) -> str:
    """The composite's four block votes and the tier they imply."""
    try:
        from sim.strategies import macro_composite as mc
        warned: list[str] = []

        def warn(m):
            warned.append(m)

        vb, ib = mc._block_breadth(con, as_of, warn)
        vc, ic = mc._block_credit(con, as_of, warn)
        vv, iv = mc._block_vol(con, as_of, warn)
        vm, im = mc._block_macro(con, as_of, warn)
        score = vb + vc + vv + vm
        return (f"as of {as_of} — breadth {vb:+d}, credit {vc:+d} "
                f"(source {ic.get('source')}), vol-term-structure {vv:+d}, "
                f"macro {vm:+d} → composite score **{score:+d}** → implied SPY "
                f"tier **{mc._tier(score):.2f}**"
                + (f"\n\nMissing series this week: {'; '.join(warned)}"
                   if warned else ""))
    except Exception as exc:  # noqa: BLE001
        return f"(unavailable: {exc})"


def peer_books(con, book: str) -> list[str]:
    """Every live book running the SAME strategy module as this one.

    An AI book and its purpose-built frozen twin are both created on day one, so
    for the first weeks of their lives NEITHER has a closed trade and the tuner
    has literally no autopsy to read (observed on the very first real session,
    2026-08-04: adaptive_mr proposed no change and was right to). The ancestor
    book this one was cloned from has been trading the identical algorithm for
    weeks. Its trade record is not evidence about THIS book's spread — it can
    never be, and the prompt says so — but it is real evidence about how this
    ALGORITHM behaves, which is exactly what a stop or a time-stop parameter
    question is about.
    """
    try:
        strat = con.execute("SELECT strategy FROM portfolios WHERE id = ?",
                            [book]).fetchone()
        if not strat:
            return []
        rows = con.execute(
            "SELECT id FROM portfolios WHERE strategy = ? AND active ORDER BY id",
            [strat[0]]).fetchall()
        return [r[0] for r in rows]
    except Exception:  # noqa: BLE001
        return []


def autopsy_md(books: list[str], db_path: str) -> str:
    """Shell out to the read-only autopsy extractor (its own RO connection)."""
    args = []
    for b in books:
        args += ["--book", b]
    try:
        r = subprocess.run(
            [str(PY), "-m", "farm.autopsy", *args,
             "--db", db_path],
            capture_output=True, text=True, timeout=600, cwd=str(REPO_ROOT))
        if r.returncode != 0:
            return f"(unavailable: autopsy exited {r.returncode}: {r.stderr[-500:]})"
        return r.stdout.strip() or "(no closed trades yet)"
    except Exception as exc:  # noqa: BLE001
        return f"(unavailable: {exc})"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--prompt-out", required=True)
    ap.add_argument("--meta-out", required=True)
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--agents-dir", default=str(AGENTS_DIR))
    # --db exists so the whole loop can be shaken down against a COPY of the
    # store; production always uses the default.
    ap.add_argument("--db", default=str(DB_PATH))
    a = ap.parse_args()

    agents_dir = Path(a.agents_dir)
    from agents.validator import load_bounds  # noqa: PLC0415

    bounds = load_bounds(a.book, agents_dir)
    twin = bounds["twin"]
    meta = {"book": a.book, "twin": twin, "date": a.date,
            "generated_utc": utcnow(), "db_ok": True, "book_exists": True,
            "version": 1}

    params: dict = {}
    peers: list[str] = []
    spread = league = macro = "(unavailable: store locked)"
    try:
        con = connect_ro(Path(a.db))
        try:
            params, version = current_params(con, a.book)
            peers = peer_books(con, a.book)
            meta["version"] = version
            meta["book_exists"] = bool(params)
            as_of = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
            meta["bars_as_of"] = str(as_of)
            spread = spread_vs_twin(con, a.book, twin)
            macro = macro_reading(con, as_of)
            league = read(REPORTS / "league.md", 8000)
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001
        meta["db_ok"] = False
        meta["db_error"] = str(exc)

    Path(a.meta_out).write_text(json.dumps(meta, indent=2) + "\n")
    if not meta["book_exists"]:
        Path(a.prompt_out).write_text("")
        return 0

    parts = [
        read(PROMPT_FILE),
        "", "---", "",
        f"## INPUT A — This book's FROZEN CHARTER (`{a.book}`)", "",
        read(agents_dir / a.book / "charter.md"),
        "", "---", "",
        "## INPUT B — Currently applied parameters (the live `portfolios` row)",
        "",
        "```json", json.dumps(params, indent=2, sort_keys=True), "```",
        "",
        f"Current parameter version: **{meta['version']}**. A change you propose "
        f"becomes version {meta['version'] + 1}.",
        "", "---", "",
        "## INPUT C — Lessons so far (append-only memory)", "",
        read(agents_dir / a.book / "lessons.md", 25000),
        "", "---", "",
        "## INPUT D — Every previous proposal, applied AND rejected", "",
        tail_jsonl(agents_dir / a.book / "changes.jsonl"),
        "", "---", "",
        f"## INPUT E — AI-vs-twin spread (`{a.book}` vs `{twin}`)",
        "",
        "**This is the only number that decides this book's fate at the "
        "26-week evaluation.** It is not a target to optimise week to week — "
        "see the standing instructions.",
        "", spread,
        "", "---", "",
        "## INPUT F — Trade autopsies",
        "",
        "MAE = worst adverse excursion from entry (uses the session LOW). "
        "MFE = best excursion (uses the HIGH). `gave_back` = MFE minus the "
        "realised return. Statistics over an empty set read `·`, never 0.",
        "",
        f"Covers `{a.book}`, its twin `{twin}`, and every other live book "
        f"running the SAME strategy module "
        f"({', '.join(f'`{p}`' for p in peers) or 'none'}). **The peer books' "
        f"records are evidence about the ALGORITHM, not about this book's "
        f"spread** — they have different inceptions and, in the gated cases, "
        f"different entry sets. Cite them as algorithm evidence; never treat a "
        f"peer's return as this book's.",
        "", autopsy_md(sorted(set([a.book, twin] + peers)), a.db),
        "", "---", "",
        "## INPUT G — Walk-forward re-validation (out-of-sample evidence)",
        "",
        read(REPORTS / "walkforward" / f"{a.book}.md", 12000),
        "",
        f"### Twin (`{twin}`) walk-forward", "",
        read(REPORTS / "walkforward" / f"{twin}.md", 12000),
        "", "---", "",
        "## INPUT H — Execution drag (modelled fill vs the bar)", "",
        read(REPORTS / "execution-drag.md", 6000),
        "", "---", "",
        "## INPUT I — Macro composite reading (regime context)", "", macro,
        "", "---", "",
        "## INPUT J — Latest news brief", "",
        read(REPORTS / "news" / "latest.md", 12000),
        "", "---", "",
        f"Today is {a.date}. Produce your proposal for `{a.book}` now, as a "
        f"single JSON object and nothing else, following the output contract at "
        f"the top. Proposing no change is a valid and frequently correct answer.",
        "",
    ]
    Path(a.prompt_out).write_text("\n".join(parts), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
