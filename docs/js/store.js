// store.js —— 存档层：localStorage 放进度，IndexedDB 放明细。
//
// 为什么分开：1.2 万行复习明细约 93 万字符，塞进 localStorage 会和词库抢 5MB 配额，
// 一旦写入超限，连「进度」都会一起写失败 —— 那是最不能接受的失效方式。

import * as core from './core.js';

const LS = {
  words: 'wb.words.v1',
  agg: 'wb.agg.v1',
  session: 'wb.session.v1',
  pending: 'wb.pending.v1',
  corrupt: 'wb.words.v1.corrupt',
};

const DB_NAME = 'wordsbook';
const DB_VERSION = 1;
const STORE_RECORDS = 'records';
const STORE_KV = 'kv';

export class StorageWriteError extends Error {}

/** 内存状态：词库是唯一权威副本，改动后立刻落盘。 */
export const state = {
  words: [],
  agg: emptyAgg(),
  statsText: '',
  lastError: null,
};

function emptyAgg() {
  return {
    totalReviews: 0,
    totalRemembered: 0,
    totalForgotten: 0,
    daily: {},
    lastExportAt: 0,
    importedAt: 0,
  };
}

// ---------- localStorage 基础读写 ----------

function lsGet(key) {
  try {
    return localStorage.getItem(key);
  } catch (error) {
    state.lastError = error;
    return null;
  }
}

function lsSet(key, value) {
  try {
    localStorage.setItem(key, value);
    return true;
  } catch (error) {
    // 最典型的是 QuotaExceededError：必须让调用方知道，绝不能静默丢进度
    state.lastError = error;
    throw new StorageWriteError(error?.name || '存储写入失败');
  }
}

function lsRemove(key) {
  try {
    localStorage.removeItem(key);
  } catch (error) {
    state.lastError = error;
  }
}

// ---------- IndexedDB ----------

let dbPromise = null;

function openDb() {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    if (!('indexedDB' in window)) {
      reject(new Error('当前浏览器不支持 IndexedDB'));
      return;
    }
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_RECORDS)) {
        db.createObjectStore(STORE_RECORDS, { autoIncrement: true });
      }
      if (!db.objectStoreNames.contains(STORE_KV)) {
        db.createObjectStore(STORE_KV);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  }).catch((error) => {
    state.lastError = error;
    dbPromise = null;
    throw error;
  });
  return dbPromise;
}

async function idbAdd(storeName, value) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, 'readwrite');
    tx.objectStore(storeName).add(value);
    tx.oncomplete = () => resolve(true);
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

async function idbPutAll(storeName, values, keyOf) {
  if (!values.length) return;
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, 'readwrite');
    const store = tx.objectStore(storeName);
    for (const value of values) {
      if (keyOf) store.put(value, keyOf(value));
      else store.add(value);
    }
    tx.oncomplete = () => resolve(true);
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

async function idbAll(storeName) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, 'readonly');
    const request = tx.objectStore(storeName).getAll();
    request.onsuccess = () => resolve(request.result || []);
    request.onerror = () => reject(request.error);
  });
}

async function idbCount(storeName) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, 'readonly');
    const request = tx.objectStore(storeName).count();
    request.onsuccess = () => resolve(request.result || 0);
    request.onerror = () => reject(request.error);
  });
}

async function idbClear(storeName) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, 'readwrite');
    tx.objectStore(storeName).clear();
    tx.oncomplete = () => resolve(true);
    tx.onerror = () => reject(tx.error);
  });
}

async function kvSet(key, value) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_KV, 'readwrite');
    tx.objectStore(STORE_KV).put(value, key);
    tx.oncomplete = () => resolve(true);
    tx.onerror = () => reject(tx.error);
  });
}

async function kvGet(key) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_KV, 'readonly');
    const request = tx.objectStore(STORE_KV).get(key);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

// ---------- 词库 ----------

/** 读取存档。解析失败时把原文挪到备份键，绝不用空数组覆盖。 */
export function loadWords() {
  const raw = lsGet(LS.words);
  if (!raw) {
    state.words = [];
    return { ok: true, empty: true };
  }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (error) {
    lsSet(LS.corrupt, raw);
    lsRemove(LS.words);
    state.words = [];
    state.lastError = error;
    return { ok: false, corrupt: true };
  }
  if (!Array.isArray(parsed)) {
    lsSet(LS.corrupt, raw);
    lsRemove(LS.words);
    state.words = [];
    return { ok: false, corrupt: true };
  }
  const words = parsed.filter((word) => word && typeof word.en === 'string');
  core.normalizeWords(words);
  state.words = words;
  return { ok: true, count: words.length };
}

export function saveWords() {
  const payload = JSON.stringify(state.words);
  lsSet(LS.words, payload); // 失败会抛 StorageWriteError，由调用方提示用户
}

export function clearWords() {
  lsRemove(LS.words);
  state.words = [];
}

