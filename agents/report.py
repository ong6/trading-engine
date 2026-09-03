#!/usr/bin/env python
"""Render data/reports/agentic/ — the AI-vs-frozen-twin scoreboard.

Five "agentic" league books each pair an algorithmic core with an AI agent that
may only make BOUNDED adjustments (a gater vetoes/downscales entries; a tuner
moves parameters inside its charter's bounds once a week). Each AI book is
measured ONLY against its **frozen twin** — the identical algo with
never-adjusted parameters. The twin is the control; nothing else is.

This module is a pure render. It opens the store READ ONLY, creates no tables,
writes nothing outside `--out-dir`, and never invents a number: state that does
not exist yet renders as an explicit "no data yet" row.

THE MEASUREMENT RULE THAT MATTERS
---------------------------------
Three of the twins (`momo_stopped`, `turtle_breakout`, `pead_ear`) are
pre-existing live books whose inception (2026-07-28) is EARLIER than the AI
books' (2026-08-04). Raw total returns from different inceptions are not
comparable and are never printed side by side here. Instead both equity series
are rebased to 1.0 at the **first date on which both books have a `sim_equity`
row** — the common window — and the spread is measured from there. Every row
states its own common-window start.

Inputs consumed (all defined elsewhere; this module invents no variants):
  store/market.duckdb        portfolios / sim_equity / sim_fills / prices
  agents/<book>/charter.md   frozen charter (linked, not parsed)
  agents/<book>/changes.jsonl  append-only tuner/gater change proposals
  agents/<book>/lessons.md   append-only; only the `## ` entry count is used
  agents/<book>/gate-<date>.json  a gater book's daily decision file

Usage:
    .venv/bin/python -m agents.report
    .venv/bin/python -m agents.report --out-dir /tmp/agentic-smoke
"""
from __future__ import annotations

import argparse
import json
import statistics
from datetime import date, datetime, timezone
from pathlib import Path

from engine.lib import db
from engine.lib.settings import DATA_DIR, DEFAULT_DB, REPO_ROOT

DEFAULT_OUT_DIR = DATA_DIR / "reports" / "agentic"
DEFAULT_AGENTS_DIR = REPO_ROOT / "agents"

# Pre-registered at program launch. The agent loop — not the algo book — is what
# gets killed if the spread is not there at the evaluation date.
EVALUATION_DATE = date(2027, 2, 1)
HORIZON_WEEKS = 26
# Forward window used to judge a gater's selection calls.
FWD_SESSIONS = 5

# ai book -> (frozen twin, agent role). Frozen and exhaustive: a book not in this
# table is not part of the program.
PAIRS: list[dict] = [
    {"ai": "news_gated_momo",      "twin": "momo_stopped",         "role": "gater",
     "note": "vetoes / downscales entries on news"},
    {"ai": "adaptive_mr",          "twin": "adaptive_mr_frozen",   "role": "tuner",
     "note": "weekly mean-reversion params"},
    {"ai": "agentic_alloc",        "twin": "agentic_alloc_frozen", "role": "tuner",
     "note": "weekly sleeve weights"},
    {"ai": "stop_tuner_turtle",    "twin": "turtle_breakout",      "role": "tuner",
     "note": "weekly stop / breakout params"},
    {"ai": "earnings_context_pead", "twin": "pead_ear",            "role": "gater",
     "note": "vetoes / downscales entries on earnings context"},
]

