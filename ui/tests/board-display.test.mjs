import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import vm from 'node:vm';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import babel from 'next/dist/compiled/babel/bundle.js';
import * as format from '../app/lib/format.js';
import { isRetainedBarQuality } from '../app/lib/market-contracts.js';

const { core, presetReact, pluginTransformModulesCommonjs } = babel;
function component(name) {
  const source = fs.readFileSync(new URL(`../app/components/${name}.js`, import.meta.url), 'utf8');
  const code = core().transformSync(source, { babelrc: false, configFile: false,
    presets: [[presetReact(), { runtime: 'classic' }]], plugins: [pluginTransformModulesCommonjs()] }).code;
  const exports = {};
  vm.runInNewContext(code, { exports, React, require: (path) => {
    if (path === '../lib/format') return format;
    if (path === './StateNotice') return { default: () => null };
    throw new Error(path);
  } });
  return exports.default;
}
const render = (name, props) => renderToStaticMarkup(React.createElement(component(name), props));

test('prospective cards keep statistical eligibility while early paper kill is actionable', () => {
  const res = { ok: true, data: { forward_review: { status: 'ACCUMULATING', shared_sessions: 30,
    minimum_shared_sessions: 200, eligible_after: '2027-07-16' }, xs_forward_review: {
    status: 'ACCUMULATING', paired_complete_months: 0, minimum_paired_months: 48,
    signal_date: '2026-09-30', eligible_after: '2031-10-01' } } };
  const accumulating = render('DashboardProspectiveEvidence', { res });
  assert.match(accumulating, /0 \/ 48/);
  assert.match(accumulating, /statistical eligibility 2031-10-01/);
  assert.match(accumulating, /Early paper review\/kill can precede statistical eligibility/);
  assert.doesNotMatch(accumulating, /no verdict before|actionable now/);
  res.data.xs_forward_review.status = 'REVIEW-KILL';
  const killed = render('DashboardProspectiveEvidence', { res });
  assert.match(killed, /0 \/ 48/);
  assert.match(killed, /2031-10-01/);
  assert.match(killed, /Early paper review\/kill is actionable now/);
  const sparse = render('DashboardProspectiveEvidence', { res: { ok: true, data: {
    forward_review: { status: 'INVALID' }, xs_forward_review: { status: 'INVALID' } } } });
  assert.doesNotMatch(sparse, /0 \/48|2031|actionable now/);
});

test('template lists exactly eight scored criteria and separates unscored context', () => {
  const screen = { passes_template: true, template_score: 8, rs_rank: 90,
    dist_50d: .1, off_52w_low: .5, off_52w_high: -.1, base_tight: false, vol_dryup: false };
  const html = render('CandidateTemplateChecks', { screen });
  const scored = html.split('<div data-scored-criteria="true">')[1].split('</div><p')[0];
  assert.equal((scored.match(/border-bottom/g) || []).length, 8);
  assert.equal((scored.match(/Not recorded/g) || []).length, 4);
  assert.doesNotMatch(scored, /Base tight|Volume dry-up/);
  assert.match(html, /Passes full template · 8\/8/);
  assert.match(html, /Supplemental context · unscored/);
  assert.match(html, /Base tight: false/);
  const failed = render('CandidateTemplateChecks', { screen: { ...screen,
    passes_template: false, template_score: 7, dist_50d: 0 } });
  assert.match(failed, /Does not pass full template · 7\/8/);
  assert.match(failed, /class="neg"[^>]*>✗<\/span>Close &gt; SMA50/);
});

test('retained-bar warning is measured, dated, and absent on valid names', () => {
  const quality = { as_of: '2026-10-16', retained_count: 250, invalid_count: 1,
    latest_invalid_date: '2026-10-16', reason: 'public candidate OHLC geometry is invalid' };
  assert.equal(isRetainedBarQuality(quality), true);
  assert.match(render('RetainedBarWarning', { quality }), /1\/250 invalid bars/);
  assert.match(render('RetainedBarWarning', { quality }), /Latest 2026-10-16 · invalid OHLC geometry/);
  assert.equal(render('RetainedBarWarning', { quality: { ...quality, invalid_count: 0 } }), '');
  for (const change of [{ invalid_count: 251 }, { retained_count: 251 }, { reason: '' },
    { latest_invalid_date: '2026-10-17' }, { as_of: null }, { reason: 'bad\nreason' }]) {
    assert.equal(isRetainedBarQuality({ ...quality, ...change }), false);
  }
  assert.equal(isRetainedBarQuality({ as_of: null, retained_count: 0, invalid_count: 0,
    latest_invalid_date: null, reason: null }), true);
});
