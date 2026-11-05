// core.js —— 算法与纯函数层。零 DOM、零存储，可被 Node 直接 import 做对照测试。
//
// 【重要】这里所有数值出口都走 pyRound()，全项目禁用 toFixed / Math.round 的取舍入用法。
// Python 的 round() 是「四舍六入五取偶」（银行家舍入），JS 的 Math.round 不是，
// 而熟练度的 .5 取整边界离真实数据最近只差 0.0067，用错了会静默算错分。

// ===== 熟练度参数 =====
export const STD_PRO = 90; // 达标熟练度（约 90 天记忆强度）
export const MAX_PRO = 100;
export const MIN_PRO = 50;

// ===== 记忆强度（调度）参数 =====
export const MIN_STABILITY_DAYS = 0.25;
export const INIT_STABILITY_DAYS = 0.5;
export const MAX_STABILITY_DAYS = 390.0;
export const STABILITY_FAIL_FACTOR = 0.4;
export const EASE_DEFAULT = 2.5;
export const EASE_MIN = 1.3;
export const EASE_MAX = 3.0;
export const EASE_UP = 0.1;
export const EASE_DOWN = 0.2;
export const MIGRATE_MAX_STABILITY_DAYS = 14.0;

// ===== 抽取策略参数 =====
export const NEW_POOL_RATIO = 0.5;
export const DUE_THRESHOLD = 1.0;
export const MIN_REVIEW_GAP_HOURS = 12;
export const LATENESS_CAP = 2.0;
export const LATENESS_POWER = 2;

/** Python round(x, nd) 的精确复刻：按 IEEE754 的真实二进制值展开成十进制，再五取偶。 */
export function pyRound(x, nd = 0) {
  if (!Number.isFinite(x) || x === 0) return x;
  // 超过 2^53 的数没有小数部分，Python 也原样返回
  if (Math.abs(x) >= 1e15) return x;

  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, x);
  const hi = view.getUint32(0);
  const lo = view.getUint32(4);
  const negative = (hi >>> 31) === 1;
  const exp = (hi >>> 20) & 0x7ff;
  let mant = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);

  let e;
  if (exp === 0) {
    e = -1074; // 次正规数
  } else {
    mant |= 1n << 52n;
    e = exp - 1075;
  }

  // x = mant * 2^e；e<0 时乘 5^-e 得到精确的 N / 10^F
  let N;
  let F;
  if (e >= 0) {
    N = mant << BigInt(e);
    F = 0;
  } else {
    F = -e;
    N = mant * 5n ** BigInt(F);
  }

  const k = F - nd;
  if (k > 0) {
    const p = 10n ** BigInt(k);
    let q = N / p;
    const r = N % p;
    const twice = r * 2n;
    if (twice > p || (twice === p && (q & 1n) === 1n)) q += 1n; // 恰好一半时取偶
    N = q;
  } else if (k < 0) {
    N *= 10n ** BigInt(-k);
  }

  const value = Number(N) / 10 ** nd;
  return negative ? -value : value;
}

/** 对应 Python 的 f"{x:.1f}"：先五取偶到该位，再定点输出。 */
export function fixed(x, digits) {
  return pyRound(x, digits).toFixed(digits);
}

// ===== 记忆强度调度 =====

/** 根据答对/答错更新记忆强度与增长系数。 */
export function applyAnswer(stability, ease, remembered) {
  const s0 = Number(stability) || 0;
  const e0 = Number.isFinite(Number(ease)) ? Number(ease) : EASE_DEFAULT;
  let s;
  let e;
  if (remembered) {
    s = s0 > 0 ? s0 * e0 : INIT_STABILITY_DAYS;
    e = Math.min(EASE_MAX, e0 + EASE_UP);
  } else {
    s = Math.max(MIN_STABILITY_DAYS, s0 * STABILITY_FAIL_FACTOR);
    e = Math.max(EASE_MIN, e0 - EASE_DOWN);
  }
  return [pyRound(Math.min(MAX_STABILITY_DAYS, s), 4), pyRound(e, 4)];
}

