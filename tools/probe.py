"""生成 JS 移植的对照基准（fixtures）。

直接调用真实的 words_book.py / words_book_gui.py，把各种输入下的输出导出为 JSON，
供 tools/verify.mjs 在 Node 里逐条比对。只读，不修改任何存档。

用法：python tools/probe.py
"""
from __future__ import annotations

import csv
import json
import random
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SNAPSHOT = BASE / "_backup_before_web"

sys.path.insert(0, str(BASE))
import words_book as core  # noqa: E402

try:
    import words_book_gui as gui  # noqa: E402
except Exception as err:  # tkinter 缺失时退化为只测核心
    gui = None
    print("警告：无法导入 words_book_gui，释义/状态基准将被跳过：", err)


def load_words() -> list[dict]:
    with open(SNAPSHOT / "words.json", encoding="utf-8") as f:
        return json.load(f)


def dump(name: str, payload) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    path = FIXTURES / name
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"  写出 {path.name}（{path.stat().st_size // 1024} KB）")


class FixedClock:
    """临时替换 time.time，让依赖当前时间的函数变得可复现。"""

    def __init__(self, value: float) -> None:
        self.value = value
        self.original = time.time

    def __enter__(self):
        time.time = lambda: self.value
        return self

    def __exit__(self, *_exc):
        time.time = self.original


class FakeRandomModule:
    """替换 words_book 里的 random 模块，让抽取过程完全可复现。

    必须直接替换模块对象，而不是 patch random.random —— CPython 的
    Random.choices 内部用的是 self.random，patch 模块属性对它无效。
    choices 按 CPython 源码复刻：累加权重 + bisect(cum, u*total, 0, n-1)。
    """

    def __init__(self, sequence) -> None:
        self.sequence = list(sequence)
        self.calls: list[float] = []

    def random(self) -> float:
        index = len(self.calls)
        value = self.sequence[index] if index < len(self.sequence) else 0.5
        self.calls.append(value)
        return value

    def choices(self, population, weights=None, *, cum_weights=None, k=1):
        from bisect import bisect
        from itertools import accumulate, repeat

        if cum_weights is None:
            if weights is None:
                n = len(population)
                return [population[min(int(self.random() * n), n - 1)]
                        for _ in repeat(None, k)]
            cum_weights = list(accumulate(weights))
        total = cum_weights[-1] + 0.0
        hi = len(population) - 1
        return [population[bisect(cum_weights, self.random() * total, 0, hi)]
                for _ in repeat(None, k)]


def probe_answer() -> None:
    grid = []
    stabilities = [0.0, 0.25, 0.4, 0.5, 0.625, 1.25, 3.5, 8.75, 42.0,
                   389.9999, 390.0, 0.03125, 0.0312500001, 100.0, 0.3]
    eases = [1.3, 1.4, 1.5, 2.1, 2.5, 2.6, 2.9, 3.0]
    for s in stabilities:
        for e in eases:
            for remembered in (True, False):
                stable, ease = core.apply_answer(s, e, remembered)
                grid.append({"s": s, "e": e, "r": remembered, "out": [stable, ease]})

    rng = random.Random(20261103)
    for _ in range(5000):
        s = rng.choice([0.0, rng.uniform(0, 400), round(rng.uniform(0, 20), 4)])
        e = round(rng.uniform(1.3, 3.0), 4)
        remembered = rng.random() < 0.5
        stable, ease = core.apply_answer(s, e, remembered)
        grid.append({"s": s, "e": e, "r": remembered, "out": [stable, ease]})
    dump("answer.json", {"cases": grid})


def probe_proficiency() -> None:
    points = [0.0, -1.0, 1e-9, 0.25, 0.5, 90.0, 390.0, 390.1, 1000.0]
    for index in range(5000):
        ratio = index / 4999
        points.append(0.25 * (1560.0 ** ratio))
    dump("proficiency.json", {
        "cases": [{"s": s, "out": core.proficiency_from_stability(s)} for s in points]
    })


def probe_schedule(words: list[dict]) -> None:
    core.words_data = words
    last_times = [w.get("last_review", 0) for w in words if w.get("last_review")]
    anchor = max(last_times)
    nows = [anchor, anchor + 3600, anchor + 86400, anchor + 7 * 86400,
            anchor + 30 * 86400, anchor + 365 * 86400]

    cases = []
    for now in nows:
        with FixedClock(now):
            due = []
            for word in words:
                if word["proficiency"] >= core.STD_PRO:
                    continue
                last = word.get("last_review", 0)
                if last and now - last < core.MIN_REVIEW_GAP_HOURS * 3600:
                    continue
                if core.overdue_ratio(word, now) >= core.DUE_THRESHOLD:
                    due.append(word)
            new_pool = [w for w in due if w.get("stability", 0) <= 0]
            review_pool = [w for w in due if w.get("stability", 0) > 0]
            weights = [max(0.01, min(core.overdue_ratio(w, now), core.LATENESS_CAP))
                       ** core.LATENESS_POWER for w in review_pool]

            picks = []
            original_module = core.random
            for u1, u2 in ((0.1, 0.1), (0.5, 0.5), (0.9, 0.9), (0.3, 0.77), (0.62, 0.41)):
                fake = FakeRandomModule([u1, u2])
                core.random = fake
                picked = core.pick_random_word(now)
                core.random = original_module
                picks.append({
                    "u": [u1, u2],
                    "en": None if picked is None else picked["en"],
                    "calls": list(fake.calls),
                })

            cases.append({
                "now": now,
                "due": [w["en"] for w in due],
                "newPool": [w["en"] for w in new_pool],
                "reviewPool": [w["en"] for w in review_pool],
                "weights": weights,
                "nextDue": core.next_due_seconds(now),
                "allFinish": core.all_word_finish(),
                "picks": picks,
            })
    dump("schedule.json", {"cases": cases})


