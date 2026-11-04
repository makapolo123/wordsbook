// ui.js —— 纯渲染层。只负责把状态变成 DOM，不碰存储，方便单独调样式。

import * as core from './core.js';

const esc = (value) =>
  String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

export function toast(message, duration = 2200) {
  const node = $('#toast');
  if (!node) return;
  node.textContent = message;
  node.hidden = false;
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => {
    node.hidden = true;
  }, duration);
}

export function notice(message, { kind = 'error', action } = {}) {
  const node = $('#notice');
  if (!node) return;
  node.className = `notice${kind === 'tip' ? ' notice--tip' : ''}`;
  node.innerHTML = `<span>${esc(message)}</span>`;
  if (action) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'linkbtn';
    button.style.color = 'inherit';
    button.textContent = action.label;
    button.addEventListener('click', action.onClick);
    node.appendChild(button);
  }
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'notice__close';
  close.setAttribute('aria-label', '关闭');
  close.textContent = '×';
  close.addEventListener('click', () => {
    node.hidden = true;
    document.documentElement.style.setProperty('--notice-h', '0px');
  });
  node.appendChild(close);
  node.hidden = false;
  // 提示条在文档流里，会把桌面侧栏（100vh）顶出视口，这里同步真实高度做补偿
  document.documentElement.style.setProperty('--notice-h', `${node.offsetHeight}px`);
}

export function clearNotice() {
  const node = $('#notice');
  if (node) node.hidden = true;
  document.documentElement.style.setProperty('--notice-h', '0px');
}

// ---------- 底部抽屉 ----------

let sheetCleanup = null;

export function openSheet(html, { onMount } = {}) {
  const sheet = $('#sheet');
  const panel = $('#sheet-panel');
  if (!sheet || !panel) return;
  panel.innerHTML = html;
  sheet.hidden = false;
  if (sheetCleanup) sheetCleanup();
  const onMask = (event) => {
    if (event.target.dataset.close) closeSheet();
  };
  sheet.addEventListener('click', onMask);
  sheetCleanup = () => {
    sheet.removeEventListener('click', onMask);
    sheetCleanup = null;
  };
  if (onMount) onMount(panel);
}

export function closeSheet() {
  const sheet = $('#sheet');
  if (sheet) sheet.hidden = true;
  if (sheetCleanup) sheetCleanup();
}

// ---------- 首页 ----------

const INTERVALS = [
  ['入门', 50, 59],
  ['熟悉', 60, 69],
  ['掌握中', 70, 79],
  ['接近达标', 80, 100],
];