/** 记忆强度（天）→ 50~100 的熟练度，对数映射：0.25 天=50，90 天=90，390 天=100。 */
export function proficiencyFromStability(stability) {
  if (!(stability > 0)) return MIN_PRO;
  const ratio =
    Math.log(stability / MIN_STABILITY_DAYS) /
    Math.log(MAX_STABILITY_DAYS / MIN_STABILITY_DAYS);
  const clamped = Math.min(1.0, Math.max(0.0, ratio));
  return Math.trunc(pyRound(MIN_PRO + (MAX_PRO - MIN_PRO) * clamped, 0));
}

/** 逾期倍数：距上次复习时间 ÷ 记忆强度。1 表示刚好到期。未复习的新词按上限处理。 */
export function overdueRatio(word, now) {
  const stability = word.stability ?? 0;
  const last = word.last_review ?? 0;
  if (stability <= 0 || !last) return LATENESS_CAP;
  return Math.max(0.0, (now - last) / (stability * 86400));
}

/** 筛出本次可抽取的词（未达标 + 过了 12 小时间隔 + 已到期），保持原数组顺序。 */
export function dueWords(words, now = Date.now() / 1000) {
  const minGap = MIN_REVIEW_GAP_HOURS * 3600;
  const result = [];
  for (const word of words) {
    if ((word.proficiency ?? 0) >= STD_PRO) continue;
    const last = word.last_review ?? 0;
    if (last && now - last < minGap) continue;
    if (overdueRatio(word, now) >= DUE_THRESHOLD) result.push(word);
  }
  return result;
}

export function splitPools(due) {
  const newPool = due.filter((word) => (word.stability ?? 0) <= 0);
  const reviewPool = due.filter((word) => (word.stability ?? 0) > 0);
  return { newPool, reviewPool };
}

/** 复习池权重 = min(逾期倍数, 上限)²，越拖越优先；到上限后权重相同保证公平轮换。 */
export function poolWeights(pool, now) {
  return pool.map((word) => {
    const value = Math.max(
      0.01,
      Math.min(overdueRatio(word, now), LATENESS_CAP),
    );
    return value * value; // 与 Python 的 `** 2` 等价（CPython 对指数 2 就是 v*v）
  });
}

/** 等价 bisect(cumWeights, u*total, 0, n-1)：末元素不参与比较，返回下标。 */
export function weightedIndex(weights, u) {
  const n = weights.length;
  if (n === 0) return -1;
  if (n === 1) return 0;
  const cum = new Array(n);
  let acc = 0;
  for (let i = 0; i < n; i += 1) {
    acc += weights[i]; // 顺序累加，不能改成并行/reduce，累加顺序影响末位
    cum[i] = acc;
  }
  const target = u * (cum[n - 1] + 0.0);
  let lo = 0;
  let hi = n - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (target < cum[mid]) hi = mid;
    else lo = mid + 1;
  }
  return lo;
}

/**
 * 抽取一个待复习单词。没有到期词返回 null。
 *
 * 【求值次序必须与 Python 一致】调用方可能传入确定性随机源做对照测试：
 * 1) newPool 非空且 reviewPool 非空时才消耗一次随机数（短路求值）；
 * 2) 权重数组按 due 的原顺序生成；
 * 3) 最后再消耗一次随机数用于加权抽样。
 * 任何「优化」都会让随机数消耗次序错位。
 */
export function pickRandomWord(words, now = Date.now() / 1000, rand = Math.random) {
  const due = dueWords(words, now);
  if (due.length === 0) return null;

  const { newPool, reviewPool } = splitPools(due);
  let pool;
  let weights;
  if (newPool.length > 0 && (reviewPool.length === 0 || rand() < NEW_POOL_RATIO)) {
    pool = newPool;
    weights = newPool.map(() => 1.0);
  } else {
    pool = reviewPool;
    weights = poolWeights(reviewPool, now);
  }
  return pool[weightedIndex(weights, rand())];
}

