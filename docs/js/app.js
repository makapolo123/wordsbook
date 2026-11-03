// app.js —— 启动、路由、复习状态机与所有事件绑定。

import * as core from './core.js';
import * as store from './store.js';
import * as ui from './ui.js';

const PAGE_SIZE = 60;

const app = {
  page: 'home',
  session: null,
  currentWord: null,
  revealed: false,
  processed: false,
  query: '',
  filter: '全部单词',
  filtered: [],
  rendered: 0,
  blocked: false,
  observer: null,
};

// ---------- 通用 ----------

const now = () => Date.now() / 1000;

function words() {
  return store.state.words;
}

function refreshChrome() {
  const list = words();
  const total = list.length;
  const mastered = list.filter((word) => (word.proficiency ?? 0) >= core.STD_PRO).length;
  const due = core.dueCount(list, now());

  const summary = document.querySelector('#side-summary');
  if (summary) summary.textContent = `${mastered} / ${total} 已掌握`;
  const meter = document.querySelector('#side-meter');
  if (meter) meter.style.width = `${total ? (mastered / total) * 100 : 0}%`;
  const sideDue = document.querySelector('#side-due');
  if (sideDue) sideDue.textContent = `${due} 个待复习`;

  const badge = document.querySelector('#tab-badge');
  if (badge) {
    badge.textContent = due > 99 ? '99+' : String(due);
    badge.hidden = due === 0;
  }
}

function go(page, { silent = false } = {}) {
  if (app.page === 'review' && page !== 'review') finishSession();
  app.page = page;

  document.querySelectorAll('.view').forEach((section) => {
    section.classList.toggle('is-active', section.dataset.view === page);
  });
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.classList.toggle('is-active', tab.dataset.target === page);
  });
  document.querySelectorAll('.navlink').forEach((tab) => {
    tab.classList.toggle('is-active', tab.dataset.target === page);
  });

  if (!silent && !app.blocked) ui.clearNotice();
  refreshChrome();

  if (page === 'home') renderHome();
  if (page === 'library') renderLibrary();
  if (page === 'records') renderRecords();
  window.scrollTo({ top: 0 });
}

// ---------- 首页 ----------

function renderHome() {
  ui.renderHome({
    words: words(),
    now: now(),
    hasData: words().length > 0,
    onStart: () => startReview(),
    onImport: () => pickFiles(),
  });
  maybePromptExport();
}

function maybePromptExport() {
  if (!words().length || app.blocked) return;
  const last = store.state.agg.lastExportAt || 0;
  const stale = !last || Date.now() - last > 7 * 86400000;
  if (!stale) return;
  if (sessionStorage.getItem('wb.export-prompt') === 'off') return;
  ui.notice('浏览器可能在长期不用时清理网页数据，建议导出一份备份。', {
    kind: 'tip',
    action: {
      label: '去导出',
      onClick: () => {
        sessionStorage.setItem('wb.export-prompt', 'off');
        openExportSheet();
      },
    },
  });
}

// ---------- 单词库 ----------

function renderLibrary() {
  app.filtered = ui.filterWords(words(), app.query, app.filter, now());
  app.rendered = 0;
  const list = document.querySelector('#word-list');
  if (list) list.innerHTML = '';
  ui.renderLibraryHeader({ total: words().length, count: app.filtered.length });
  if (!app.filtered.length) {
    if (list) {
      list.innerHTML = `<p class="empty">${
        words().length ? '没有符合条件的单词，换个搜索词或筛选条件试试。' : '词库还是空的，先导入一份词表吧。'
      }</p>`;
    }
    return;
  }
  renderMore();
  setupObserver();
}

function renderMore() {
  const list = document.querySelector('#word-list');
  if (!list) return;
  const slice = app.filtered.slice(app.rendered, app.rendered + PAGE_SIZE);
  if (!slice.length) return;
  const html = slice.map((word) => ui.wordRow(word, now())).join('');
  list.insertAdjacentHTML('beforeend', html);
  app.rendered += slice.length;
}

