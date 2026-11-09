import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { instructions } from '../scripts/compatibility.mjs';

const data = JSON.parse(await readFile(new URL('../src/compatibility.json', import.meta.url), 'utf8'));
const candidate = model => Object.values(model.routes).every(route => route === 'automatic_supported');

test('all 48 carrier decisions have distinct progress and accurate route counts', async () => {
  const counts = {};
  for (const model of data.models) for (const state of Object.values(model.routes)) counts[state] = (counts[state] || 0) + 1;
  assert.deepEqual(counts, { automatic_supported: 48 });
  for (const prefix of ['', 'en/']) {
    const page = await readFile(new URL(`../dist/${prefix}index.html`, import.meta.url), 'utf8');
    assert.equal([...page.matchAll(/<tr data-variant=/g)].length, 16);
    for (const model of data.models) {
      const row = page.split(`<tr data-variant="${model.variant}">`)[1].split('</tr>')[0];
      for (const [operator, state] of Object.entries(model.routes)) assert.ok(row.includes(`data-operator="${operator}" data-route="${state}"`));
      const note = model.note[prefix ? 'en' : 'zh'].trim();
      if (note) assert.ok(row.includes(note), model.variant);
      assert.equal(row.includes(prefix ? '>Open<' : '>已开放<'), false);
    }
  }
});

test('each exact candidate has standalone bilingual instructions and a complete feedback form', async () => {
  assert.equal(data.models.filter(candidate).length, 16);
  for (const model of data.models.filter(candidate)) {
    for (const language of ['zh', 'en']) {
      const text = await readFile(new URL(`../dist/trials/${model.variant}.${language}.txt`, import.meta.url), 'utf8');
      assert.equal(text, instructions(model, language));
      for (const required of [model.variant, 'r43', '10.3.3.3216', 'Root', 'SSH', 'LTE', 'JSON', 'ZIP', 'IMSI', 'IMEI', 'ICCID']) assert.ok(text.includes(required));
      assert.match(text, /反馈表|FEEDBACK FORM/);
      assert.match(text, /停用并恢复|Disable and restore/);
      assert.match(text, /已送达|delivered/);
    }
  }
});
