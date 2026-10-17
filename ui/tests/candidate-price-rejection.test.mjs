import assert from "node:assert/strict";
import test from "node:test";
import { isInadmissiblePriceData } from "../app/lib/market-contracts.js";

const rejection = () => ({ detail: {
  code: "inadmissible_price_data", ticker: "VLO", bars: [{
    date: "2026-10-15", open: 456.5, high: 456.28, low: 437.02, close: 444.06,
    reason: "public candidate OHLC geometry is invalid",
  }],
} });

test("candidate price rejection admits dated evidence bound to the requested ticker", () => {
  assert.equal(isInadmissiblePriceData(rejection(), "VLO"), true);
  const zero = rejection();
  zero.detail.ticker = "WBD";
  zero.detail.bars[0].open = 0;
  zero.detail.bars[0].reason = "public candidate open is invalid";
  assert.equal(isInadmissiblePriceData(zero, "WBD"), true);
  zero.detail.bars[0].open = null;
  assert.equal(isInadmissiblePriceData(zero, "WBD"), true);
});

test("malformed price rejection cannot be rendered as admitted evidence", () => {
  for (const change of [
    d => { d.detail.ticker = "SPY"; },
    d => { d.detail.code = "other"; },
    d => { d.detail.bars = []; },
    d => { d.detail.bars[0].date = "bad"; },
    d => { d.detail.bars[0].open = "456.5"; },
    d => { d.detail.bars[0].reason = "arbitrary"; },
    d => { d.detail.bars.push({ ...d.detail.bars[0] }); },
    d => { d.detail.bars[0].volume = 100; },
    d => { d.detail.extra = true; },
  ]) {
    const value = rejection(); change(value);
    assert.equal(isInadmissiblePriceData(value, "VLO"), false);
  }
});