export function renderHome({ words, now, hasData, onStart, onImport }) {
  const host = $('#home-body');
  if (!host) return;

  $('#home-title').textContent = core.greeting();
  const today = new Date();
  const weekday = '日一二三四五六'[today.getDay()];
  $('#home-date').textContent =
    `${today.getFullYear()}年${today.getMonth() + 1}月${today.getDate()}日 · 周${weekday}`;

  if (!hasData) {
    host.innerHTML = `
      <div class="card">
        <p class="card__title">先把词库导进来</p>
        <p class="card__sub">支持桌面版导出的 words.json（带完整进度），也支持"英文, 中文"格式的 TXT 词表。</p>
        <div class="sheet__actions">
          <button class="btn btn--block" id="home-import" type="button">选择文件导入</button>
        </div>
        <p class="card__sub" style="margin-top:12px">
          数据只保存在这台设备上，不上传任何服务器。
        </p>
      </div>`;
    $('#home-import')?.addEventListener('click', onImport);
    return;
  }

  const total = words.length;
  const mastered = words.filter((word) => (word.proficiency ?? 0) >= core.STD_PRO).length;
  const due = core.dueCount(words, now);
  const newCount = words.filter(
    (word) => (word.proficiency ?? 0) < core.STD_PRO && (word.stability ?? 0) <= 0,
  ).length;
  const reviewed = words.filter((word) => (word.proficiency ?? 0) < 101);
  const average = reviewed.length
    ? core.pyRound(
        reviewed.reduce((sum, word) => sum + (word.proficiency ?? core.MIN_PRO), 0) / reviewed.length,
        0,
      )
    : 0;

  let headline;
  let description;
  if (due) {
    headline = `今天有 ${due} 个单词待复习`;
    description = '系统会优先安排临近遗忘的词。一次只专注一个词，完成后进度会自动保存。';
  } else if (total === 0) {
    headline = '从导入第一组单词开始';
    description = '准备一个 TXT 词表，每行用英文和中文释义组成，即可开始自己的学习节奏。';
  } else if (mastered >= total) {
    headline = '今天的单词已经全部掌握';
    description = '所有单词都已达到目标熟练度。你可以继续浏览词库，或导入新的学习内容。';
  } else {
    headline = '这一轮已经完成';
    description = `最近一组单词预计在 ${core.formatWait(core.nextDueSeconds(words, now))}后到期，届时再来复习即可。`;
  }

  const nextWait = core.nextDueSeconds(words, now);
  const maxCount = Math.max(
    1,
    ...INTERVALS.map(
      ([, low, high]) => words.filter((word) => (word.proficiency ?? 0) >= low && (word.proficiency ?? 0) <= high).length,
    ),
  );

  host.innerHTML = `
    <div class="hero">
      <div class="hero__head">
        <div style="min-width:0">
          <p class="hero__eyebrow">今日复习</p>
          <h2 class="hero__title">${esc(headline)}</h2>
          <p class="hero__desc">${esc(description)}</p>
        </div>
        <div class="ring" style="--p:${total ? (mastered / total) * 100 : 0}">
          <div class="ring__text">
            <b>${total ? ((mastered / total) * 100).toFixed(1) : '0.0'}%</b>
            <span>已掌握</span>
          </div>
        </div>
      </div>
      <div class="hero__stats">
        <div class="hero__stat"><b>${mastered}</b><span>已掌握</span></div>
        <div class="hero__divider"></div>
        <div class="hero__stat"><b>${average}</b><span>平均熟练度</span></div>
        <div class="hero__divider"></div>
        <div class="hero__stat"><b>${newCount}</b><span>新词</span></div>
      </div>
      <button class="btn btn--block" id="home-start" type="button">开始复习 →</button>
    </div>

    <div class="card">
      <p class="card__title">熟练度分布</p>
      <p class="card__sub">记忆强度换算后的当前区间</p>
      <div style="margin-top:12px">
        ${INTERVALS.map(([label, low, high]) => {
          const count = words.filter(
            (word) => (word.proficiency ?? 0) >= low && (word.proficiency ?? 0) <= high,
          ).length;
          return `<div class="dist-row">
            <span class="dist-row__label">${label}</span>
            <div class="meter"><i style="width:${(count / maxCount) * 100}%"></i></div>
            <span class="dist-row__count">${count}</span>
          </div>`;
        }).join('')}
      </div>
    </div>

    <div class="card">
      <p class="card__title">学习节奏</p>
      <p class="card__sub">根据当前记忆强度计算</p>
      <div style="margin-top:8px">
        <div class="detail-row"><span>待复习</span><b>${due} 个</b></div>
        <div class="detail-row"><span>新词</span><b>${newCount} 个</b></div>
        <div class="detail-row"><span>最近到期</span><b>${due ? '现在' : esc(core.formatWait(nextWait))}</b></div>
        <div class="detail-row"><span>词库总数</span><b>${total} 个</b></div>
      </div>
    </div>`;

  $('#home-start')?.addEventListener('click', onStart);
}

// ---------- 单词库 ----------

const STATUS_PILL = {
  已掌握: 'pill--done',
  已达标: 'pill--done',
  新词: 'pill--new',
  待复习: 'pill--due',
  已排期: 'pill--idle',
};

export function renderLibraryHeader({ total, count }) {
  const sub = $('#library-sub');
  if (sub) sub.textContent = `共 ${total} 个单词 · 查看、筛选或导入新的学习内容`;
  const counter = $('#library-count');
  if (counter) counter.textContent = `${count} 条记录`;
}

export function wordRow(word, now) {
  const status = core.wordStatus(word, now);
  return `<button class="wordrow" type="button" data-en="${esc(word.en)}">
    <div class="wordrow__top">
      <span class="wordrow__en">${esc(word.en)}</span>
      <span class="wordrow__pro">${word.proficiency ?? core.MIN_PRO}</span>
    </div>
    <div class="wordrow__cn">${esc(word.cn)}</div>
    <div class="wordrow__foot">
      <span class="pill ${STATUS_PILL[status] || 'pill--idle'}">${status}</span>
      <span class="wordrow__next">${esc(core.nextReviewText(word, now))}</span>
    </div>
  </button>`;
}