function setupObserver() {
  const sentinel = document.querySelector('#list-sentinel');
  if (!sentinel) return;
  if (app.observer) app.observer.disconnect();
  if (app.rendered >= app.filtered.length) return;
  app.observer = new IntersectionObserver(
    (entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      renderMore();
      if (app.rendered >= app.filtered.length) app.observer.disconnect();
    },
    { rootMargin: '200px' },
  );
  app.observer.observe(sentinel);
}

function openWordDetail(english) {
  const word = words().find((item) => item.en === english);
  if (!word) return;
  ui.openSheet(ui.wordDetailSheet(word, now()));
}

// ---------- 学习记录 ----------

async function renderRecords() {
  const rows = await store.readRecords();
  const todayKey = core.dateKey(new Date());
  const todayCount = rows.filter((row) => String(row[0] ?? '').startsWith(todayKey)).length;

  let storageText = '';
  const estimate = await store.storageEstimate();
  if (estimate?.usage != null) {
    const used = (estimate.usage / 1048576).toFixed(2);
    const quota = estimate.quota ? (estimate.quota / 1048576).toFixed(0) : '?';
    storageText = `已用 ${used} MB / 可用 ${quota} MB · 共 ${rows.length} 条复习明细`;
  } else {
    storageText = `共 ${rows.length} 条复习明细`;
  }

  ui.renderRecords({
    agg: store.state.agg,
    rows,
    todayCount,
    storageText,
    onImport: () => pickFiles(),
    onExport: () => openExportSheet(),
  });
}

function openExportSheet() {
  ui.openSheet(ui.exportSheetHtml(), {
    onMount: (panel) => {
      panel.querySelectorAll('[data-export]').forEach((button) => {
        button.addEventListener('click', async () => {
          const kind = button.dataset.export;
          try {
            if (kind === 'words') {
              store.download('words.json', store.exportWordsText(), 'application/json');
            } else if (kind === 'csv') {
              store.download('word_record.csv', await store.exportRecordsCsv(), 'text/csv');
            } else if (kind === 'stats') {
              store.download('statistic_data.txt', await store.exportStatsText(), 'text/plain');
            } else {
              store.download('wordsbook-backup.json', await store.exportBundle(), 'application/json');
            }
            ui.closeSheet();
            ui.toast('已导出，请确认浏览器已保存文件');
          } catch (error) {
            ui.toast(`导出失败：${error.message || error}`);
          }
        });
      });
    },
  });
}

// ---------- 复习 ----------

function newSession() {
  return {
    startTime: now(),
    reviewCount: 0,
    rememberedCount: 0,
    newWords: 0,
    words: [],
    finished: false,
  };
}

function startReview() {
  if (!words().length) {
    ui.toast('词库还是空的，先导入单词');
    return;
  }
  if (app.page !== 'review') {
    app.session = newSession();
    store.saveSession(app.session);
  }
  app.page = 'review';
  ui.setReviewVisible(true);
  ui.renderSessionLabel(app.session);
  loadNextWord();
}

function loadNextWord() {
  app.revealed = false;
  app.processed = false;
  app.currentWord = core.pickRandomWord(words(), now());
  if (!app.currentWord) {
    renderReviewDone();
    return;
  }
  ui.renderSessionLabel(app.session);
  ui.renderReviewQuestion({
    word: app.currentWord,
    revealed: false,
    processed: false,
    handlers: reviewHandlers(),
  });
}

function reviewHandlers() {
  return {
    reveal: () => {
      app.revealed = true;
      redrawReview();
    },
    unknown: () => recordAnswer('forgotten', false),
    remembered: () => recordAnswer('remembered', true),
    forgotten: () => recordAnswer('forgotten', true),
    marked: () => recordAnswer('marked_remembered', true),
    advance: () => loadNextWord(),
    library: () => exitReview('library'),
    home: () => exitReview('home'),
  };
}

function redrawReview() {
  if (!app.currentWord) return;
  ui.renderSessionLabel(app.session);
  ui.renderReviewQuestion({
    word: app.currentWord,
    revealed: app.revealed,
    processed: app.processed,
    handlers: reviewHandlers(),
  });
}

