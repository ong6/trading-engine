"""Bounded hourly/four-hour P9 quote and headline observations; never trades."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from engine.lib import db
from engine.lib.provenance import canonical_sha256
from engine.lib.resources import advisory_file_lock
from engine.lib.settings import DEFAULT_DB, REPO_ROOT

from . import agent_model_client, daily_opportunity_news
from .daily_opportunity_runner import _model_input, _validate_output
from .file_utils import read_bytes

REGISTRATION = REPO_ROOT / "server" / "agent-cadence-registration.json"
MAX_QUOTES = 5
LOCK_PATH = REPO_ROOT / ".hourly-opportunity.lock"


def _variants() -> dict[str, dict]:
    payload = json.loads(read_bytes(REGISTRATION, label="agent cadence registration"))
    return {item["id"]: item for item in payload["variants"]}


def observe(
    variant_id: str, *, database: Path = DEFAULT_DB, now: datetime | None = None,
    generate=agent_model_client.generate_opportunity_json, fetch_news=daily_opportunity_news._fetch,
) -> dict:
    variant = _variants().get(variant_id)
    if variant is None or variant["execution_authority"] != "none":
        raise ValueError("observation variant is invalid")
    observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    with advisory_file_lock(LOCK_PATH):
        con = db.connect(database, read_only=True, wait_s=0)
        try:
            market_date = db.latest_operational_market_date(con)
            if market_date is None:
                raise ValueError("no breadth-qualified market date")
            from engine.daily_opportunities import detect

            bundle = detect(con, market_date, limit=variant["candidate_limit"])
            tickers = [item["ticker"] for item in bundle["candidates"]]
        finally:
            con.close()
    try:
        import yfinance as yf

        raw = yf.download(tickers, period="2d", interval="5m", group_by="ticker",
                          auto_adjust=False, threads=True, progress=False, timeout=20)
    except Exception:
        raw = None
    quotes = []
    for ticker in tickers[:MAX_QUOTES]:
        try:
            frame = raw[ticker] if len(tickers) > 1 else raw
            closes = frame["Close"].dropna()
            volumes = frame["Volume"].dropna()
            if len(closes) < 2 or not len(volumes):
                continue
            last, prior = float(closes.iloc[-1]), float(closes.iloc[-2])
            if not all(math.isfinite(value) and value > 0 for value in (last, prior)):
                continue
            body = {"ticker": ticker, "observed_at": observed.isoformat(),
                    "last": last, "change_5m": last / prior - 1,
                    "last_volume": int(volumes.iloc[-1])}
            quotes.append({**body, "evidence_id": canonical_sha256(body)})
        except (KeyError, TypeError, ValueError):
            continue
    news = daily_opportunity_news.capture(["SPY", *tickers], now=observed, fetch=fetch_news)
    for candidate in bundle["candidates"]:
        quote = next((item for item in quotes if item["ticker"] == candidate["ticker"]), None)
        candidate["intraday_observation"] = quote
    model_input, allowed = _model_input(bundle, news, [])
    for ticker, values in allowed.items():
        quote = next((item for item in quotes if item["ticker"] == ticker), None)
        if quote is not None:
            values.add(quote["evidence_id"])
    model_input["task"] = variant["prompt_role"]
    model_input["variant_id"] = variant_id
    model_input["execution_authority"] = "none"
    model_input["allowed_evidence_ids"] = sorted(set().union(*allowed.values()) if allowed else set())
    response = generate(model_input)
    assessments = _validate_output(response.output, bundle, allowed, set())
    artifact = {
        "schema_version": 1, "variant_id": variant_id, "cadence": variant["cadence"],
        "prompt_role": variant["prompt_role"], "observed_at": observed.isoformat(),
        "market_date": market_date.isoformat(), "quotes": quotes,
        "news_status": news["status"], "headlines": news["observations"],
        "assessments": assessments, "model": response.model,
        "model_version": response.model_version, "response_id": response.response_id,
        "usage": response.usage,
        "execution_authority": "none",
    }
    artifact["observation_sha256"] = canonical_sha256(artifact)
    target = REPO_ROOT / "logs" / f"{variant_id}.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = target.read_text().splitlines() if target.exists() else []
    window = observed.strftime("%Y-%m-%dT%H") if variant["cadence"] == "hourly" else observed.strftime("%Y-%m-%dT%H")
    artifact["window"] = window
    if not any(json.loads(line).get("window") == window for line in existing):
        with target.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(artifact, sort_keys=True, separators=(",", ":")) + "\n")
    return {"status": "completed", "variant_id": variant_id,
            "quote_count": len(quotes), "headline_count": len(news["observations"]),
            "assessment_count": len(assessments),
            "execution_authority": "none", "artifact_sha256": hashlib.sha256(target.read_bytes()).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("variant_id", choices=("hourly_market_watch_v1", "four_hour_opportunity_review_v1"))
    args = parser.parse_args()
    print(json.dumps(observe(args.variant_id), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