/** 最近一个未达标词的到期等待秒数；没有未达标词返回 null。 */
export function nextDueSeconds(words, now = Date.now() / 1000) {
  let best = null;
  for (const word of words) {
    if ((word.proficiency ?? 0) >= STD_PRO) continue;
    const stability = word.stability ?? 0;
    const last = word.last_review ?? 0;
    if (stability <= 0 || !last) return 0;
    const nextDue = last + Math.max(stability * 86400, MIN_REVIEW_GAP_HOURS * 3600);
    const wait = nextDue - now;
    if (best === null || wait < best) best = wait;
  }
  if (best === null) return null;
  return Math.max(0, best);
}

export function allWordFinish(words) {
  return words.every((word) => (word.proficiency ?? 0) >= STD_PRO);
}

export function dueCount(words, now = Date.now() / 1000) {
  return dueWords(words, now).length;
}

// ===== 展示层文案 =====

export function formatWait(seconds) {
  if (seconds === null || seconds === undefined) return '暂无安排';
  const value = Math.max(0, seconds);
  if (value < 60) return '不到 1 分钟';
  if (value < 3600) return `${Math.trunc(value / 60)} 分钟`;
  if (value < 86400) return `${fixed(value / 3600, 1)} 小时`;
  return `${fixed(value / 86400, 1)} 天`;
}

export function greeting(hour = new Date().getHours()) {
  if (hour < 6) return '夜深了';
  if (hour < 12) return '上午好';
  if (hour < 18) return '下午好';
  return '晚上好';
}

export function wordStatus(word, now = Date.now() / 1000) {
  const proficiency = word.proficiency ?? 0;
  if (proficiency >= 101) return '已掌握';
  if (proficiency >= STD_PRO) return '已达标';
  if ((word.stability ?? 0) <= 0) return '新词';
  if (overdueRatio(word, now) >= DUE_THRESHOLD) return '待复习';
  return '已排期';
}

export function nextReviewText(word, now = Date.now() / 1000) {
  const proficiency = word.proficiency ?? 0;
  if (proficiency >= 101) return '不再复习';
  if (proficiency >= STD_PRO) return '已完成';
  const stability = word.stability ?? 0;
  const last = word.last_review ?? 0;
  if (stability <= 0 || !last) return '等待首次学习';
  const dueTime = last + Math.max(stability * 86400, MIN_REVIEW_GAP_HOURS * 3600);
  const seconds = dueTime - now;
  if (seconds <= 0) return '已到期';
  if (seconds < 86400) return `${fixed(seconds / 3600, 1)} 小时后`;
  return `${fixed(seconds / 86400, 1)} 天后`;
}

const POS = '(?:n|v|vt|vi|a|adj|ad|adv|prep|conj|pron|num|art|int|aux|abbr|pl)';
// 用 (^|[^A-Za-z]) 前导捕获组代替 Python 的后行断言 —— 后行断言在 iOS Safari 16.4 以下
// 会让整个模块解析失败，页面直接白屏。
const POS_MARKER = new RegExp(`(^|[^A-Za-z])(${POS}\\.)`, 'gi');
const POS_PREFIX = new RegExp(`^(${POS}\\.)\\s+`, 'i');

const stripChars = (text) =>
  text.replace(/^[ /；;，,]+/, '').replace(/[ /；;，,]+$/, '');

const keepPosWithMeaning = (part) => part.replace(POS_PREFIX, '$1\u00A0');

