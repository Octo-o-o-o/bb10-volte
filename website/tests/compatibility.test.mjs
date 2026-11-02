import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { instructions } from '../scripts/compatibility.mjs';

const data = JSON.parse(await readFile(new URL('../src/compatibility.json', import.meta.url), 'utf8'));
const candidate = model => Object.values(model.routes).some(route => ['manual_candidate', 'read_only_lifecycle_pending'].includes(route));

test('all 42 public carrier decisions have distinct progress and accurate route counts', async () => {
  const counts = {};
  for (const model of data.models) for (const state of Object.values(model.routes)) counts[state] = (counts[state] || 0) + 1;
  assert.deepEqual(counts, { manual_candidate: 13, blocked: 14, automatic_supported: 9, read_only_lifecycle_pending: 6 });
  for (const prefix of ['', 'en/']) {
    const page = await readFile(new URL(`../dist/${prefix}index.html`, import.meta.url), 'utf8');
    assert.equal([...page.matchAll(/<tr data-variant=/g)].length, 14);
    for (const model of data.models) {
      const row = page.split(`<tr data-variant="${model.variant}">`)[1].split('</tr>')[0];
      for (const [operator, state] of Object.entries(model.routes)) assert.ok(row.includes(`data-operator="${operator}" data-route="${state}"`));
      assert.ok(row.includes(model.progress[prefix ? 'en' : 'zh']));
    }
  }
});

test('each exact candidate has standalone bilingual instructions and a complete feedback form', async () => {
  assert.equal(data.models.filter(candidate).length, 8);
  for (const model of data.models.filter(candidate)) {
    for (const language of ['zh', 'en']) {
      const text = await readFile(new URL(`../dist/trials/${model.variant}.${language}.txt`, import.meta.url), 'utf8');
      assert.equal(text, instructions(model, language));
      for (const required of [model.variant, 'r15', '10.3.3.3216', 'Root', 'SSH', 'LTE', 'JSON', 'ZIP', 'IMSI', 'IMEI', 'ICCID']) assert.ok(text.includes(required));
      assert.match(text, /反馈表|FEEDBACK FORM/);
      if (model.family === 'passport') {
        assert.match(text, /不适用（只读）|N\/A \(read-only\)/);
        assert.doesNotMatch(text, /3\. 点击“安装并验证”|3\. Click Install and verify/);
      } else {
        assert.match(text, /单独点击“启动并验证”|click Start and verify separately/);
        assert.match(text, /至少 3 分钟|at least three minutes/);
        assert.match(text, /停用并恢复|Disable and restore/);
      }
    }
  }
});