export function filterWords(words, query, filter, now) {
  const needle = query.trim().toLowerCase();
  const result = [];
  for (const word of words) {
    if (needle) {
      const en = String(word.en ?? '').toLowerCase();
      const cn = String(word.cn ?? '').toLowerCase();
      if (!en.includes(needle) && !cn.includes(needle)) continue;
    }
    if (filter !== '全部单词') {
      const status = core.wordStatus(word, now);
      if (filter === '待复习' && status !== '待复习' && status !== '新词') continue;
      if (filter === '新词' && status !== '新词') continue;
      if (filter === '已掌握' && status !== '已掌握' && status !== '已达标') continue;
    }
    result.push(word);
  }
  // 按码点排序，与桌面版 sorted(key=en.lower()) 一致（不能用 localeCompare）
  result.sort((a, b) => {
    const left = String(a.en ?? '').toLowerCase();
    const right = String(b.en ?? '').toLowerCase();
    if (left < right) return -1;
    if (left > right) return 1;
    return 0;
  });
  return result;
}

export function wordDetailSheet(word, now) {
  const definition = core.formatDefinition(word.cn);
  const status = core.wordStatus(word, now);
  const last = word.last_review ? core.formatTimestamp(new Date(word.last_review * 1000)) : '未复习';
  const first = word.first_review ? core.formatTimestamp(new Date(word.first_review * 1000)) : '未复习';
  return `
    <p class="sheet__title">${esc(word.en)}</p>
    <p class="sheet__sub">熟练度 ${word.proficiency ?? core.MIN_PRO} · ${status}</p>
    <div class="sheet__section">
      ${definition.map((line) => `<div class="def-line">${esc(line)}</div>`).join('')}
    </div>
    <div class="sheet__section">
      <h3>记忆信息</h3>
      <div class="detail-row"><span>记忆强度</span><b>${(word.stability ?? 0).toFixed(2)} 天</b></div>
      <div class="detail-row"><span>增长系数</span><b>${(word.ease ?? core.EASE_DEFAULT).toFixed(2)}</b></div>
      <div class="detail-row"><span>下次复习</span><b>${esc(core.nextReviewText(word, now))}</b></div>
      <div class="detail-row"><span>首次复习</span><b>${first}</b></div>
      <div class="detail-row"><span>最近复习</span><b>${last}</b></div>
      <div class="detail-row"><span>答对 / 答错</span><b>${word.success_count ?? 0} / ${word.fail_count ?? 0}</b></div>
    </div>
    <div class="sheet__actions">
      <button class="btn btn--secondary btn--block" type="button" data-close="1">关闭</button>
    </div>`;
}

// ---------- 学习记录 ----------

export function renderRecords({ agg, rows, todayCount, onImport, onExport, storageText }) {
  const host = $('#records-body');
  if (!host) return;

  const judged = agg.totalRemembered + agg.totalForgotten;
  const accuracy = judged ? (agg.totalRemembered / judged) * 100 : 0;
  const weekly = core.weeklyCounts(rows, new Date());
  const maxCount = Math.max(1, ...weekly.map((day) => day.count));
  const recent = rows.slice(-12).reverse();

  const resultLabel = (value) => {
    const text = String(value ?? '');
    if (text.startsWith('marked_remembered')) return '记住了（不再复习）';
    if (text.startsWith('forgotten')) return '没想起来';
    if (text.startsWith('remembered')) return '记住了';
    return text;
  };

  host.innerHTML = `
    <div class="stat-grid">
      <div class="stat"><span>累计复习</span><b>${agg.totalReviews}</b><small>次单词作答</small></div>
      <div class="stat"><span>今日复习</span><b>${todayCount}</b><small>次单词作答</small></div>
      <div class="stat"><span>记住率</span><b>${Math.round(accuracy)}%</b><small>不含彻底掌握标记</small></div>
    </div>

    <div class="card">
      <p class="card__title">近 7 天复习量</p>
      <div class="chart">
        ${weekly
          .map(
            (day) => `<div class="chart__col">
              <span class="chart__value">${day.count || ''}</span>
              <div class="chart__bar ${day.count ? '' : 'chart__bar--empty'}" style="height:${day.count ? Math.max(4, (day.count / maxCount) * 74) : 4}px"></div>
              <span class="chart__label">${day.label}</span>
            </div>`,
          )
          .join('')}
      </div>
    </div>

    <div class="card">
      <p class="card__title">最近复习</p>
      ${
        recent.length
          ? `<div style="margin-top:6px">${recent
              .map((row) => {
                const change =
                  row.length >= 5 ? `${row[3]} → ${row[4]}` : '';
                return `<div class="recent-row">
                  <span class="recent-row__time">${esc(String(row[0] ?? '').slice(11, 16))}</span>
                  <span class="recent-row__word">${esc(row[1])}</span>
                  <span class="pill ${String(row[5]).startsWith('forgotten') ? 'pill--new' : 'pill--due'}">${esc(resultLabel(row[5]))}</span>
                  <span class="recent-row__change">${esc(change)}</span>
                </div>`;
              })
              .join('')}</div>`
          : '<p class="empty">还没有复习记录，先去背几个词吧。</p>'
      }
    </div>

    <div class="card">
      <p class="card__title">数据管理</p>
      <p class="card__sub">进度只存在本机。换设备或给电脑版同步时，用导出／导入搬一次即可。</p>
      <div class="sheet__actions">
        <button class="btn btn--secondary btn--block" id="data-import" type="button">导入存档（words.json / CSV / TXT）</button>
        <button class="btn btn--secondary btn--block" id="data-export" type="button">导出备份</button>
      </div>
      <p class="card__sub" style="margin-top:12px">${esc(storageText || '')}</p>
    </div>`;

  $('#data-import')?.addEventListener('click', onImport);
  $('#data-export')?.addEventListener('click', onExport);
}