/** 把释义按词性拆成多行，返回行数组。 */
export function formatDefinition(text) {
  const source = String(text ?? '').trim();
  const marks = [];
  POS_MARKER.lastIndex = 0;
  let match = POS_MARKER.exec(source);
  while (match) {
    marks.push(match.index + match[1].length);
    POS_MARKER.lastIndex = match.index + match[1].length + 1;
    match = POS_MARKER.exec(source);
  }
  if (marks.length <= 1) return [keepPosWithMeaning(source)];

  const parts = [];
  const head = stripChars(source.slice(0, marks[0]));
  if (head) parts.push(head);
  marks.forEach((start, index) => {
    const end = index + 1 < marks.length ? marks[index + 1] : source.length;
    const part = stripChars(source.slice(start, end));
    if (part) parts.push(keepPosWithMeaning(part));
  });
  return parts;
}

// ===== 时间与格式化 =====

const pad2 = (value) => String(value).padStart(2, '0');

/** 本地时间 'YYYY-MM-DD HH:MM:SS'（不能用 toISOString，那是 UTC，会差 8 小时）。 */
export function formatTimestamp(date = new Date()) {
  return (
    `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} ` +
    `${pad2(date.getHours())}:${pad2(date.getMinutes())}:${pad2(date.getSeconds())}`
  );
}

export function dateKey(date = new Date()) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

/** 近 7 天每天复习次数（含今天），返回 [{ date: 'MM/DD', key, count }]。 */
export function weeklyCounts(rows, today = new Date()) {
  const base = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const days = [];
  for (let offset = 6; offset >= 0; offset -= 1) {
    const day = new Date(base.getTime() - offset * 86400000);
    days.push({ key: dateKey(day), label: `${pad2(day.getMonth() + 1)}/${pad2(day.getDate())}` });
  }
  const keys = new Set(days.map((day) => day.key));
  const counts = new Map();
  for (const row of rows) {
    if (!row || !row[0]) continue;
    const key = String(row[0]).slice(0, 10);
    if (keys.has(key)) counts.set(key, (counts.get(key) || 0) + 1);
  }
  return days.map((day) => ({ ...day, count: counts.get(day.key) || 0 }));
}

// ===== 存档归一化与导入 =====

/** 补齐缺失字段、清理废弃字段。幂等；返回是否发生了改动。 */
export function normalizeWords(words) {
  let changed = false;
  let needsMigration = false;
  let needsBackfill = false;
  for (const word of words) {
    if (!('first_review' in word)) {
      word.first_review = word.last_review ?? 0;
      changed = true;
    }
    if ('last_reduce' in word) {
      delete word.last_reduce;
      changed = true;
    }
    if ('review_count' in word) {
      delete word.review_count;
      changed = true;
    }
    if (!('fail_count' in word) || !('success_count' in word)) {
      if (!('fail_count' in word)) word.fail_count = 0;
      if (!('success_count' in word)) word.success_count = 0;
      needsBackfill = true;
      changed = true;
    }
    if (!('stability' in word) || !('ease' in word)) {
      if (!('stability' in word)) word.stability = 0.0;
      if (!('ease' in word)) word.ease = EASE_DEFAULT;
      needsMigration = true;
      changed = true;
    }
  }
  return { changed, needsMigration, needsBackfill };
}

/** 旧档迁移：按历史对错序列回放，得到记忆强度；上限 14 天。 */
export function replayResults(results) {
  let stability = 0.0;
  let ease = EASE_DEFAULT;
  for (const remembered of results) {
    [stability, ease] = applyAnswer(stability, ease, remembered);
  }
  return [Math.min(stability, MIGRATE_MAX_STABILITY_DAYS), ease];
}

export function estimateStability(word) {
  const successes = word.success_count ?? 0;
  const fails = word.fail_count ?? 0;
  const ease = Math.max(
    EASE_MIN,
    Math.min(EASE_MAX, EASE_DEFAULT + EASE_UP * successes - EASE_DOWN * fails),
  );
  if (successes === 0) return [0.0, ease];
  const logStability =
    successes * Math.log(ease) + fails * Math.log(STABILITY_FAIL_FACTOR);
  const stability = Math.exp(Math.min(logStability, 10.0));
  return [Math.min(stability, MIGRATE_MAX_STABILITY_DAYS), ease];
}