function renderReviewDone() {
  ui.renderSessionLabel(app.session);
  let title;
  let detail;
  if (core.allWordFinish(words()) && words().length) {
    title = '所有单词都已达标';
    detail = '这一阶段的学习已经完成，可以导入新的词表继续前进。';
  } else if (app.session.reviewCount) {
    title = '这一轮完成了';
    detail = `最近一组单词将在 ${core.formatWait(core.nextDueSeconds(words(), now()))}后到期。`;
  } else {
    title = '暂时没有到期单词';
    detail = `最近一组单词将在 ${core.formatWait(core.nextDueSeconds(words(), now()))}后到期。`;
  }
  ui.renderReviewEmpty({
    title,
    detail,
    handlers: {
      library: () => exitReview('library'),
      home: () => exitReview('home'),
    },
  });
}

function recordAnswer(result, advance) {
  const word = app.currentWord;
  if (!word || app.processed) return;
  if (app.blocked) {
    ui.notice('进度写入失败，先导出备份再继续答题。', {
      action: { label: '去导出', onClick: openExportSheet },
    });
    return;
  }

  const initialProficiency = word.proficiency ?? core.MIN_PRO;
  const recordTime = core.formatTimestamp();
  const stamp = now();

  if (result === 'marked_remembered') {
    word.proficiency = 101;
  } else {
    const remembered = result === 'remembered';
    [word.stability, word.ease] = core.applyAnswer(
      word.stability ?? 0,
      word.ease ?? core.EASE_DEFAULT,
      remembered,
    );
    word.proficiency = core.proficiencyFromStability(word.stability);
  }

  if ((word.first_review ?? 0) === 0) {
    app.session.newWords += 1;
    word.first_review = stamp;
  }
  if (result === 'forgotten') word.fail_count = (word.fail_count ?? 0) + 1;
  else word.success_count = (word.success_count ?? 0) + 1;

  word.last_review = stamp;
  app.session.reviewCount += 1;
  if (result === 'remembered') app.session.rememberedCount += 1;
  if (!app.session.words.includes(word.en)) app.session.words.push(word.en);
  store.saveSession(app.session);

  app.processed = true;
  app.revealed = true;

  const row = [recordTime, word.en, word.cn, initialProficiency, word.proficiency, result];
  store.addRecord(row);
  store.bumpAgg(result, recordTime);

  try {
    store.saveWords();
  } catch (error) {
    app.blocked = true;
    ui.notice('进度写入失败，请立即导出备份后再继续。', {
      action: { label: '去导出', onClick: openExportSheet },
    });
    ui.toast('进度未能保存');
    return;
  }

  refreshChrome();
  if (advance) loadNextWord();
  else redrawReview();
}

function finishSession() {
  const session = app.session;
  if (!session || session.finished) return;
  if (session.startTime && session.reviewCount > 0) {
    const block = store.buildSessionBlock(
      session.startTime,
      now(),
      session.reviewCount,
      session.rememberedCount,
      session.words.length,
      session.newWords,
    );
    store.appendSessionBlock(block);
  }
  session.finished = true;
  store.saveSession(null);
  app.session = null;
}

function exitReview(page) {
  finishSession();
  ui.setReviewVisible(false);
  app.currentWord = null;
  go(page);
}

// ---------- 导入 ----------

function pickFiles() {
  const input = document.querySelector('#file-input');
  if (!input) return;
  input.value = '';
  input.click();
}

async function handleFiles(fileList) {
  const files = Array.from(fileList || []);
  if (!files.length) return;
  ui.toast('正在导入…', 4000);
  try {
    const summary = await store.importFiles(files);
    const parts = [];
    if (summary.words) parts.push(`词库 ${summary.words} 个词`);
    if (summary.records) parts.push(`明细 ${summary.records} 条`);
    if (summary.stats) parts.push(`统计 ${summary.stats} 份`);
    if (summary.skipped) parts.push(`跳过 ${summary.skipped} 个文件`);
    ui.toast(parts.length ? `导入完成：${parts.join('，')}` : '没有识别到可用内容', 3200);
    if (summary.words) store.requestPersistent();
    refreshChrome();
    if (app.page === 'home') renderHome();
    if (app.page === 'library') renderLibrary();
    if (app.page === 'records') renderRecords();
  } catch (error) {
    ui.notice(`导入失败：${error.message || error}`);
  }
}