DISCLOSURES = """\
## Disclosures — read before any number below

1. **The spread is the ONLY measure.** Each AI book is scored against its frozen
   twin and against nothing else — not SPY, not the league table, not its own
   absolute return. The twin runs the same algo with never-adjusted parameters,
   so the difference is the closest thing to a clean read on whether the agent's
   bounded adjustments added anything. An AI book that is up while its twin is
   up more has **lost**.
2. **Different inceptions are rebased, never subtracted raw.** `momo_stopped`,
   `turtle_breakout` and `pead_ear` are pre-existing live books with an earlier
   inception than the AI books that shadow them. Every spread below is computed
   on the **common overlapping window only**: both equity curves are rebased to
   1.0 at the first session on which both books have a `sim_equity` row, and the
   spread runs from there. The common-window start is printed on every row. No
   number on this page compares total returns measured from different days.
3. **The window is short and the sample is tiny.** Weeks elapsed are printed
   against the 26-week horizon. At this length the spread is dominated by a
   handful of fills; it is a diagnostic, not a result. Nothing here is
   statistically significant and nothing here should be read as though it were.
4. **Paper fills.** Every number is simulated — t+1-open fills with the league's
   slippage and liquidity guards. No agent has ever moved real money, and the
   fill assumptions flatter both sides of the spread roughly equally.
5. **No mid-stream re-registration.** The charter (bounds, objective, kill
   criterion) is frozen at book creation. If a charter is edited, the book's
   record restarts — it is not spliced onto the old one. The change log below is
   append-only and rejected proposals are shown, not hidden: a loop that
   proposes badly and self-rejects is a different animal from one that never
   proposes.
6. **The 26-week kill criterion applies to the AGENT LOOP, not the algo book.**
   If the spread is not positive at the evaluation date, what gets switched off
   is the agent's authority to adjust — the underlying algorithmic book keeps
   trading as its own frozen twin. Killing the loop is a cheap, reversible,
   pre-registered act; it is not a verdict on the strategy.
7. **A veto's counterfactual is only observable through the twin.** The AI book
   never took the vetoed name, so its outcome is unknowable from the AI book's
   own fills. The only honest counterfactual is what the TWIN did on the same
   signal, and it exists only where the twin actually bought the name. Vetoes
   the twin also skipped are reported and excluded from the hit rate — there is
   no counterfactual to score.
"""