// ---------- 统计聚合 ----------

export function loadAgg() {
  const raw = lsGet(LS.agg);
  let parsed = null;
  try {
    parsed = raw ? JSON.parse(raw) : null;
  } catch {
    parsed = null;
  }
  state.agg = { ...emptyAgg(), ...(parsed || {}) };
  if (!state.agg.daily || typeof state.agg.daily !== 'object') state.agg.daily = {};
  return state.agg;
}

export function saveAgg() {
  try {
    lsSet(LS.agg, JSON.stringify(state.agg));
  } catch {
    // 聚合统计丢了可以重建，不阻断答题
  }
}

export function bumpAgg(result, timeText) {
  const agg = state.agg;
  agg.totalReviews += 1;
  if (result === 'forgotten') agg.totalForgotten += 1;
  else agg.totalRemembered += 1;
  const key = String(timeText).slice(0, 10);
  agg.daily[key] = (agg.daily[key] || 0) + 1;
  saveAgg();
}

export function rebuildAggFromRecords(rows) {
  const agg = emptyAgg();
  for (const row of rows) {
    if (!row || !row[0]) continue;
    agg.totalReviews += 1;
    if (row[5] === 'forgotten') agg.totalForgotten += 1;
    else agg.totalRemembered += 1;
    const key = String(row[0]).slice(0, 10);
    agg.daily[key] = (agg.daily[key] || 0) + 1;
  }
  agg.importedAt = Date.now();
  state.agg = { ...state.agg, ...agg, lastExportAt: state.agg.lastExportAt };
  saveAgg();
  return state.agg;
}

// ---------- 复习明细 ----------

export async function addRecord(row) {
  try {
    await idbAdd(STORE_RECORDS, row);
    return true;
  } catch (error) {
    // 明细写失败不该打断答题：进待补队列，下次启动重放
    state.lastError = error;
    const queue = loadPending();
    queue.push(row);
    lsSet(LS.pending, JSON.stringify(queue.slice(-50)));
    return false;
  }
}

export function loadPending() {
  try {
    return JSON.parse(lsGet(LS.pending) || '[]');
  } catch {
    return [];
  }
}

export async function flushPending() {
  const queue = loadPending();
  if (!queue.length) return 0;
  const rest = [];
  for (const row of queue) {
    try {
      await idbAdd(STORE_RECORDS, row);
    } catch {
      rest.push(row);
    }
  }
  if (rest.length) lsSet(LS.pending, JSON.stringify(rest));
  else lsRemove(LS.pending);
  return queue.length - rest.length;
}

export async function readRecords() {
  try {
    return await idbAll(STORE_RECORDS);
  } catch {
    return [];
  }
}

export async function recordCount() {
  try {
    return await idbCount(STORE_RECORDS);
  } catch {
    return 0;
  }
}

export async function replaceRecords(rows) {
  await idbClear(STORE_RECORDS);
  await idbPutAll(STORE_RECORDS, rows);
}

// ---------- 统计文本 ----------

export async function loadStatsText() {
  try {
    state.statsText = (await kvGet('stats')) || '';
  } catch {
    state.statsText = '';
  }
  return state.statsText;
}

export async function appendSessionBlock(block) {
  state.statsText = `${state.statsText}${block}`;
  try {
    await kvSet('stats', state.statsText);
  } catch (error) {
    state.lastError = error;
  }
}

/** 与桌面版 statistic_data() 完全一致的文本块。 */
export function buildSessionBlock(startTime, endTime, reviewCounts, rememberCounts, reviewWords, newWords) {
  const start = new Date(startTime * 1000);
  const total = Math.max(0, Math.round(endTime - startTime));
  const hours = Math.trunc(total / 3600);
  const minutes = Math.trunc((total % 3600) / 60);
  const seconds = Math.trunc(total % 60);
  const accuracy = reviewCounts ? core.fixed((rememberCounts / reviewCounts) * 100, 2) : '0.00';
  return (
    `\n复习时间：${core.formatTimestamp(start)}\n` +
    `用时：${hours}:${minutes}:${seconds}\n` +
    `复习单词次数：${reviewCounts}\n` +
    `记住单词次数：${rememberCounts}\n` +
    `复习单词数：${reviewWords}\n` +
    `新单词数：${newWords}\n` +
    `正确率：${accuracy}%\n`
  );
}

// ---------- 本轮会话（防刷新丢统计） ----------