export function exportSheetHtml() {
  return `
    <p class="sheet__title">导出备份</p>
    <p class="sheet__sub">导出的 words.json 可以直接覆盖电脑版同名文件，字段与桌面版一致。</p>
    <div class="sheet__actions">
      <button class="btn btn--block" type="button" data-export="words">words.json（进度存档）</button>
      <button class="btn btn--secondary btn--block" type="button" data-export="csv">word_record.csv（复习明细）</button>
      <button class="btn btn--secondary btn--block" type="button" data-export="stats">statistic_data.txt（会话统计）</button>
      <button class="btn btn--secondary btn--block" type="button" data-export="bundle">全部打包（单个 JSON）</button>
      <button class="btn btn--secondary btn--block" type="button" data-close="1">取消</button>
    </div>`;
}

// ---------- 复习页 ----------

export function renderSessionLabel(session) {
  const node = $('#review-session');
  if (!node) return;
  node.textContent = session.reviewCount
    ? `本轮已复习 ${session.reviewCount} 次 · 记住 ${session.rememberedCount} 次`
    : '按记忆强度自动安排，随时可以结束';
}

const SWIPE_ICON =
  '<svg class="swipe-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 15l7-7 7 7"/></svg>';

// 触摸结束后浏览器会补发一套兼容鼠标事件，若不加压制，同一次滑动会被算成两次。
// 这套回放在手指离开后约 450ms 才开始，所以每个触摸事件都要刷新时间戳。
let lastTouchAt = 0;

const markTouch = (event) => {
  if (event.pointerType !== 'mouse') lastTouchAt = Date.now();
};

// 上滑手势：卡片跟随手指上移，松手超过阈值才执行动作，未过阈值回弹。
function attachSwipeReview(card, getAction) {
  let active = false;
  let decided = false;
  let startY = 0;
  let startX = 0;
  let travel = 0;

  const limit = () => Math.max(54, Math.min(112, card.clientHeight * 0.16));

  const clear = () => {
    card.classList.remove('is-dragging', 'is-leaving');
    card.style.transform = '';
    card.style.opacity = '';
  };

  card.addEventListener('pointerdown', (event) => {
    markTouch(event);
    if (!card.isConnected) return;
    if (event.pointerType === 'mouse' && (event.button !== 0 || Date.now() - lastTouchAt < 1000)) {
      return;
    }
    if (event.target.closest('button, a, input, textarea, select')) return;
    active = true;
    decided = false;
    startY = event.clientY;
    startX = event.clientX;
    travel = 0;
    card.classList.add('is-dragging');
    card.style.transform = '';
    card.style.opacity = '';
  });

  card.addEventListener('pointermove', (event) => {
    markTouch(event);
    if (!active) return;
    const deltaY = event.clientY - startY;
    const deltaX = event.clientX - startX;
    if (!decided) {
      if (Math.abs(deltaY) < 6 && Math.abs(deltaX) < 6) return;
      if (Math.abs(deltaX) > Math.abs(deltaY)) {
        active = false;
        clear();
        return;
      }
      decided = true;
      if (card.setPointerCapture) card.setPointerCapture(event.pointerId);
    }
    const edge = limit();
    const distance = Math.abs(Math.min(0, deltaY));
    travel = distance <= edge ? distance : edge + (distance - edge) * 0.45;
    if (event.cancelable) event.preventDefault();
    card.style.transform = `translateY(${-travel}px)`;
    card.style.opacity = String(Math.max(0.45, 1 - (travel / (edge * 1.8)) * 0.3));
  });

  const settle = () => {
    if (!active) return;
    active = false;
    const passed = travel >= limit() * 0.92;
    card.classList.remove('is-dragging');
    if (!passed) {
      clear();
      return;
    }
    card.classList.add('is-leaving');
    void card.offsetHeight;
    card.style.transform = 'translateY(-118%)';
    card.style.opacity = '0';
    window.setTimeout(() => {
      getAction()();
      // 动作被拦截（例如写入失败）时卡片不会被重绘，需要恢复原状
      if (card.isConnected) clear();
    }, 180);
  };

  card.addEventListener('pointerup', (event) => {
    markTouch(event);
    settle();
  });
  card.addEventListener('pointercancel', (event) => {
    markTouch(event);
    active = false;
    clear();
  });
}