# --------------------------------------------------------------------------- #
# formatting
# --------------------------------------------------------------------------- #
def _pct(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "·"
    return f"{'+' if v >= 0 else '−'}{abs(v) * 100:.2f}%"


def _rate(v) -> str:
    """A share of a count — never a signed return."""
    if v is None or (isinstance(v, float) and v != v):
        return "·"
    return f"{v * 100:.0f}%"


def _money(v) -> str:
    return "·" if v is None else f"${v:,.0f}"


def _idx(v) -> str:
    return "·" if v is None else f"{v:.4f}"


def _max_drawdown(equity: list[float]) -> float:
    """Same definition as sim/league.py::_max_drawdown (copied, not imported, to
    keep this module a dependency-free pure render)."""
    peak = -1e18
    mdd = 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            mdd = min(mdd, e / peak - 1)
    return mdd


def _mean(xs):
    return statistics.fmean(xs) if xs else None


def _median(xs):
    return statistics.median(xs) if xs else None


def _rel(p: Path) -> str:
    """Repo-relative when it is inside the repo, absolute otherwise (the agents
    dir is redirectable via --agents-dir)."""
    try:
        return str(p.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def _esc(s) -> str:
    """Make free text safe inside a markdown table cell."""
    return str(s or "").replace("|", "\\|").replace("\n", " ").strip()


# --------------------------------------------------------------------------- #
# read-only DB access
# --------------------------------------------------------------------------- #
def connect_ro(db_path: Path, attempts: int = 5):
    """Read-only connection with a short retry.

    engine/queue_runner.py and the nightly take a write lock and DuckDB is
    single-writer, so a transient conflict is normal and must not fail a report
    run (same pattern as engine/news_analyst_prep.py::open_positions).
    """
    # Thin wrapper over the one connection factory (engine.lib.db.connect);
    # ~sum(2*(i+1)) seconds of the old backoff ≈ attempts*(attempts+1).
    try:
        return db.connect(db_path, read_only=True, wait_s=attempts * (attempts + 1))
    except Exception as e:  # locked by the nightly / farm drain
        raise SystemExit(f"[agentic-report] could not open {db_path} read-only "
                         f"after {attempts} attempts: {e}") from e


def _q(con, sql: str, params: list | None = None) -> list[tuple]:
    """Query that degrades to [] if the table simply isn't there yet."""
    try:
        return con.execute(sql, params or []).fetchall()
    except Exception:
        return []


def load_book(con, book_id: str) -> dict:
    """Everything the store knows about one book. `exists` False ⇒ not created."""
    row = _q(con, "SELECT id, name, created, active, config FROM portfolios "
                  "WHERE id = ?", [book_id])
    if not row:
        return {"id": book_id, "exists": False, "equity": [], "agent_version": None}
    _id, name, created, active, config = row[0]
    version = 1
    try:
        cfg = json.loads(config) if config else {}
        version = int(cfg.get("agent_version", 1))
    except Exception:
        version = 1
    eq = _q(con, "SELECT date, equity FROM sim_equity WHERE portfolio_id = ? "
                 "ORDER BY date", [book_id])
    return {"id": book_id, "exists": True, "name": name or book_id,
            "created": created, "active": bool(active), "agent_version": version,
            "equity": [(d, float(e)) for d, e in eq]}


def sessions(con) -> list[date]:
    """The market session calendar — distinct `prices` dates, ascending."""
    return [r[0] for r in _q(con, "SELECT DISTINCT date FROM prices ORDER BY date")]


def next_session(cal: list[date], d: date) -> date | None:
    for s in cal:
        if s > d:
            return s
    return None


def fwd_return(con, ticker: str, from_date: date, ref_px: float,
               n: int = FWD_SESSIONS):
    """close(from_date + n of THIS ticker's own bars) / ref_px − 1.

    Returns None when the +n bar does not exist yet — the caller must render that
    as `pending`, never as 0 and never extrapolated. Counting on the ticker's own
    bars (not the global calendar) means a name with a missing bar is measured
    over its own next n prints; that is disclosed rather than silently patched.
    """
    if not ref_px:
        return None
    bars = _q(con, "SELECT close FROM prices WHERE ticker = ? AND date > ? "
                   "ORDER BY date LIMIT ?", [ticker, from_date, n])
    if len(bars) < n or bars[-1][0] is None:
        return None
    return float(bars[-1][0]) / float(ref_px) - 1


def buys_on(con, book_id: str, d: date) -> list[dict]:
    rows = _q(con, "SELECT ticker, qty, fill_px FROM sim_fills WHERE "
                   "portfolio_id = ? AND side = 'buy' AND fill_date = ? "
                   "ORDER BY ticker", [book_id, d])
    return [{"ticker": t, "qty": q, "fill_px": p} for t, q, p in rows]


# --------------------------------------------------------------------------- #
# on-disk agent state
# --------------------------------------------------------------------------- #
def load_changes(agents_dir: Path, book_id: str) -> list[dict]:
    """changes.jsonl, in file order. A torn last line is skipped, not fatal."""
    p = agents_dir / book_id / "changes.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def load_gates(agents_dir: Path, book_id: str) -> list[dict]:
    """Every gate-YYYY-MM-DD.json for a gater book, oldest first."""
    d = agents_dir / book_id
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("gate-*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        rec.setdefault("date", p.stem.replace("gate-", ""))
        rec["_file"] = p.name
        out.append(rec)
    return sorted(out, key=lambda r: str(r.get("date")))


def lessons_count(agents_dir: Path, book_id: str) -> int | None:
    p = agents_dir / book_id / "lessons.md"
    if not p.exists():
        return None
    return sum(1 for ln in p.read_text(encoding="utf-8").splitlines()
               if ln.startswith("## "))


def charter_path(agents_dir: Path, book_id: str) -> Path | None:
    p = agents_dir / book_id / "charter.md"
    return p if p.exists() else None


# --------------------------------------------------------------------------- #
# the pair measurement
# --------------------------------------------------------------------------- #
def pair_metrics(ai: dict, twin: dict) -> dict:
    """AI vs twin over the COMMON overlapping window only.

    Both curves are rebased to 1.0 at the first session both books have an equity
    row for. `spread` = ai_return − twin_return, both measured from that session.
    """
    out = {"status": "ok", "common_start": None, "common_end": None,
           "n_sessions": 0, "ai_ret": None, "twin_ret": None, "spread": None,
           "ai_mdd": None, "twin_mdd": None, "series": []}
    if not ai["exists"] or not twin["exists"]:
        missing = [b["id"] for b in (ai, twin) if not b["exists"]]
        out["status"] = "not-created"
        out["detail"] = "not in `portfolios`: " + ", ".join(missing)
        return out
    if not ai["equity"] or not twin["equity"]:
        empty = [b["id"] for b in (ai, twin) if not b["equity"]]
        out["status"] = "no-equity"
        out["detail"] = "no `sim_equity` rows yet: " + ", ".join(empty)
        return out

    twin_by_date = dict(twin["equity"])
    common = [(d, e, twin_by_date[d]) for d, e in ai["equity"] if d in twin_by_date]
    if not common:
        out["status"] = "no-overlap"
        out["detail"] = (f"AI equity {ai['equity'][0][0]}→{ai['equity'][-1][0]}, "
                         f"twin {twin['equity'][0][0]}→{twin['equity'][-1][0]} "
                         f"— no shared session yet")
        return out

    base_ai, base_twin = common[0][1], common[0][2]
    if not base_ai or not base_twin:
        out["status"] = "no-overlap"
        out["detail"] = "the first shared session has zero/NULL equity"
        return out

    series = [{"date": d, "ai": a, "twin": t,
               "ai_idx": a / base_ai, "twin_idx": t / base_twin,
               "spread": a / base_ai - t / base_twin} for d, a, t in common]
    out.update({
        "common_start": common[0][0], "common_end": common[-1][0],
        "n_sessions": len(common),
        "ai_ret": series[-1]["ai_idx"] - 1,
        "twin_ret": series[-1]["twin_idx"] - 1,
        "spread": series[-1]["ai_idx"] - series[-1]["twin_idx"],
        # Drawdowns are measured over the same common window, so they are
        # comparable to each other rather than to each book's whole life.
        "ai_mdd": _max_drawdown([s["ai"] for s in series]),
        "twin_mdd": _max_drawdown([s["twin"] for s in series]),
        "series": series,
    })
    return out


def weeks_elapsed(start, end) -> float | None:
    if not start or not end:
        return None
    return (end - start).days / 7.0


# --------------------------------------------------------------------------- #
# veto hit-rate — gater books only
# --------------------------------------------------------------------------- #
def veto_analysis(con, cal: list[date], ai_id: str, twin_id: str,
                  gates: list[dict]) -> dict:
    """The honest read on a gater's SELECTION calls.

    For every gate file dated D, the decisions bite on the NEXT session (orders
    are generated on D's close and fill at the next open). For each:

      * veto   — did the TWIN buy that name on the next session? If yes the veto
                 had a real effect and the counterfactual is observable: score
                 the name's +5-session return from the TWIN's fill price. A veto
                 is CORRECT when that return is negative. If the twin also
                 skipped the name there is nothing to score, and it is reported
                 as `no-twin-entry`, not as a win.
      * taken  — a buy the AI book actually filled on the next session: score its
                 +5-session return from its OWN fill price.
      * downscale — recorded, but NEVER counted in the hit rate. It changes size,
                 not selection, so it cannot be right or wrong about a name.

    Names whose +5-session bar does not exist yet are `pending`: reported, never
    dropped, never extrapolated.
    """
    res = {"available": True, "n_gate_files": len(gates), "vetoes": [],
           "downscales": [], "taken": []}
    if not gates:
        res["available"] = False
        return res

    for g in gates:
        try:
            gd = date.fromisoformat(str(g.get("date")))
        except Exception:
            continue
        nxt = next_session(cal, gd)
        decisions = g.get("decisions") or []

        for dec in decisions:
            tk = dec.get("ticker")
            action = (dec.get("action") or "").lower()
            base = {"gate_date": gd, "next_session": nxt, "ticker": tk,
                    "reason": dec.get("reason"), "scale": dec.get("scale")}
            if action == "downscale":
                res["downscales"].append(base)
                continue
            if action != "veto":
                continue
            rec = dict(base, twin_bought=False, fill_px=None, fwd=None,
                       status="no-session-yet" if nxt is None else "no-twin-entry")
            if nxt is not None:
                twin_buy = next((b for b in buys_on(con, twin_id, nxt)
                                 if b["ticker"] == tk), None)
                if twin_buy:
                    rec["twin_bought"] = True
                    rec["fill_px"] = twin_buy["fill_px"]
                    fwd = fwd_return(con, tk, nxt, twin_buy["fill_px"])
                    rec["fwd"] = fwd
                    rec["status"] = "pending" if fwd is None else "resolved"
            res["vetoes"].append(rec)

        # Entries the AI book actually took on the same session the gate bit on.
        if nxt is not None:
            for b in buys_on(con, ai_id, nxt):
                fwd = fwd_return(con, b["ticker"], nxt, b["fill_px"])
                res["taken"].append({
                    "gate_date": gd, "next_session": nxt, "ticker": b["ticker"],
                    "fill_px": b["fill_px"], "fwd": fwd,
                    "status": "pending" if fwd is None else "resolved"})

    vet_scored = [v["fwd"] for v in res["vetoes"]
                  if v["twin_bought"] and v["status"] == "resolved"]
    taken_scored = [t["fwd"] for t in res["taken"] if t["status"] == "resolved"]
    res.update({
        "n_vetoes": len(res["vetoes"]),
        "n_vetoes_twin_bought": sum(1 for v in res["vetoes"] if v["twin_bought"]),
        "n_vetoes_pending": sum(1 for v in res["vetoes"] if v["status"] == "pending"),
        "n_vetoes_no_counterfactual": sum(
            1 for v in res["vetoes"] if v["status"] == "no-twin-entry"),
        "n_downscales": len(res["downscales"]),
        "n_taken": len(res["taken"]),
        "n_taken_pending": sum(1 for t in res["taken"] if t["status"] == "pending"),
        "veto_mean": _mean(vet_scored), "veto_median": _median(vet_scored),
        "taken_mean": _mean(taken_scored), "taken_median": _median(taken_scored),
        "n_veto_scored": len(vet_scored), "n_taken_scored": len(taken_scored),
        "veto_correct": sum(1 for f in vet_scored if f < 0),
    })
    res["hit_rate"] = (res["veto_correct"] / len(vet_scored)) if vet_scored else None
    res["difference"] = (None if res["veto_mean"] is None or res["taken_mean"] is None
                         else res["veto_mean"] - res["taken_mean"])
    return res


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
INDEX_HEADER = (
    "| AI book | Frozen twin | Role | Common window from | AI ret | Twin ret | "
    "**Spread** | AI max DD | Twin max DD | Param v | Applied | Rejected | "
    "Veto hit rate | Weeks | Evaluation |")
INDEX_RULE = "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"


def _index_row(p: dict, m: dict, changes: list[dict], ai: dict,
               veto: dict | None) -> str:
    applied = sum(1 for c in changes if c.get("status") == "applied")
    rejected = sum(1 for c in changes if c.get("status") == "rejected")
    ver = "·" if ai.get("agent_version") is None else f"v{ai['agent_version']}"
    hit = "—" if p["role"] != "gater" else (
        "·" if not veto or not veto.get("available") or veto.get("hit_rate") is None
        else f"{_rate(veto['hit_rate'])} ({veto['n_veto_scored']} scored)")
    wk = weeks_elapsed(ai.get("created"), m.get("common_end"))
    weeks = "·" if wk is None else f"{wk:.1f}/{HORIZON_WEEKS}"
    link = f"[{p['ai']}]({p['ai']}.md)"

    if m["status"] != "ok":
        return (f"| {link} | `{p['twin']}` | {p['role']} | **no data yet** — "
                f"{m.get('detail', m['status'])} | · | · | · | · | · | {ver} | "
                f"{applied} | {rejected} | {hit} | {weeks} | "
                f"{EVALUATION_DATE.isoformat()} |")
    return (f"| {link} | `{p['twin']}` | {p['role']} | "
            f"{m['common_start']} ({m['n_sessions']} sess) | "
            f"{_pct(m['ai_ret'])} | {_pct(m['twin_ret'])} | "
            f"**{_pct(m['spread'])}** | {_pct(m['ai_mdd'])} | "
            f"{_pct(m['twin_mdd'])} | {ver} | {applied} | {rejected} | {hit} | "
            f"{weeks} | {EVALUATION_DATE.isoformat()} |")


def _change_rows(changes: list[dict]) -> list[str]:
    lines = [
        "| Date | Status | Version | Diff | Rationale | Evidence | Reject reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in changes:
        diffs = c.get("changes") or []
        diff = " · ".join(
            f"`{_esc(d.get('param'))}` {_esc(d.get('from'))}→{_esc(d.get('to'))}"
            for d in diffs) or "_(no change proposed)_"
        ev = c.get("evidence") or []
        ev_txt = "<br>".join(f"- {_esc(e)}" for e in ev) if ev else "·"
        vfrom, vto = c.get("version_from"), c.get("version_to")
        ver = f"v{vfrom}" if vfrom == vto else f"v{vfrom}→v{vto}"
        status = ("**applied**" if c.get("status") == "applied"
                  else f"_{_esc(c.get('status'))}_")
        lines.append(
            f"| {_esc(c.get('date'))} | {status} | {ver} | {diff} | "
            f"{_esc(c.get('rationale')) or '·'} | {ev_txt} | "
            f"{_esc(c.get('reject_reason')) or '·'} |")
    return lines


def _spread_table(m: dict, ai_id: str, twin_id: str, n: int = 20) -> list[str]:
    tail = m["series"][-n:]
    lines = [
        f"| Session | {ai_id} equity | idx | {twin_id} equity | idx | "
        f"Cumulative spread |",
        "|---|---|---|---|---|---|",
    ]
    for s in tail:
        lines.append(
            f"| {s['date']} | {_money(s['ai'])} | {_idx(s['ai_idx'])} | "
            f"{_money(s['twin'])} | {_idx(s['twin_idx'])} | "
            f"**{_pct(s['spread'])}** |")
    return lines


def _veto_section(p: dict, veto: dict) -> list[str]:
    b = ["## Veto ledger and hit rate", ""]
    if not veto or not veto.get("available"):
        return b + ["_No `gate-<date>.json` decision file exists yet — this book "
                    "has made no recorded gating call, so there is nothing to "
                    "score._", ""]
    b += [
        f"_{veto['n_gate_files']} gate file(s) · {veto['n_vetoes']} veto(es) · "
        f"{veto['n_downscales']} downscale(s) · {veto['n_taken']} entry(ies) the "
        f"book took on the same sessions._",
        "",
        "**How a veto is scored.** A veto's counterfactual is only observable "
        "through the twin: the AI book never bought the name, so the only "
        "evidence of what the veto cost or saved is whether the FROZEN TWIN "
        "bought it on the next session, and what happened to it afterwards. "
        f"Where the twin bought, the name's +{FWD_SESSIONS}-session return is "
        "measured from the twin's fill price, and the veto counts as **correct** "
        "when that return is negative. Where the twin also skipped the name "
        "there is no counterfactual and the veto is excluded from the hit rate "
        "— it is not scored as a win. **A downscale is never counted in the hit "
        "rate**: it changes position size, not selection, so it cannot be right "
        "or wrong about a name. Names whose "
        f"+{FWD_SESSIONS}-session bar does not exist yet are shown as `pending` "
        "and are never extrapolated.",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Vetoes issued | {veto['n_vetoes']} |",
        f"| …that the twin actually bought (scoreable) | "
        f"{veto['n_vetoes_twin_bought']} |",
        f"| …with no twin entry (no counterfactual, excluded) | "
        f"{veto['n_vetoes_no_counterfactual']} |",
        f"| …resolved (+{FWD_SESSIONS} bar exists) | {veto['n_veto_scored']} |",
        f"| …pending | {veto['n_vetoes_pending']} |",
        f"| Vetoes correct (subsequent return negative) | {veto['veto_correct']} |",
        f"| **Veto hit rate** | **{_rate(veto['hit_rate'])}** |",
        f"| Mean +{FWD_SESSIONS}d return, vetoed-and-twin-bought | "
        f"{_pct(veto['veto_mean'])} |",
        f"| Median +{FWD_SESSIONS}d return, vetoed-and-twin-bought | "
        f"{_pct(veto['veto_median'])} |",
        f"| Entries taken (resolved / pending) | {veto['n_taken_scored']} / "
        f"{veto['n_taken_pending']} |",
        f"| Mean +{FWD_SESSIONS}d return, taken | {_pct(veto['taken_mean'])} |",
        f"| Median +{FWD_SESSIONS}d return, taken | {_pct(veto['taken_median'])} |",
        f"| **Difference (vetoed − taken)** | **{_pct(veto['difference'])}** |",
        "",
        "A gater that is selecting well shows a **negative** difference: the "
        "names it refused did worse than the names it let through. A positive "
        "difference means the gate is vetoing the wrong names.",
        "",
        "### Veto ledger", "",
        "| Gate date | Bites on | Ticker | Twin bought? | Twin fill | "
        f"+{FWD_SESSIONS}d | Verdict | Reason |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for v in veto["vetoes"]:
        if v["status"] == "resolved":
            verdict = "correct" if v["fwd"] < 0 else "wrong"
            fwd = _pct(v["fwd"])
        elif v["status"] == "pending":
            verdict = "`pending`"
            fwd = "`pending`"
        else:
            verdict = "_no counterfactual_"
            fwd = "·"
        fill = "·" if v["fill_px"] is None else f"${v['fill_px']:,.2f}"
        b.append(
            f"| {v['gate_date']} | {v['next_session'] or '·'} | {v['ticker']} | "
            f"{'yes' if v['twin_bought'] else 'no'} | {fill} | "
            f"{fwd} | {verdict} | {_esc(v.get('reason'))} |")
    b.append("")
    if veto["downscales"]:
        b += ["### Downscales (recorded, NOT in the hit rate)", "",
              "| Gate date | Bites on | Ticker | Scale | Reason |",
              "|---|---|---|---|---|"]
        for d in veto["downscales"]:
            b.append(f"| {d['gate_date']} | {d['next_session'] or '·'} | "
                     f"{d['ticker']} | {d.get('scale')} | "
                     f"{_esc(d.get('reason'))} |")
        b.append("")
    if veto["taken"]:
        b += [f"### Entries taken on gated sessions (+{FWD_SESSIONS}d)", "",
              f"| Session | Ticker | Fill | +{FWD_SESSIONS}d |",
              "|---|---|---|---|"]
        for t in veto["taken"]:
            b.append(f"| {t['next_session']} | {t['ticker']} | "
                     f"${t['fill_px']:,.2f} | "
                     f"{'`pending`' if t['status'] == 'pending' else _pct(t['fwd'])} |")
        b.append("")
    return b


# --------------------------------------------------------------------------- #
def write_reports(db_path: Path, out_dir: Path, agents_dir: Path) -> list[Path]:
    con = connect_ro(db_path)
    try:
        cal = sessions(con)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        out_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        rows, per_book = [], []

        for p in PAIRS:
            ai = load_book(con, p["ai"])
            twin = load_book(con, p["twin"])
            m = pair_metrics(ai, twin)
            changes = load_changes(agents_dir, p["ai"])
            gates = load_gates(agents_dir, p["ai"]) if p["role"] == "gater" else []
            veto = (veto_analysis(con, cal, p["ai"], p["twin"], gates)
                    if p["role"] == "gater" else None)
            rows.append(_index_row(p, m, changes, ai, veto))
            per_book.append((p, ai, twin, m, changes, veto))

        live = sum(1 for _, ai, *_ in per_book if ai["exists"])
        lines = [
            "# Agentic books — AI vs frozen twin",
            "",
            f"_{len(PAIRS)} paired book(s) · {live} of {len(PAIRS)} AI book(s) "
            f"exist in `portfolios` · generated {stamp}._",
            "",
            "Each row is one AI book and the frozen twin it is measured against. "
            "The twin runs the SAME algorithm with never-adjusted parameters; the "
            "AI book runs that algorithm plus an agent whose authority is bounded "
            "by a frozen charter. **The spread between them is the whole "
            "experiment** — everything else on this page is context.",
            "",
            "Spreads are computed on the common overlapping window only, because "
            "three of the twins are pre-existing books with an earlier inception "
            "than the AI books shadowing them. Both curves are rebased to 1.0 at "
            "the first session both books have an equity row for, and the window "
            "start is stated on every row.",
            "",
            DISCLOSURES,
            "",
            "## Scoreboard",
            "",
            INDEX_HEADER, INDEX_RULE,
        ]
        lines += rows
        lines += [
            "",
            f"_`Param v` is `portfolios.config → agent_version` (1 when the key is "
            f"absent). `Applied`/`Rejected` count rows in `changes.jsonl`. "
            f"`Weeks` counts from the AI book's own inception to the last shared "
            f"session, against the {HORIZON_WEEKS}-week horizon; the loop is "
            f"evaluated {EVALUATION_DATE.isoformat()}._",
            "",
            "## Kill criterion (pre-registered)",
            "",
            f"At **{EVALUATION_DATE.isoformat()}**, after {HORIZON_WEEKS} weeks, "
            "an AI book whose spread against its frozen twin is not positive "
            "loses its agent loop: the agent's authority to adjust is withdrawn "
            "and the book continues as the pure algorithm. The algorithmic book "
            "is NOT killed by this criterion — only the loop is. Nothing about "
            "the criterion, the bounds or the twin may be re-registered "
            "mid-stream; a changed charter starts a new record.",
            "",
        ]
        readme = out_dir / "README.md"
        readme.write_text("\n".join(lines) + "\n")
        written.append(readme)

        for p, ai, twin, m, changes, veto in per_book:
            ch = charter_path(agents_dir, p["ai"])
            lc = lessons_count(agents_dir, p["ai"])
            applied = sum(1 for c in changes if c.get("status") == "applied")
            rejected = sum(1 for c in changes if c.get("status") == "rejected")
            wk = weeks_elapsed(ai.get("created"), m.get("common_end"))
            b = [
                f"# {p['ai']} — vs frozen twin `{p['twin']}`",
                "",
                f"_role **{p['role']}** ({p['note']}) · param version "
                f"**{('v%d' % ai['agent_version']) if ai['exists'] else '·'}** · "
                f"{applied} applied / {rejected} rejected change(s) · "
                + (f"{lc} lesson(s)" if lc is not None else "no lessons file")
                + f" · generated {stamp}._",
                "",
                (f"Charter: `{_rel(ch)}` (frozen — bounds, objective and kill "
                 f"criterion are not re-registrable mid-stream)."
                 if ch else
                 "_No `charter.md` on disk for this book yet._"),
                "",
            ]
            if m["status"] != "ok":
                b += [f"> **No data yet — {m.get('detail', m['status'])}.** "
                      f"Nothing below is measurable until both this book and "
                      f"`{p['twin']}` have `sim_equity` rows on a shared session.",
                      ""]
            else:
                b += [
                    "## Spread vs the frozen twin",
                    "",
                    f"Common window **{m['common_start']} → {m['common_end']}** "
                    f"({m['n_sessions']} session(s)); both curves rebased to 1.0000 "
                    f"at {m['common_start']}. AI inception "
                    f"{ai.get('created')}, twin inception {twin.get('created')} — "
                    + ("identical, so the common window is the whole life of both "
                       "books."
                       if ai.get("created") == twin.get("created") else
                       "**different**, which is exactly why the raw total returns "
                       "of these two books are never subtracted from each other "
                       "here."),
                    "",
                    f"* AI return over the window: **{_pct(m['ai_ret'])}**",
                    f"* Twin return over the window: **{_pct(m['twin_ret'])}**",
                    f"* **Spread (AI − twin): {_pct(m['spread'])}**",
                    f"* Max drawdown over the same window — AI "
                    f"{_pct(m['ai_mdd'])}, twin {_pct(m['twin_mdd'])}",
                    f"* Elapsed: "
                    + (f"**{wk:.1f} / {HORIZON_WEEKS} weeks**" if wk is not None
                       else "·")
                    + f", evaluated {EVALUATION_DATE.isoformat()}",
                    "",
                    f"### Last {min(20, m['n_sessions'])} session(s)",
                    "",
                ]
                b += _spread_table(m, p["ai"], p["twin"])
                b.append("")

            b += ["## Change log", ""]
            if changes:
                b += [f"_{len(changes)} proposal(s) from `changes.jsonl` "
                      f"({applied} applied, {rejected} rejected). Append-only: "
                      f"rejected proposals are shown, not hidden._", ""]
                b += _change_rows(changes)
                b.append("")
            else:
                b += ["_No `changes.jsonl` yet — the agent has made no recorded "
                      "proposal for this book._", ""]

            if p["role"] == "gater":
                b += _veto_section(p, veto)
            else:
                b += ["## Gating", "",
                      "_Not applicable — this is a **tuner** book. It adjusts "
                      "parameters on a weekly cadence and never vetoes or "
                      "downscales an individual entry, so there is no veto "
                      "ledger and no hit rate to compute._", ""]

            b += [DISCLOSURES, ""]
            f = out_dir / f"{p['ai']}.md"
            f.write_text("\n".join(b) + "\n")
            written.append(f)

        print(f"[agentic-report] wrote {len(written)} file(s) to {out_dir} "
              f"({live}/{len(PAIRS)} AI book(s) live in the store)")
        return written
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Render the agentic AI-vs-frozen-twin reports.")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="DuckDB path (read-only)")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="output dir")
    ap.add_argument("--agents-dir", default=str(DEFAULT_AGENTS_DIR),
                    help="dir holding <book>/charter.md, changes.jsonl, gate-*.json")
    a = ap.parse_args()
    write_reports(Path(a.db), Path(a.out_dir), Path(a.agents_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