export function loadSession() {
  try {
    const raw = lsGet(LS.session);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveSession(session) {
  try {
    if (session) lsSet(LS.session, JSON.stringify(session));
    else lsRemove(LS.session);
  } catch {
    // 会话统计非关键
  }
}

// ---------- 导入 ----------

function detectKind(name, text) {
  const lower = (name || '').toLowerCase();
  if (lower.endsWith('.json')) return 'json';
  if (lower.endsWith('.csv')) return 'csv';
  if (lower.endsWith('.txt')) {
    const head = text.slice(0, 200);
    return head.includes('复习时间') || head.includes('正确率') ? 'stats' : 'wordlist';
  }
  const trimmed = text.trim();
  if (trimmed.startsWith('[') || trimmed.startsWith('{')) return 'json';
  if (text.startsWith('复习时间') || text.includes('\n复习时间：')) return 'stats';
  if (text.split('\n')[0]?.split(',').length === 6) return 'csv';
  return 'wordlist';
}

export async function importFiles(files) {
  const summary = { words: 0, records: 0, stats: 0, skipped: 0, names: [] };
  const pendingRecords = [];
  let statsChunks = [];

  for (const file of files) {
    const text = await file.text();
    const kind = detectKind(file.name, text);
    if (kind === 'json') {
      let data;
      try {
        data = JSON.parse(text);
      } catch {
        summary.skipped += 1;
        continue;
      }
      let list = null;
      if (Array.isArray(data)) list = data;
      else if (Array.isArray(data.words)) {
        list = data.words;
        if (Array.isArray(data.records)) pendingRecords.push(...data.records);
        if (typeof data.statistics_text === 'string') statsChunks.push(data.statistics_text);
      }
      if (!list) {
        summary.skipped += 1;
        continue;
      }
      const words = list.filter((item) => item && typeof item.en === 'string');
      const report = core.normalizeWords(words);
      if (report.needsBackfill || report.needsMigration) {
        const rows = pendingRecords.length
          ? pendingRecords
          : await readRecords();
        if (report.needsBackfill) core.backfillCounts(words, rows);
        if (report.needsMigration) migrateLegacy(words, rows);
      }
      state.words = words;
      saveWords();
      summary.words = words.length;
      summary.names.push(file.name);
    } else if (kind === 'csv') {
      const rows = core.parseCsv(text);
      const body = rows.filter((row) => row.length >= 6 && row[0] !== '复习时间');
      pendingRecords.push(...body);
      summary.records += body.length;
      summary.names.push(file.name);
    } else if (kind === 'stats') {
      statsChunks.push(text);
      summary.stats += 1;
      summary.names.push(file.name);
    } else {
      const added = core.importWords(text, state.words);
      if (added) {
        saveWords();
        summary.words = state.words.length;
        summary.names.push(`${file.name}（新增 ${added}）`);
      } else {
        summary.skipped += 1;
      }
    }
  }

  if (pendingRecords.length) {
    const existing = await readRecords();
    if (existing.length === 0 || summary.words > 0) {
      await replaceRecords(pendingRecords);
    } else {
      await idbPutAll(STORE_RECORDS, pendingRecords);
    }
  }

  if (statsChunks.length) {
    const joined = statsChunks.join('\n');
    state.statsText = state.statsText ? `${state.statsText}\n${joined}` : joined;
    await kvSet('stats', state.statsText).catch(() => {});
  }

  const rows = await readRecords();
  rebuildAggFromRecords(rows);

  return summary;
}

/** 旧档迁移：按历史对错序列回放估算记忆强度（与桌面版一致，上限 14 天）。 */
function migrateLegacy(words, rows) {
  const sequences = core.historySequences(rows);
  for (const word of words) {
    const results = sequences.get(word.en);
    let stability;
    let ease;
    if (results && results.length) {
      [stability, ease] = core.replayResults(results);
    } else {
      [stability, ease] = core.estimateStability(word);
    }
    word.stability = core.pyRound(stability, 4);
    word.ease = core.pyRound(ease, 4);
    if (word.proficiency !== 101) {
      word.proficiency = core.proficiencyFromStability(stability);
    }
  }
}

// ---------- 导出 ----------

export function download(filename, content, mime = 'application/octet-stream') {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
  state.agg.lastExportAt = Date.now();
  saveAgg();
}

export function exportWordsText() {
  return core.serializeWords(state.words);
}

export async function exportRecordsCsv() {
  const rows = await readRecords();
  const lines = [core.csvLine(core.RECORD_HEADER.split(','))];
  for (const row of rows) lines.push(core.csvLine(row.slice(0, 6)));
  return lines.join('');
}

export async function exportStatsText() {
  return state.statsText || '';
}

export async function exportBundle() {
  const rows = await readRecords();
  return JSON.stringify(
    {
      schema: 'wordsbook-backup/1',
      exported_at: core.formatTimestamp(),
      words: JSON.parse(exportWordsText()),
      records: rows,
      statistics_text: state.statsText || '',
      aggregate: state.agg,
    },
    null,
    2,
  );
}

export async function storageEstimate() {
  if (!navigator.storage?.estimate) return null;
  try {
    return await navigator.storage.estimate();
  } catch {
    return null;
  }
}

export async function requestPersistent() {
  if (!navigator.storage?.persist) return false;
  try {
    if (await navigator.storage.persisted()) return true;
    return await navigator.storage.persist();
  } catch {
    return false;
  }
}