export function renderReviewQuestion({ word, revealed, processed, handlers }) {
  const host = $('#review-body');
  if (!host) return;

  const isNew = (word.stability ?? 0) <= 0;
  const definition = core.formatDefinition(word.cn);
  const meta = `
    <div class="review__meta">
      <span class="pill ${isNew ? 'pill--new' : 'pill--due'}">${isNew ? '新词' : '到期复习'}</span>
      <span class="review__pro">熟练度 ${word.proficiency ?? core.MIN_PRO}</span>
    </div>`;

  const wordHtml = `<div class="review__word">${esc(word.en)}</div>`;
  const defHtml = `
    <div class="review__divider"></div>
    <p class="review__label">释义</p>
    <div class="review__def" id="review-def">${definition
      .map((line) => `<div>${esc(line)}</div>`)
      .join('')}</div>`;

  let center;
  let actions;

  const tip = (text) => `<p class="review__tip review__tip--swipe">${SWIPE_ICON}${text}</p>`;

  if (!revealed) {
    center = `${wordHtml}${tip('上滑查看释义')}`;
    actions = `<div class="review__actions">
      <button class="btn btn--block" data-act="know" type="button">1　认识</button>
      <button class="btn btn--secondary btn--block" data-act="unknown" type="button">2　不认识</button>
    </div>`;
  } else if (!processed) {
    center = `${wordHtml}${defHtml}${tip('上滑进入下一个单词')}`;
    actions = `<div class="review__actions">
      <button class="btn btn--block" data-act="next" type="button">1　下一个</button>
      <button class="btn btn--secondary btn--block" data-act="forgot" type="button">2　记错了</button>
      <button class="btn btn--secondary btn--block" data-act="mark" type="button">3　记住了</button>
    </div>
    <p class="review__note">选择“记住了”后，这个词以后不再复习</p>`;
  } else {
    center = `${wordHtml}${defHtml}${tip('上滑继续')}`;
    actions = `<div class="review__actions">
      <button class="btn btn--block" data-act="advance" type="button">下一个单词</button>
    </div>`;
  }

  host.innerHTML = `<div class="review__card">
    ${meta}
    <div class="review__center">${center}</div>
    ${actions}
  </div>`;

  const bind = (act, fn) =>
    host.querySelector(`[data-act="${act}"]`)?.addEventListener('click', fn);
  bind('know', handlers.reveal);
  bind('unknown', handlers.unknown);
  bind('next', handlers.remembered);
  bind('forgot', handlers.forgotten);
  bind('mark', handlers.marked);
  bind('advance', handlers.advance);

  const card = host.querySelector('.review__card');
  if (card) {
    const action = !revealed ? handlers.reveal : processed ? handlers.advance : handlers.remembered;
    attachSwipeReview(card, () => action);
  }
}

export function renderReviewEmpty({ title, detail, handlers }) {
  const host = $('#review-body');
  if (!host) return;
  host.innerHTML = `<div class="review__card">
    <div class="review__done">
      <div class="review__check">✓</div>
      <h2>${esc(title)}</h2>
      <p>${esc(detail)}</p>
      <div class="review__actions review__actions--row">
        <button class="btn btn--secondary" data-act="library" type="button">查看单词库</button>
        <button class="btn" data-act="home" type="button">回到首页</button>
      </div>
    </div>
  </div>`;
  host.querySelector('[data-act="library"]')?.addEventListener('click', handlers.library);
  host.querySelector('[data-act="home"]')?.addEventListener('click', handlers.home);
}

export function setReviewVisible(visible) {
  const node = $('#review');
  if (node) node.hidden = !visible;
  document.body.style.overflow = visible ? 'hidden' : '';
}