// ---------- 键盘（桌面浏览器） ----------

function onKey(event) {
  if (app.page !== 'review' || !app.currentWord) return;
  if (event.target instanceof HTMLInputElement) return;
  const key = event.key;
  if (app.processed) {
    if (key === 'Enter' || key === ' ') {
      event.preventDefault();
      loadNextWord();
    }
    return;
  }
  if (!app.revealed) {
    if (key === '1') {
      app.revealed = true;
      redrawReview();
    } else if (key === '2') {
      recordAnswer('forgotten', false);
    }
    return;
  }
  if (key === '1') recordAnswer('remembered', true);
  else if (key === '2') recordAnswer('forgotten', true);
  else if (key === '3') recordAnswer('marked_remembered', true);
}

// ---------- 启动 ----------

function bindChrome() {
  document.querySelectorAll('.tab, .navlink').forEach((button) => {
    button.addEventListener('click', () => go(button.dataset.target));
  });

  document.querySelector('#review-exit')?.addEventListener('click', () => exitReview('home'));

  const search = document.querySelector('#search-input');
  if (search) {
    let timer = null;
    search.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        app.query = search.value;
        renderLibrary();
      }, 120);
    });
  }

  document.querySelectorAll('#filter-chips .chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      app.filter = chip.dataset.filter;
      document.querySelectorAll('#filter-chips .chip').forEach((item) => {
        item.classList.toggle('is-active', item === chip);
      });
      renderLibrary();
    });
  });

  document.querySelector('#word-list')?.addEventListener('click', (event) => {
    const row = event.target.closest('.wordrow');
    if (row) openWordDetail(row.dataset.en);
  });

  document.querySelector('#library-import')?.addEventListener('click', () => pickFiles());

  document.querySelector('#file-input')?.addEventListener('change', (event) => {
    handleFiles(event.target.files);
    event.target.value = '';
  });

  document.addEventListener('keydown', onKey);

  // 切后台/关闭前确保进度落盘（iOS 杀进程前只有这一线机会）
  const flush = () => {
    try {
      if (words().length) store.saveWords();
    } catch {
      /* 已经提示过用户 */
    }
  };
  window.addEventListener('pagehide', flush);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flush();
  });
}

function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return;
  if (location.protocol !== 'https:' && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') {
    return; // 非安全上下文不注册，避免控制台噪音
  }
  window.addEventListener('load', async () => {
    try {
      const registration = await navigator.serviceWorker.register('./sw.js', { scope: './' });
      registration.addEventListener('updatefound', () => {
        const worker = registration.installing;
        if (!worker) return;
        worker.addEventListener('statechange', () => {
          if (worker.state === 'installed' && navigator.serviceWorker.controller) {
            ui.notice('有新版本可用。', {
              kind: 'tip',
              action: { label: '刷新', onClick: () => location.reload() },
            });
          }
        });
      });
    } catch (error) {
      console.warn('Service Worker 注册失败', error);
    }
  });
}

async function boot() {
  const words0 = store.loadWords();
  store.loadAgg();
  store.requestPersistent();

  if (words0.corrupt) {
    ui.notice('本地存档已损坏，已备份原文。请导入之前的备份文件恢复。', {
      action: { label: '导入', onClick: () => pickFiles() },
    });
  }

  bindChrome();
  refreshChrome();
  go('home');

  // 上次没走完的那一轮：刷新/被杀进程时补写统计，避免这一轮白背
  const orphan = store.loadSession();
  if (orphan && !orphan.finished && orphan.reviewCount > 0) {
    store.appendSessionBlock(
      store.buildSessionBlock(
        orphan.startTime,
        now(),
        orphan.reviewCount,
        orphan.rememberedCount,
        (orphan.words || []).length,
        orphan.newWords,
      ),
    );
  }
  store.saveSession(null);

  // 补写上次没落库的明细
  store.flushPending().catch(() => {});
  store.loadStatsText().catch(() => {});

  registerServiceWorker();

  if (!words0.count && !words0.corrupt) {
    setTimeout(() => {
      if (!words().length) ui.toast('先导入一份词表开始使用', 3200);
    }, 600);
  }
}

boot();