def probe_status(words: list[dict]) -> None:
    if gui is None:
        return
    core.words_data = words
    last_times = [w.get("last_review", 0) for w in words if w.get("last_review")]
    anchor = max(last_times)
    samples = words[:60] + words[-60:]
    cases = []
    for now in (anchor, anchor + 86400):
        with FixedClock(now):
            for word in samples:
                cases.append({
                    "en": word["en"],
                    "now": now,
                    "status": gui.WordBookApp._word_status(None, word),
                    "nextText": gui.WordBookApp._next_review_text(None, word),
                })
    dump("status.json", {"cases": cases})


def probe_definition(words: list[dict]) -> None:
    if gui is None:
        return
    samples = [w["cn"] for w in words[:200]]
    cases = [{"text": text, "lines": gui._format_definition(text).split("\n")}
             for text in samples]
    dump("definition.json", {"cases": cases})


def probe_text() -> None:
    waits = [None, 0, 1, 59, 60, 61, 3599, 3600, 3661, 86399, 86400, 90061, 864000]
    format_wait = gui._format_wait if gui else core.format_wait
    if gui is None:
        waits = [w for w in waits if w is not None]
    greetings = []
    if gui is not None:
        from datetime import datetime as real_datetime

        class FakeDatetime(real_datetime):
            hour_fixed = 0

            @classmethod
            def now(cls, tz=None):
                return real_datetime(2026, 11, 3, cls.hour_fixed, 0, 0)

        original = gui.datetime
        gui.datetime = FakeDatetime
        try:
            for hour in range(24):
                FakeDatetime.hour_fixed = hour
                greetings.append({"hour": hour, "out": gui._greeting()})
        finally:
            gui.datetime = original
    dump("text.json", {
        "waits": [{"s": w, "out": format_wait(w)} for w in waits],
        "greetings": greetings,
    })


def probe_weekly() -> None:
    rows = []
    with open(SNAPSHOT / "word_record.csv", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if row:
                rows.append(row)
    sample = rows[-400:]
    case = {"rows": sample, "expected": {}}
    for offset in (0, 1, 7, 400):
        anchor = max(r[0] for r in sample if r and r[0])
        from datetime import datetime, timedelta
        day = datetime.strptime(anchor[:10], "%Y-%m-%d") - timedelta(days=offset)
        dates = [day - timedelta(days=i) for i in range(6, -1, -1)]
        keys = [d.strftime("%Y-%m-%d") for d in dates]
        counts = {}
        for row in sample:
            if row and row[0][:10] in keys:
                counts[row[0][:10]] = counts.get(row[0][:10], 0) + 1
        case["expected"][day.strftime("%Y-%m-%d")] = [
            [key, counts.get(key, 0)] for key in keys
        ]
    dump("weekly.json", {"cases": [case]})


def probe_normalize() -> None:
    """只覆盖不需要读写磁盘的路径：补 first_review、删废弃字段、清理顺序。
    含 stability/ease 的样本不会触发旧档迁移，避免写到真实存档。"""
    legacy = [
        {"en": "abandon", "cn": "vt. 放弃", "proficiency": 70,
         "last_review": 1700000000.0, "stability": 3.0, "ease": 2.5,
         "fail_count": 1, "success_count": 4},
        {"en": "beam", "cn": "n. 光束", "proficiency": 55, "last_review": 0,
         "first_review": 0, "fail_count": 2, "success_count": 3,
         "stability": 1.0, "ease": 2.0, "review_count": 5, "last_reduce": 1},
    ]
    payload = [dict(item) for item in legacy]
    core.words_data = payload
    original_save = core.save_words
    core.save_words = lambda: None
    try:
        core.normalize_words()
    finally:
        core.save_words = original_save
    dump("normalize.json", {"input": legacy, "out": payload})


def probe_fuzz() -> None:
    rng = random.Random(777)
    cases = []
    for _ in range(20000):
        s = rng.choice([0.0, rng.uniform(0, 400)])
        e = rng.uniform(1.3, 3.0)
        remembered = rng.random() < 0.5
        stable, ease = core.apply_answer(s, e, remembered)
        cases.append({"s": s, "e": e, "r": remembered, "out": [stable, ease],
                      "p": core.proficiency_from_stability(stable)})
    dump("fuzz.json", {"cases": cases})


def main() -> None:
    words = load_words()
    print(f"基准数据来源：_backup_before_web/words.json（{len(words)} 个词）")
    print("生成中……")
    probe_answer()
    probe_proficiency()
    probe_schedule(words)
    probe_status(words)
    probe_definition(words)
    probe_text()
    probe_weekly()
    probe_normalize()
    probe_fuzz()
    print("完成。")


if __name__ == "__main__":
    main()