/** 从复习记录里取出每个词的对错序列（旧档迁移用）。 */
export function historySequences(rows) {
  const sequences = new Map();
  for (const row of rows) {
    if (!row || row.length < 6) continue;
    const result = String(row[5]).trim();
    if (result.startsWith('marked_remembered')) continue;
    const key = String(row[1]).trim();
    if (!sequences.has(key)) sequences.set(key, []);
    if (result.startsWith('forgotten')) sequences.get(key).push(false);
    else if (result.startsWith('remembered')) sequences.get(key).push(true);
  }
  return sequences;
}

/** 从复习记录回填历史对错次数。判断用的是精确相等，与桌面版保持一致。 */
export function backfillCounts(words, rows) {
  const index = new Map(words.map((word) => [word.en, word]));
  let filled = 0;
  for (const row of rows) {
    if (!row || row.length < 6) continue;
    const word = index.get(row[1]);
    if (!word) continue;
    if (row[5] === 'forgotten') word.fail_count += 1;
    else word.success_count += 1;
    filled += 1;
  }
  return filled;
}

/** 解析 "英文, 中文" 词表文本，返回新增数量（就地修改 words）。 */
export function importWords(text, words) {
  const exists = new Set(words.map((word) => word.en));
  let added = 0;
  for (const raw of String(text).split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || !line.includes(',')) continue;
    const cut = line.indexOf(','); // 只按第一个逗号切，释义里可以再有逗号
    const en = line.slice(0, cut).trim();
    const cn = line.slice(cut + 1).trim();
    if (!en || exists.has(en)) continue;
    words.push({
      en,
      cn,
      proficiency: MIN_PRO,
      stability: 0.0,
      ease: EASE_DEFAULT,
      first_review: 0,
      last_review: 0,
      fail_count: 0,
      success_count: 0,
    });
    exists.add(en);
    added += 1;
  }
  return added;
}

/** RFC4180 解析：支持引号包裹、字段内逗号与换行、CRLF。脏行原样保留。 */
export function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = '';
  let quoted = false;
  let index = 0;
  const source = String(text).replace(/^\uFEFF/, '');
  while (index < source.length) {
    const ch = source[index];
    if (quoted) {
      if (ch === '"') {
        if (source[index + 1] === '"') {
          field += '"';
          index += 2;
          continue;
        }
        quoted = false;
        index += 1;
        continue;
      }
      field += ch;
      index += 1;
      continue;
    }
    if (ch === '"') {
      quoted = true;
      index += 1;
      continue;
    }
    if (ch === ',') {
      row.push(field);
      field = '';
      index += 1;
      continue;
    }
    if (ch === '\r') {
      index += 1;
      continue;
    }
    if (ch === '\n') {
      row.push(field);
      rows.push(row);
      row = [];
      field = '';
      index += 1;
      continue;
    }
    field += ch;
    index += 1;
  }
  if (field !== '' || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

const csvCell = (value) => {
  const text = value === null || value === undefined ? '' : String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
};

/** 生成与桌面版一致的记录行（CRLF、六列）。 */
export function csvLine(cells) {
  return `${cells.map(csvCell).join(',')}\r\n`;
}

export const RECORD_HEADER = '复习时间,英文,中文,初始熟练度,最终熟练度,结果';

export const FIELD_ORDER = [
  'en',
  'cn',
  'proficiency',
  'stability',
  'ease',
  'first_review',
  'last_review',
  'fail_count',
  'success_count',
];

/** 按固定字段顺序序列化，保证导出的 words.json 能被桌面版直接读取。 */
export function serializeWords(words) {
  const ordered = words.map((word) => {
    const out = {};
    for (const key of FIELD_ORDER) out[key] = word[key];
    return out;
  });
  return JSON.stringify(ordered, null, 2);
}
