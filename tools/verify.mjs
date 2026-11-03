// verify.mjs —— 用真实 Python 生成的 fixtures 逐条比对 core.js。
// 用法：node tools/verify.mjs
// 任何差异都会打印前若干条并返回退出码 1。

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = dirname(here);
const fixtures = join(here, 'fixtures');
const core = await import(new URL('../docs/js/core.js', import.meta.url).href);

const load = (name) => JSON.parse(readFileSync(join(fixtures, name), 'utf8'));
let failures = 0;
let checks = 0;
const reports = [];

function report(section, detail) {
  failures += 1;
  if (reports.length < 25) reports.push(`[${section}] ${detail}`);
}

function same(a, b) {
  if (typeof a === 'number' && typeof b === 'number') return Object.is(a, b);
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((item, i) => same(item, b[i]));
  }
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    const ka = Object.keys(a);
    const kb = Object.keys(b);
    return ka.length === kb.length && ka.every((k) => same(a[k], b[k]));
  }
  return a === b;
}

function expect(section, label, actual, expected) {
  checks += 1;
  if (!same(actual, expected)) {
    const hint =
      typeof actual === 'number' && typeof expected === 'number'
        ? `（差 ${(actual - expected).toExponential(3)}）`
        : '';
    report(section, `${label}\n    期望 ${JSON.stringify(expected)}\n    实际 ${JSON.stringify(actual)} ${hint}`);
  }
}

/**
 * 浮点相对容差比对。只用于权重数组：Python 的 `x ** 2` 走 libm pow，
 * 约 0.2% 的输入与正确舍入的 x*x 差 1 ulp（已实测），属平台差异、无法逐位复刻。
 * 相对误差 2e-16 不会改变任何一次抽样的结果（30 组抽取用例已逐条一致）。
 */
function expectClose(section, label, actual, expected, rtol = 1e-12) {
  checks += 1;
  if (!Array.isArray(actual) || !Array.isArray(expected) || actual.length !== expected.length) {
    report(section, `${label} 长度不一致：${actual?.length} vs ${expected?.length}`);
    return;
  }
  for (let i = 0; i < expected.length; i += 1) {
    const a = actual[i];
    const b = expected[i];
    if (Object.is(a, b)) continue;
    const scale = Math.max(Math.abs(a), Math.abs(b), Number.MIN_VALUE);
    if (Math.abs(a - b) / scale > rtol) {
      report(section, `${label}[${i}] 相差过大\n    期望 ${b}\n    实际 ${a}`);
      return;
    }
  }
}

const makeRand = (values) => {
  const calls = [];
  const fn = () => {
    const value = calls.length < values.length ? values[calls.length] : 0.5;
    calls.push(value);
    return value;
  };
  fn.calls = calls;
  return fn;
};

// ---------- 1. 舍入 ----------
const rounding = [
  [0.03125, 4, 0.0312],
  [2.5, 0, 2],
  [74.5, 0, 74],
  [1.25, 1, 1.2],
  [0.5, 0, 0],
  [1.5, 0, 2],
  [-2.5, 0, -2],
  [3.14159, 3, 3.142],
];
for (const [x, nd, want] of rounding) expect('舍入', `pyRound(${x}, ${nd})`, core.pyRound(x, nd), want);

// ---------- 2. apply_answer ----------
const answer = load('answer.json');
for (const [index, item] of answer.cases.entries()) {
  expect('apply_answer', `#${index} s=${item.s} e=${item.e} r=${item.r}`,
    core.applyAnswer(item.s, item.e, item.r), item.out);
}

// ---------- 3. proficiency ----------
const proficiency = load('proficiency.json');
for (const [index, item] of proficiency.cases.entries()) {
  expect('proficiency', `#${index} s=${item.s}`,
    core.proficiencyFromStability(item.s), item.out);
}

// ---------- 4. 调度与抽样 ----------
const words = JSON.parse(readFileSync(join(root, '_backup_before_web', 'words.json'), 'utf8'));
const schedule = load('schedule.json');
for (const [index, item] of schedule.cases.entries()) {
  const now = item.now;
  const due = core.dueWords(words, now);
  expect('调度', `case${index}.due`, due.map((w) => w.en), item.due);

  const { newPool, reviewPool } = core.splitPools(due);
  expect('调度', `case${index}.newPool`, newPool.map((w) => w.en), item.newPool);
  expect('调度', `case${index}.reviewPool`, reviewPool.map((w) => w.en), item.reviewPool);
  expectClose('调度', `case${index}.weights`, core.poolWeights(reviewPool, now), item.weights);
  expect('调度', `case${index}.nextDue`, core.nextDueSeconds(words, now), item.nextDue);
  expect('调度', `case${index}.allFinish`, core.allWordFinish(words), item.allFinish);

  for (const [pickIndex, pick] of item.picks.entries()) {
    const rand = makeRand(pick.u);
    const picked = core.pickRandomWord(words, now, rand);
    expect('抽样', `case${index}.pick${pickIndex}.en`,
      picked === null ? null : picked.en, pick.en);
    expect('抽样', `case${index}.pick${pickIndex}.随机次数`,
      rand.calls.length, pick.calls.length);
  }
}

// ---------- 5. 单词状态 ----------
const status = load('status.json');
for (const [index, item] of status.cases.entries()) {
  const word = words.find((w) => w.en === item.en);
  expect('状态', `#${index} ${item.en}.status`, core.wordStatus(word, item.now), item.status);
  expect('状态', `#${index} ${item.en}.nextText`, core.nextReviewText(word, item.now), item.nextText);
}

// ---------- 6. 释义分行 ----------
const definition = load('definition.json');
for (const [index, item] of definition.cases.entries()) {
  expect('释义', `#${index} ${JSON.stringify(item.text)}`,
    core.formatDefinition(item.text), item.lines);
}

// ---------- 7. 文案 ----------
const text = load('text.json');
for (const [index, item] of text.waits.entries()) {
  expect('文案', `formatWait#${index} s=${item.s}`, core.formatWait(item.s), item.out);
}
for (const item of text.greetings) {
  expect('文案', `greeting(${item.hour})`, core.greeting(item.hour), item.out);
}

// ---------- 8. 近 7 天统计 ----------
const weekly = load('weekly.json');
for (const [index, item] of weekly.cases.entries()) {
  for (const [anchor, expected] of Object.entries(item.expected)) {
    const [y, m, d] = anchor.split('-').map(Number);
    const today = new Date(y, m - 1, d, 12, 0, 0);
    const actual = core.weeklyCounts(item.rows, today).map((day) => [day.key, day.count]);
    expect('周统计', `case${index} @${anchor}`, actual, expected);
  }
}

// ---------- 9. 存档归一化 ----------
const normalize = load('normalize.json');
{
  const input = normalize.input.map((item) => ({ ...item }));
  core.normalizeWords(input);
  expect('归一化', '字段补齐结果', input, normalize.out);
}

// ---------- 10. 大规模模糊比对 ----------
const fuzz = load('fuzz.json');
for (const [index, item] of fuzz.cases.entries()) {
  const out = core.applyAnswer(item.s, item.e, item.r);
  expect('模糊', `#${index}.out s=${item.s} e=${item.e} r=${item.r}`, out, item.out);
  expect('模糊', `#${index}.proficiency`, core.proficiencyFromStability(out[0]), item.p);
}

// ---------- 汇总 ----------
const total = checks;
if (failures === 0) {
  console.log(`通过：${total} 项对比全部一致 ✓`);
  process.exit(0);
}
console.log(`失败：${failures} / ${total} 项不一致\n`);
for (const line of reports) console.log(line + '\n');
process.exit(1);
