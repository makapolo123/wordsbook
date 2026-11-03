from __future__ import annotations

import csv
import ctypes
import re
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Iterable

import words_book as core


COLORS = {
    "background": "#F3F5F1",
    "sidebar": "#E9EDE6",
    "card": "#FFFFFF",
    "surface": "#F8FAF7",
    "text": "#1F2A23",
    "muted": "#707A72",
    "subtle": "#929B94",
    "border": "#DDE3DC",
    "accent": "#355F49",
    "accent_hover": "#294C3A",
    "accent_soft": "#DFEBE3",
    "accent_pale": "#EEF5F0",
    "warning": "#9A6A3A",
    "warning_soft": "#F4EBDD",
    "track": "#E8ECE7",
}


def _pick_font(root: tk.Misc) -> str:
    available = set(tkfont.families(root))
    for family in (
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "PingFang SC",
        "Noto Sans CJK SC",
        "Segoe UI",
        "Arial",
    ):
        if family in available:
            return family
    return "TkDefaultFont"


def _format_wait(seconds: float | None) -> str:
    if seconds is None:
        return "暂无安排"
    seconds = max(0, seconds)
    if seconds < 60:
        return "不到 1 分钟"
    if seconds < 3600:
        return f"{int(seconds // 60)} 分钟"
    if seconds < 86400:
        return f"{seconds / 3600:.1f} 小时"
    return f"{seconds / 86400:.1f} 天"


_POS_MARKER = re.compile(
    r"(?i)(?<![A-Za-z])"
    r"((?:n|v|vt|vi|a|adj|ad|adv|prep|conj|pron|num|art|int|aux|abbr|pl)\.)"
)
_POS_PREFIX = re.compile(
    r"(?i)^((?:n|v|vt|vi|a|adj|ad|adv|prep|conj|pron|num|art|int|aux|abbr|pl)\.)\s+"
)


def _keep_pos_with_meaning(part: str) -> str:
    # A non-breaking space prevents Tk from orphaning "vt." on its own line.
    return _POS_PREFIX.sub(lambda match: match.group(1) + "\u00A0", part, count=1)


def _format_definition(text: str) -> str:
    """Group shared POS labels and keep distinct meanings on separate lines."""
    text = text.strip()
    markers = list(_POS_MARKER.finditer(text))
    if len(markers) <= 1:
        return _keep_pos_with_meaning(text)

    groups = []
    current_group = [markers[0]]
    for marker in markers[1:]:
        between = text[current_group[-1].end() : marker.start()]
        if not between.strip(" /；;，,"):
            current_group.append(marker)
        else:
            groups.append(current_group)
            current_group = [marker]
    groups.append(current_group)

    parts = []
    prefix = text[: markers[0].start()].strip(" /；;，,")
    if prefix:
        parts.append(prefix)
    for index, group in enumerate(groups):
        end = (
            groups[index + 1][0].start()
            if index + 1 < len(groups)
            else len(text)
        )
        pos_labels = "/".join(marker.group(1) for marker in group)
        meaning = text[group[-1].end() : end].strip(" /；;，,")
        if meaning:
            parts.append(f"{pos_labels}\u00A0{meaning}")
        else:
            parts.append(pos_labels)
    return "\n".join(parts)


def _greeting() -> str:
    hour = datetime.now().hour
    if hour < 6:
        return "夜深了"
    if hour < 12:
        return "上午好"
    if hour < 18:
        return "下午好"
    return "晚上好"


class LinearMeter(tk.Canvas):
    def __init__(
        self,
        master: tk.Misc,
        *,
        background: str,
        fill: str,
        track: str,
        height: int = 8,
    ) -> None:
        super().__init__(
            master,
            width=1,
            height=height,
            bg=background,
            highlightthickness=0,
            bd=0,
        )
        self._fill = fill
        self._track = track
        self._value = 0.0
        self.bind("<Configure>", lambda _event: self._draw())

    def set(self, value: float) -> None:
        self._value = max(0.0, min(1.0, value))
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        self.create_rectangle(0, 0, width, height, fill=self._track, outline="")
        if self._value > 0:
            self.create_rectangle(
                0,
                0,
                max(2, width * self._value),
                height,
                fill=self._fill,
                outline="",
            )


class ProgressRing(tk.Canvas):
    def __init__(
        self,
        master: tk.Misc,
        *,
        background: str,
        accent: str,
        track: str,
        font_family: str,
    ) -> None:
        size = 148
        super().__init__(
            master,
            width=size,
            height=size,
            bg=background,
            highlightthickness=0,
            bd=0,
        )
        self._accent = accent
        self._track = track
        self._font_family = font_family
        self._progress = 0.0
        self.set(0)

    def set(self, progress: float, caption: str = "已掌握") -> None:
        self._progress = max(0.0, min(1.0, progress))
        self.delete("all")
        pad = 12
        box = (pad, pad, 148 - pad, 148 - pad)
        self.create_oval(
            *box,
            outline=self._track,
            width=10,
        )
        if self._progress > 0:
            self.create_arc(
                *box,
                start=90,
                extent=-359.9 * self._progress,
                style="arc",
                outline=self._accent,
                width=10,
            )
        self.create_text(
            74,
            65,
            text=f"{self._progress * 100:.1f}%",
            fill=COLORS["text"],
            font=(self._font_family, 19, "bold"),
        )
        self.create_text(
            74,
            91,
            text=caption,
            fill=COLORS["muted"],
            font=(self._font_family, 9),
        )


class WeeklyChart(tk.Canvas):
    def __init__(self, master: tk.Misc, font_family: str) -> None:
        super().__init__(
            master,
            width=1,
            height=100,
            bg=COLORS["card"],
            highlightthickness=0,
            bd=0,
        )
        self._font_family = font_family
        self._data: list[tuple[datetime, int]] = []
        self.bind("<Configure>", lambda _event: self._draw())

    def set_data(self, data: list[tuple[datetime, int]]) -> None:
        self._data = data
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        width = max(300, self.winfo_width())
        height = max(90, self.winfo_height())
        if not self._data:
            self.create_text(
                width / 2,
                height / 2,
                text="还没有复习记录",
                fill=COLORS["muted"],
                font=(self._font_family, 10),
            )
            return

        max_value = max((count for _, count in self._data), default=0)
        max_value = max(1, max_value)
        left = 12
        right = width - 12
        baseline = height - 30
        chart_top = 26
        chart_height = max(50, baseline - chart_top)
        slot = (right - left) / len(self._data)
        bar_width = min(34, slot * 0.48)

        self.create_line(
            left,
            baseline,
            right,
            baseline,
            fill=COLORS["border"],
            width=1,
        )
        for index, (date_value, count) in enumerate(self._data):
            center = left + slot * (index + 0.5)
            bar_height = 0 if count == 0 else max(4, chart_height * count / max_value)
            x1 = center - bar_width / 2
            x2 = center + bar_width / 2
            y1 = baseline - bar_height
            if count:
                self.create_rectangle(
                    x1,
                    y1,
                    x2,
                    baseline,
                    fill=COLORS["accent"],
                    outline="",
                )
                self.create_text(
                    center,
                    y1 - 10,
                    text=str(count),
                    fill=COLORS["text"],
                    font=(self._font_family, 9, "bold"),
                )
            self.create_text(
                center,
                baseline + 17,
                text=date_value.strftime("%m/%d"),
                fill=COLORS["muted"],
                font=(self._font_family, 8),
            )


class WordBookApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.font_family = _pick_font(root)
        self.page = "home"
        self.words: list[dict] = []
        self.current_word: dict | None = None
        self.revealed = False
        self.answer_processed = False
        self.last_result: str | None = None
        self.last_proficiency_change: tuple[int, int] | None = None
        self.session_start_time: float | None = None
        self.session_review_count = 0
        self.session_remembered_count = 0
        self.session_new_words = 0
        self.session_words: set[str] = set()
        self.session_finished = False
        self.nav_buttons: dict[str, tk.Button] = {}
        self.review_view: tk.Frame | None = None
        self.search_var = tk.StringVar()
        self.filter_var = tk.StringVar(value="全部单词")
        self.search_var.trace_add(
            "write",
            lambda *_args: self._refresh_word_rows(),
        )

        self.root.title("词间 · 单词记忆助手")
        self.root.configure(bg=COLORS["background"])
        self.root.minsize(1040, 760)
        self.root.geometry(self._centered_geometry(1180, 780))
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._configure_styles()
        core.load_words()
        self.words = core.words_data
        self._build_shell()
        self._refresh_sidebar()
        self.show_home()
        self.root.bind("<Key>", self._on_key)

    def _centered_geometry(self, width: int, height: int) -> str:
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2 - 20)
        return f"{width}x{height}+{x}+{y}"

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Word.Treeview",
            background=COLORS["card"],
            fieldbackground=COLORS["card"],
            foreground=COLORS["text"],
            borderwidth=0,
            relief="flat",
            rowheight=38,
            font=(self.font_family, 10),
        )
        style.configure(
            "Word.Treeview.Heading",
            background=COLORS["surface"],
            foreground=COLORS["muted"],
            borderwidth=0,
            relief="flat",
            padding=(10, 9),
            font=(self.font_family, 9, "bold"),
        )
        style.map(
            "Word.Treeview",
            background=[("selected", COLORS["accent_soft"])],
            foreground=[("selected", COLORS["accent"])],
        )
        style.map(
            "Word.Treeview.Heading",
            background=[("active", COLORS["surface"])],
        )
        style.configure(
            "Clean.Vertical.TScrollbar",
            background=COLORS["border"],
            troughcolor=COLORS["surface"],
            borderwidth=0,
            arrowsize=12,
        )
        style.configure(
            "Clean.TCombobox",
            fieldbackground=COLORS["card"],
            background=COLORS["card"],
            foreground=COLORS["text"],
            bordercolor=COLORS["border"],
            lightcolor=COLORS["border"],
            darkcolor=COLORS["border"],
            arrowcolor=COLORS["muted"],
            padding=(10, 8),
        )

    def _build_shell(self) -> None:
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, minsize=222)
        self.root.grid_columnconfigure(1, weight=1)

        self.sidebar = tk.Frame(
            self.root,
            width=222,
            bg=COLORS["sidebar"],
            bd=0,
            highlightthickness=0,
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        self.workspace = tk.Frame(self.root, bg=COLORS["background"])
        self.workspace.grid(row=0, column=1, sticky="nsew")
        self.content = tk.Frame(self.workspace, bg=COLORS["background"])
        self.content.pack(fill="both", expand=True)

        brand = tk.Frame(self.sidebar, bg=COLORS["sidebar"])
        brand.pack(fill="x", padx=22, pady=(27, 30))
        mark = tk.Canvas(
            brand,
            width=36,
            height=36,
            bg=COLORS["sidebar"],
            highlightthickness=0,
            bd=0,
        )
        mark.pack(side="left")
        mark.create_oval(2, 2, 34, 34, fill=COLORS["accent"], outline="")
        mark.create_text(
            18,
            18,
            text="词",
            fill="#FFFFFF",
            font=(self.font_family, 12, "bold"),
        )
        brand_text = tk.Frame(brand, bg=COLORS["sidebar"])
        brand_text.pack(side="left", padx=(10, 0))
        tk.Label(
            brand_text,
            text="词间",
            bg=COLORS["sidebar"],
            fg=COLORS["text"],
            font=(self.font_family, 16, "bold"),
        ).pack(anchor="w")
        tk.Label(
            brand_text,
            text="SPACED REVIEW",
            bg=COLORS["sidebar"],
            fg=COLORS["subtle"],
            font=(self.font_family, 7, "bold"),
        ).pack(anchor="w", pady=(1, 0))

        nav = tk.Frame(self.sidebar, bg=COLORS["sidebar"])
        nav.pack(fill="x", padx=13)
        nav_items = (
            ("home", "今日学习"),
            ("library", "单词库"),
            ("records", "学习记录"),
        )
        for key, label in nav_items:
            button = tk.Button(
                nav,
                text=label,
                command=lambda target=key: self._navigate(target),
                anchor="w",
                bg=COLORS["sidebar"],
                fg=COLORS["muted"],
                activebackground=COLORS["accent_soft"],
                activeforeground=COLORS["accent"],
                bd=0,
                relief="flat",
                font=(self.font_family, 10),
                padx=15,
                pady=12,
                cursor="hand2",
                highlightthickness=0,
            )
            button.pack(fill="x", pady=2)
            button.bind(
                "<Enter>",
                lambda _event, target=key: self._hover_nav(target, True),
            )
            button.bind(
                "<Leave>",
                lambda _event, target=key: self._hover_nav(target, False),
            )
            self.nav_buttons[key] = button

        summary = tk.Frame(
            self.sidebar,
            bg=COLORS["card"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
        )
        summary.pack(side="bottom", fill="x", padx=15, pady=18)
        summary_inner = tk.Frame(summary, bg=COLORS["card"])
        summary_inner.pack(fill="x", padx=15, pady=14)
        tk.Label(
            summary_inner,
            text="总体进度",
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=(self.font_family, 9, "bold"),
        ).pack(anchor="w")
        self.side_summary = tk.Label(
            summary_inner,
            text="",
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=(self.font_family, 9),
        )
        self.side_summary.pack(anchor="w", pady=(4, 9))
        self.side_meter = LinearMeter(
            summary_inner,
            background=COLORS["card"],
            fill=COLORS["accent"],
            track=COLORS["track"],
            height=7,
        )
        self.side_meter.pack(fill="x")
        self.side_due = tk.Label(
            summary_inner,
            text="",
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=(self.font_family, 9),
        )
        self.side_due.pack(anchor="w", pady=(9, 0))

    def _hover_nav(self, key: str, entering: bool) -> None:
        if key == self.page:
            return
        background = COLORS["accent_pale"] if entering else COLORS["sidebar"]
        self.nav_buttons[key].configure(bg=background)

    def _set_active_nav(self, active: str) -> None:
        for key, button in self.nav_buttons.items():
            if key == active:
                button.configure(
                    bg=COLORS["accent_soft"],
                    fg=COLORS["accent"],
                    font=(self.font_family, 10, "bold"),
                )
            else:
                button.configure(
                    bg=COLORS["sidebar"],
                    fg=COLORS["muted"],
                    font=(self.font_family, 10),
                )

    def _clear_content(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()

    def _primary_button(
        self,
        parent: tk.Misc,
        text: str,
        command: Callable[[], None],
    ) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=COLORS["accent"],
            fg="#FFFFFF",
            activebackground=COLORS["accent_hover"],
            activeforeground="#FFFFFF",
            bd=0,
            relief="flat",
            font=(self.font_family, 10, "bold"),
            padx=22,
            pady=11,
            cursor="hand2",
            highlightthickness=0,
        )
        button.bind(
            "<Enter>",
            lambda _event: button.configure(bg=COLORS["accent_hover"]),
        )
        button.bind(
            "<Leave>",
            lambda _event: button.configure(bg=COLORS["accent"]),
        )
        return button

    def _secondary_button(
        self,
        parent: tk.Misc,
        text: str,
        command: Callable[[], None],
    ) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=COLORS["accent_pale"],
            fg=COLORS["text"],
            activebackground=COLORS["accent_soft"],
            activeforeground=COLORS["accent"],
            bd=0,
            relief="flat",
            font=(self.font_family, 10),
            padx=20,
            pady=10,
            cursor="hand2",
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["accent"],
            highlightthickness=1,
        )
        button.bind(
            "<Enter>",
            lambda _event: button.configure(bg=COLORS["accent_soft"]),
        )
        button.bind(
            "<Leave>",
            lambda _event: button.configure(bg=COLORS["accent_pale"]),
        )
        return button

    def _surface(self, parent: tk.Misc) -> tk.Frame:
        return tk.Frame(
            parent,
            bg=COLORS["card"],
            bd=0,
            highlightbackground=COLORS["border"],
            highlightthickness=1,
        )

    def _page_header(
        self,
        title: str,
        subtitle: str,
        *,
        action_text: str | None = None,
        action_command: Callable[[], None] | None = None,
        action_secondary: bool = False,
    ) -> tk.Frame:
        header = tk.Frame(self.content, bg=COLORS["background"])
        header.pack(fill="x", padx=38, pady=(24, 16))
        text_wrap = tk.Frame(header, bg=COLORS["background"])
        text_wrap.pack(side="left")
        tk.Label(
            text_wrap,
            text=title,
            bg=COLORS["background"],
            fg=COLORS["text"],
            font=(self.font_family, 23, "bold"),
        ).pack(anchor="w")
        tk.Label(
            text_wrap,
            text=subtitle,
            bg=COLORS["background"],
            fg=COLORS["muted"],
            font=(self.font_family, 9),
        ).pack(anchor="w", pady=(5, 0))
        if action_text and action_command:
            if action_secondary:
                action = self._secondary_button(
                    header,
                    action_text,
                    action_command,
                )
            else:
                action = self._primary_button(
                    header,
                    action_text,
                    action_command,
                )
            action.pack(side="right", pady=4)
        return header

    def _navigate(self, target: str) -> None:
        if target == self.page:
            if target == "home":
                self.show_home()
            return
        if self.page == "review":
            self._finish_session()
        if target == "home":
            self.show_home()
        elif target == "library":
            self.show_library()
        elif target == "records":
            self.show_records()
        elif target == "review":
            self.show_review()

    def _refresh_sidebar(self) -> None:
        total = len(self.words)
        mastered = sum(1 for word in self.words if word.get("proficiency", 0) >= core.STD_PRO)
        due = self._due_count()
        self.side_summary.configure(text=f"{mastered} / {total} 已掌握")
        self.side_meter.set(mastered / total if total else 0)
        self.side_due.configure(text=f"{due} 个待复习")

    def _due_count(self) -> int:
        now = time.time()
        min_gap = core.MIN_REVIEW_GAP_HOURS * 3600
        count = 0
        for word in self.words:
            if word.get("proficiency", 0) >= core.STD_PRO:
                continue
            last = word.get("last_review", 0)
            if last and now - last < min_gap:
                continue
            if core.overdue_ratio(word, now) >= core.DUE_THRESHOLD:
                count += 1
        return count

    def show_home(self) -> None:
        self.page = "home"
        self._set_active_nav("home")
        self._refresh_sidebar()
        self._clear_content()

        today = datetime.now()
        weekday = "一二三四五六日"[today.weekday()]
        date_text = f"{today.year}年{today.month}月{today.day}日 · 周{weekday}"
        self._page_header(
            _greeting(),
            date_text,
            action_text="开始复习  →",
            action_command=lambda: self._navigate("review"),
        )

        total = len(self.words)
        mastered = sum(1 for word in self.words if word.get("proficiency", 0) >= core.STD_PRO)
        due = self._due_count()
        new_count = sum(
            1
            for word in self.words
            if word.get("proficiency", 0) < core.STD_PRO
            and word.get("stability", 0) <= 0
        )
        reviewed_words = [
            word
            for word in self.words
            if word.get("proficiency", 0) < 101
        ]
        average_proficiency = (
            round(sum(word.get("proficiency", core.MIN_PRO) for word in reviewed_words) / len(reviewed_words))
            if reviewed_words
            else 0
        )

        hero = self._surface(self.content)
        hero.pack(fill="x", padx=38)
        hero_inner = tk.Frame(hero, bg=COLORS["card"])
        hero_inner.pack(fill="both", expand=True, padx=34, pady=20)
        hero_inner.grid_columnconfigure(0, weight=1)

        left = tk.Frame(hero_inner, bg=COLORS["card"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 28))
        tk.Label(
            left,
            text="今日复习",
            bg=COLORS["card"],
            fg=COLORS["accent"],
            font=(self.font_family, 9, "bold"),
        ).pack(anchor="w")
        if due:
            headline = f"今天有 {due} 个单词待复习"
            description = "系统会优先安排临近遗忘的词。一次只专注一个词，完成后进度会自动保存。"
        elif total == 0:
            headline = "从导入第一组单词开始"
            description = "准备一个 TXT 词表，每行用英文和中文释义组成，即可开始自己的学习节奏。"
        elif mastered >= total:
            headline = "今天的单词已经全部掌握"
            description = "所有单词都已达到目标熟练度。你可以继续浏览词库，或导入新的学习内容。"
        else:
            next_wait = core.next_due_seconds()
            headline = "这一轮已经完成"
            description = f"最近一组单词预计在 {_format_wait(next_wait)}后到期，届时再来复习即可。"
        tk.Label(
            left,
            text=headline,
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=(self.font_family, 23, "bold"),
            wraplength=610,
            justify="left",
        ).pack(anchor="w", pady=(10, 8))
        tk.Label(
            left,
            text=description,
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=(self.font_family, 9),
            wraplength=590,
            justify="left",
        ).pack(anchor="w")

        stats = tk.Frame(left, bg=COLORS["card"])
        stats.pack(anchor="w", pady=(18, 0))
        self._inline_stat(stats, "已掌握", str(mastered), side="left")
        self._inline_divider(stats)
        self._inline_stat(stats, "平均熟练度", str(average_proficiency), side="left")
        self._inline_divider(stats)
        self._inline_stat(stats, "新词", str(new_count), side="left")

        ring = ProgressRing(
            hero_inner,
            background=COLORS["card"],
            accent=COLORS["accent"],
            track=COLORS["track"],
            font_family=self.font_family,
        )
        ring.grid(row=0, column=1, sticky="e")
        ring.set(mastered / total if total else 0)

        lower = tk.Frame(self.content, bg=COLORS["background"])
        lower.pack(fill="both", expand=True, padx=38, pady=(12, 20))
        lower.grid_columnconfigure(0, weight=3)
        lower.grid_columnconfigure(1, weight=2)
        lower.grid_rowconfigure(0, weight=1)

        distribution = self._surface(lower)
        distribution.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
        dist_inner = tk.Frame(distribution, bg=COLORS["card"])
        dist_inner.pack(fill="both", expand=True, padx=22, pady=14)
        self._card_title(dist_inner, "熟练度分布", "记忆强度换算后的当前区间")
        intervals = (
            ("入门", 50, 59),
            ("熟悉", 60, 69),
            ("掌握中", 70, 79),
            ("接近达标", 80, 100),
        )
        counts = []
        for label, low, high in intervals:
            count = sum(low <= word.get("proficiency", 0) <= high for word in self.words)
            counts.append(count)
        maximum = max(counts, default=0) or 1
        for (label, _low, _high), count in zip(intervals, counts):
            self._distribution_row(dist_inner, label, count, count / maximum)

        rhythm = self._surface(lower)
        rhythm.grid(row=0, column=1, sticky="nsew", padx=(9, 0))
        rhythm_inner = tk.Frame(rhythm, bg=COLORS["card"])
        rhythm_inner.pack(fill="both", expand=True, padx=22, pady=14)
        self._card_title(rhythm_inner, "学习节奏", "根据当前记忆强度计算")
        next_wait = core.next_due_seconds()
        self._detail_line(
            rhythm_inner,
            "待复习",
            f"{due} 个",
        )
        self._detail_line(
            rhythm_inner,
            "新词",
            f"{new_count} 个",
        )
        self._detail_line(
            rhythm_inner,
            "最近到期",
            "现在" if due else _format_wait(next_wait),
        )

    def _inline_stat(self, parent: tk.Misc, label: str, value: str, *, side: str) -> None:
        frame = tk.Frame(parent, bg=COLORS["card"])
        frame.pack(side=side, anchor="w")
        tk.Label(
            frame,
            text=value,
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=(self.font_family, 15, "bold"),
        ).pack(anchor="w")
        tk.Label(
            frame,
            text=label,
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=(self.font_family, 8),
        ).pack(anchor="w", pady=(2, 0))

    def _inline_divider(self, parent: tk.Misc) -> None:
        divider = tk.Frame(parent, width=1, height=36, bg=COLORS["border"])
        divider.pack(side="left", padx=24)
        divider.pack_propagate(False)

    def _card_title(self, parent: tk.Misc, title: str, subtitle: str) -> None:
        tk.Label(
            parent,
            text=title,
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=(self.font_family, 12, "bold"),
        ).pack(anchor="w")
        tk.Label(
            parent,
            text=subtitle,
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=(self.font_family, 8),
        ).pack(anchor="w", pady=(3, 10))

    def _distribution_row(
        self,
        parent: tk.Misc,
        label: str,
        count: int,
        ratio: float,
    ) -> None:
        row = tk.Frame(parent, bg=COLORS["card"])
        row.pack(fill="x", pady=1)
        tk.Label(
            row,
            text=label,
            width=9,
            anchor="w",
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=(self.font_family, 9),
        ).pack(side="left")
        meter = LinearMeter(
            row,
            background=COLORS["card"],
            fill=COLORS["accent"],
            track=COLORS["track"],
            height=7,
        )
        meter.pack(side="left", fill="x", expand=True, padx=(6, 12))
        meter.set(ratio)
        tk.Label(
            row,
            text=str(count),
            width=4,
            anchor="e",
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=(self.font_family, 9, "bold"),
        ).pack(side="right")

    def _detail_line(self, parent: tk.Misc, label: str, value: str) -> None:
        row = tk.Frame(parent, bg=COLORS["card"])
        row.pack(fill="x", pady=7)
        tk.Label(
            row,
            text=label,
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=(self.font_family, 9),
        ).pack(side="left")
        tk.Label(
            row,
            text=value,
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=(self.font_family, 9, "bold"),
        ).pack(side="right")

    def _definition_label(
        self,
        parent: tk.Misc,
        text: str,
        resize_source: tk.Misc,
    ) -> tk.Label:
        label = tk.Label(
            parent,
            text=text,
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=(self.font_family, 21),
            wraplength=760,
            justify="center",
        )
        resize_source.bind(
            "<Configure>",
            lambda event, target=label: target.configure(
                wraplength=max(320, event.width - 24)
            ),
            add="+",
        )
        return label

    def show_review(self) -> None:
        if self.page != "review":
            self.session_start_time = time.time()
            self.session_review_count = 0
            self.session_remembered_count = 0
            self.session_new_words = 0
            self.session_words = set()
            self.session_finished = False
        self.page = "review"
        self._set_active_nav("")
        self._clear_content()

        header = self._page_header(
            "专注复习",
            "每次只专注一个词",
            action_text="结束本轮",
            action_command=lambda: self._navigate("home"),
            action_secondary=True,
        )
        self.review_session_label = tk.Label(
            header,
            text="",
            bg=COLORS["background"],
            fg=COLORS["muted"],
            font=(self.font_family, 9),
        )
        self.review_session_label.pack(side="right", padx=(0, 12), pady=8)

        self.review_card = self._surface(self.content)
        self.review_card.pack(
            fill="both",
            expand=True,
            padx=38,
            pady=(0, 32),
        )
        self.review_body = tk.Frame(self.review_card, bg=COLORS["card"])
        self.review_body.pack(fill="both", expand=True, padx=40, pady=30)
        self.review_view = None
        self._load_next_word()

    def _session_subtitle(self) -> str:
        if self.session_review_count:
            return (
                f"本轮已复习 {self.session_review_count} 次 · "
                f"记住 {self.session_remembered_count} 次"
            )
        return "按记忆强度自动安排，随时可以结束"

    def _load_next_word(self) -> None:
        self.answer_processed = False
        self.revealed = False
        self.last_result = None
        self.last_proficiency_change = None
        self.current_word = core.pick_random_word()
        if self.current_word is None:
            self._render_review_empty()
        else:
            self._render_review_question()

    def _swap_review_view(self, new_view: tk.Frame) -> None:
        old_view = self.review_view
        self.review_view = new_view

        if old_view is None or not old_view.winfo_exists():
            new_view.place(x=20, y=0, relwidth=1, relheight=1)
            start_x = 20
            end_x = 0
            old_x_end = 0
        else:
            old_view.pack_forget()
            old_view.place(x=0, y=0, relwidth=1, relheight=1)
            new_view.place(x=22, y=0, relwidth=1, relheight=1)
            new_view.lift()
            start_x = 22
            end_x = 0
            old_x_end = -8

        steps = 9

        def animate(step: int = 0) -> None:
            if not new_view.winfo_exists():
                return
            progress = step / steps
            eased = 1 - (1 - progress) ** 3
            new_x = round(start_x * (1 - eased))
            new_view.place_configure(x=new_x)
            if (
                old_view is not None
                and old_view.winfo_exists()
            ):
                old_x = round(old_x_end * eased)
                old_view.place_configure(x=old_x)
            if step < steps:
                self.root.after(16, lambda: animate(step + 1))
                return
            new_view.place_forget()
            new_view.pack(fill="both", expand=True)
            if old_view is not None and old_view.winfo_exists():
                old_view.destroy()

        animate()

    def _render_review_question(self) -> None:
        word = self.current_word
        if word is None:
            return
        if hasattr(self, "review_session_label"):
            self.review_session_label.configure(text=self._session_subtitle())

        view = tk.Frame(self.review_body, bg=COLORS["card"])
        top = tk.Frame(view, bg=COLORS["card"])
        top.pack(fill="x")
        is_new = word.get("stability", 0) <= 0
        status_text = "新词" if is_new else "到期复习"
        status_bg = COLORS["warning_soft"] if is_new else COLORS["accent_soft"]
        status_fg = COLORS["warning"] if is_new else COLORS["accent"]
        tk.Label(
            top,
            text=status_text,
            bg=status_bg,
            fg=status_fg,
            font=(self.font_family, 8, "bold"),
            padx=10,
            pady=5,
        ).pack(side="left")
        tk.Label(
            top,
            text=f"熟练度 {word.get('proficiency', core.MIN_PRO)}",
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=(self.font_family, 9),
        ).pack(side="right")

        body = tk.Frame(view, bg=COLORS["card"])
        body.pack(fill="both", expand=True)
        center = tk.Frame(body, bg=COLORS["card"])
        center.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(
            center,
            text=word["en"],
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=(self.font_family, 40, "bold"),
            wraplength=720,
            justify="center",
        ).pack()
        definition_text = _format_definition(word["cn"])

        if not self.revealed:
            tk.Label(
                center,
                text="根据自己的记忆情况选择一个答案",
                bg=COLORS["card"],
                fg=COLORS["muted"],
                font=(self.font_family, 10),
            ).pack(pady=(28, 0))
            tk.Label(
                center,
                text="快捷键与选项序号一致",
                bg=COLORS["card"],
                fg=COLORS["subtle"],
                font=(self.font_family, 8),
            ).pack(pady=(14, 0))
            actions = tk.Frame(center, bg=COLORS["card"])
            actions.pack(pady=(54, 0))
            self._primary_button(
                actions,
                "1  认识",
                self._reveal_answer,
            ).pack(side="left", padx=6)
            self._secondary_button(
                actions,
                "2  不认识",
                lambda: self._record_answer("forgotten", advance=False),
            ).pack(side="left", padx=6)
        elif not self.answer_processed:
            tk.Frame(center, bg=COLORS["border"], height=1).pack(
                fill="x",
                padx=125,
                pady=(25, 25),
            )
            tk.Label(
                center,
                text="释义",
                bg=COLORS["card"],
                fg=COLORS["muted"],
                font=(self.font_family, 8, "bold"),
            ).pack()
            self._definition_label(
                center,
                definition_text,
                body,
            ).pack(pady=(12, 4))
            tk.Label(
                center,
                text="请选择后续操作",
                bg=COLORS["card"],
                fg=COLORS["muted"],
                font=(self.font_family, 9),
            ).pack(pady=(22, 0))
            actions = tk.Frame(center, bg=COLORS["card"])
            actions.pack(pady=(34, 0))
            self._primary_button(
                actions,
                "1  下一个",
                lambda: self._record_answer("remembered"),
            ).pack(side="left", padx=6)
            self._secondary_button(
                actions,
                "2  记错了",
                lambda: self._record_answer("forgotten"),
            ).pack(side="left", padx=6)
            self._secondary_button(
                actions,
                "3  记住了",
                lambda: self._record_answer("marked_remembered"),
            ).pack(side="left", padx=6)
            tk.Label(
                center,
                text="选择“记住了”后，这个词以后不再复习",
                bg=COLORS["card"],
                fg=COLORS["subtle"],
                font=(self.font_family, 8),
            ).pack(pady=(16, 0))
        else:
            tk.Frame(center, bg=COLORS["border"], height=1).pack(
                fill="x",
                padx=125,
                pady=(25, 25),
            )
            tk.Label(
                center,
                text="释义",
                bg=COLORS["card"],
                fg=COLORS["muted"],
                font=(self.font_family, 8, "bold"),
            ).pack()
            self._definition_label(
                center,
                definition_text,
                body,
            ).pack(pady=(12, 0))
            actions = tk.Frame(center, bg=COLORS["card"])
            actions.pack(pady=(44, 0))
            self._primary_button(
                actions,
                "下一个单词",
                self._load_next_word,
            ).pack()
        self._swap_review_view(view)

    def _reveal_answer(self) -> None:
        self.revealed = True
        self._render_review_question()

    def _record_answer(self, result: str, *, advance: bool = True) -> None:
        if self.current_word is None or self.answer_processed:
            return
        word = self.current_word
        initial_proficiency = word.get("proficiency", core.MIN_PRO)
        record_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        now = time.time()

        if result == "marked_remembered":
            word["proficiency"] = 101
        else:
            remembered = result == "remembered"
            word["stability"], word["ease"] = core.apply_answer(
                word.get("stability", 0),
                word.get("ease", core.EASE_DEFAULT),
                remembered,
            )
            word["proficiency"] = core.proficiency_from_stability(
                word["stability"]
            )

        if word.get("first_review", 0) == 0:
            self.session_new_words += 1
            word["first_review"] = now
        if result == "forgotten":
            word["fail_count"] = word.get("fail_count", 0) + 1
        else:
            word["success_count"] = word.get("success_count", 0) + 1

        word["last_review"] = now
        self.session_review_count += 1
        if result == "remembered":
            self.session_remembered_count += 1
        self.session_words.add(word["en"])
        self.last_result = result
        self.answer_processed = True
        self.revealed = True
        self.last_proficiency_change = (
            initial_proficiency,
            word["proficiency"],
        )

        try:
            core.word_record(
                [
                    record_time,
                    word["en"],
                    word["cn"],
                    initial_proficiency,
                    word["proficiency"],
                    result,
                ]
            )
            core.save_words()
        except OSError as error:
            messagebox.showerror(
                "保存失败",
                f"本次答题已保留在当前窗口中，但写入进度失败：\n{error}",
                parent=self.root,
            )
        self._refresh_sidebar()
        if advance:
            self._load_next_word()
        else:
            self._render_review_question()

    def _render_review_empty(self) -> None:
        if hasattr(self, "review_session_label"):
            self.review_session_label.configure(text=self._session_subtitle())
        view = tk.Frame(self.review_body, bg=COLORS["card"])
        center = tk.Frame(view, bg=COLORS["card"])
        center.pack(fill="both", expand=True)
        tk.Label(
            center,
            text="✓",
            bg=COLORS["card"],
            fg=COLORS["accent"],
            font=(self.font_family, 34, "bold"),
        ).pack(pady=(44, 14))
        if core.all_word_finish() and self.words:
            title = "所有单词都已达标"
            detail = "这一阶段的学习已经完成，可以导入新的词表继续前进。"
        elif self.session_review_count:
            title = "这一轮完成了"
            next_wait = core.next_due_seconds()
            detail = f"最近一组单词将在 {_format_wait(next_wait)}后到期。"
        else:
            title = "暂时没有到期单词"
            next_wait = core.next_due_seconds()
            detail = f"最近一组单词将在 {_format_wait(next_wait)}后到期。"
        tk.Label(
            center,
            text=title,
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=(self.font_family, 20, "bold"),
        ).pack()
        tk.Label(
            center,
            text=detail,
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=(self.font_family, 10),
        ).pack(pady=(8, 25))
        actions = tk.Frame(center, bg=COLORS["card"])
        actions.pack()
        self._secondary_button(
            actions,
            "查看单词库",
            lambda: self._navigate("library"),
        ).pack(side="left", padx=5)
        self._primary_button(
            actions,
            "回到首页",
            lambda: self._navigate("home"),
        ).pack(side="left", padx=5)
        self._swap_review_view(view)

    def _finish_session(self) -> None:
        if self.session_finished:
            return
        if (
            self.session_start_time is not None
            and self.session_review_count > 0
        ):
            try:
                core.statistic_data(
                    self.session_start_time,
                    time.time(),
                    self.session_review_count,
                    self.session_remembered_count,
                    self.session_words,
                    self.session_new_words,
                )
            except OSError:
                pass
        self.session_finished = True

    def show_library(self) -> None:
        self.page = "library"
        self._set_active_nav("library")
        self._refresh_sidebar()
        self._clear_content()

        self._page_header(
            "单词库",
            f"共 {len(self.words)} 个单词 · 查看、筛选或导入新的学习内容",
            action_text="导入 TXT",
            action_command=self._open_import_dialog,
        )

        toolbar = tk.Frame(self.content, bg=COLORS["background"])
        toolbar.pack(fill="x", padx=38, pady=(0, 14))
        search_wrap = tk.Frame(
            toolbar,
            bg=COLORS["card"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
        )
        search_wrap.pack(side="left", fill="x", expand=True, padx=(0, 10))
        tk.Label(
            search_wrap,
            text="搜索",
            bg=COLORS["card"],
            fg=COLORS["subtle"],
            font=(self.font_family, 9),
            padx=12,
        ).pack(side="left")
        search_entry = tk.Entry(
            search_wrap,
            textvariable=self.search_var,
            bg=COLORS["card"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat",
            bd=0,
            font=(self.font_family, 10),
        )
        search_entry.pack(side="left", fill="x", expand=True, padx=(0, 12), pady=10)
        search_entry.focus_set()
        filter_box = ttk.Combobox(
            toolbar,
            textvariable=self.filter_var,
            values=("全部单词", "待复习", "新词", "已掌握"),
            state="readonly",
            width=10,
            font=(self.font_family, 9),
            style="Clean.TCombobox",
        )
        filter_box.pack(side="right")
        self.library_count = tk.Label(
            toolbar,
            text="",
            bg=COLORS["background"],
            fg=COLORS["muted"],
            font=(self.font_family, 9),
        )
        self.library_count.pack(side="right", padx=(0, 16))

        table_shell = self._surface(self.content)
        table_shell.pack(fill="both", expand=True, padx=38, pady=(0, 30))
        table_shell.grid_rowconfigure(0, weight=1)
        table_shell.grid_columnconfigure(0, weight=1)
        columns = ("word", "meaning", "proficiency", "status", "next_review")
        self.word_tree = ttk.Treeview(
            table_shell,
            columns=columns,
            show="headings",
            style="Word.Treeview",
        )
        headings = {
            "word": "单词",
            "meaning": "释义",
            "proficiency": "熟练度",
            "status": "状态",
            "next_review": "下次复习",
        }
        widths = {
            "word": 160,
            "meaning": 290,
            "proficiency": 80,
            "status": 90,
            "next_review": 100,
        }
        for column in columns:
            self.word_tree.heading(column, text=headings[column], anchor="w")
            self.word_tree.column(
                column,
                width=widths[column],
                minwidth=70,
                stretch=column == "meaning",
                anchor="center" if column == "proficiency" else "w",
            )
        scrollbar = ttk.Scrollbar(
            table_shell,
            orient="vertical",
            command=self.word_tree.yview,
            style="Clean.Vertical.TScrollbar",
        )
        self.word_tree.configure(yscrollcommand=scrollbar.set)
        self.word_tree.grid(row=0, column=0, sticky="nsew", padx=(1, 0), pady=1)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 4), pady=4)
        self.word_tree.tag_configure("due", background="#FCFAF6")
        self.word_tree.tag_configure("mastered", foreground=COLORS["muted"])

        filter_box.bind("<<ComboboxSelected>>", lambda _event: self._refresh_word_rows())
        self._refresh_word_rows()

    def _refresh_word_rows(self) -> None:
        if not hasattr(self, "word_tree") or not self.word_tree.winfo_exists():
            return
        query = self.search_var.get().strip().lower()
        selected_filter = self.filter_var.get()
        rows = []
        for word in self.words:
            en = word.get("en", "")
            cn = word.get("cn", "")
            status = self._word_status(word)
            if query and query not in en.lower() and query not in cn.lower():
                continue
            if selected_filter == "待复习" and status not in ("待复习", "新词"):
                continue
            if selected_filter == "新词" and status != "新词":
                continue
            if selected_filter == "已掌握" and status not in ("已掌握", "已达标"):
                continue
            rows.append((word, status))
        rows.sort(key=lambda item: item[0].get("en", "").lower())
        self.word_tree.delete(*self.word_tree.get_children())
        for word, status in rows:
            tag = "mastered" if status in ("已掌握", "已达标") else ""
            if status in ("待复习", "新词"):
                tag = "due"
            self.word_tree.insert(
                "",
                "end",
                values=(
                    word.get("en", ""),
                    word.get("cn", ""),
                    word.get("proficiency", core.MIN_PRO),
                    status,
                    self._next_review_text(word),
                ),
                tags=(tag,) if tag else (),
            )
        self.library_count.configure(text=f"{len(rows)} 条记录")

    def _word_status(self, word: dict) -> str:
        proficiency = word.get("proficiency", 0)
        if proficiency >= 101:
            return "已掌握"
        if proficiency >= core.STD_PRO:
            return "已达标"
        if word.get("stability", 0) <= 0:
            return "新词"
        if core.overdue_ratio(word, time.time()) >= core.DUE_THRESHOLD:
            return "待复习"
        return "已排期"

    def _next_review_text(self, word: dict) -> str:
        proficiency = word.get("proficiency", 0)
        if proficiency >= 101:
            return "不再复习"
        if proficiency >= core.STD_PRO:
            return "已完成"
        stability = word.get("stability", 0)
        last_review = word.get("last_review", 0)
        if stability <= 0 or not last_review:
            return "等待首次学习"
        due_time = last_review + max(
            stability * 86400,
            core.MIN_REVIEW_GAP_HOURS * 3600,
        )
        seconds = due_time - time.time()
        if seconds <= 0:
            return "已到期"
        if seconds < 86400:
            return f"{seconds / 3600:.1f} 小时后"
        return f"{seconds / 86400:.1f} 天后"

    def _open_import_dialog(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="选择单词 TXT 文件",
            initialdir=str(core.BASE_DIR),
            filetypes=(("文本文件", "*.txt"), ("所有文件", "*.*")),
        )
        if not path:
            return
        before = len(self.words)
        core.import_txt(path)
        self.words = core.words_data
        added = len(self.words) - before
        self._refresh_sidebar()
        self._refresh_word_rows()
        if added:
            messagebox.showinfo(
                "导入完成",
                f"已新增 {added} 个单词。",
                parent=self.root,
            )
        else:
            messagebox.showinfo(
                "没有新增单词",
                "词表中没有可新增的内容。请检查文件格式是否为“英文, 中文”，以及单词是否重复。",
                parent=self.root,
            )

    def show_records(self) -> None:
        self.page = "records"
        self._set_active_nav("records")
        self._refresh_sidebar()
        self._clear_content()

        rows = self._read_record_rows()
        today_prefix = datetime.now().strftime("%Y-%m-%d")
        today_count = sum(row[0].startswith(today_prefix) for row in rows if row)
        remembered = sum(row[5].startswith("remembered") for row in rows if len(row) >= 6)
        forgotten = sum(row[5].startswith("forgotten") for row in rows if len(row) >= 6)
        judged = remembered + forgotten
        accuracy = remembered / judged * 100 if judged else 0

        self._page_header(
            "学习记录",
            "回看最近的复习节奏与答题情况",
        )
        stats = tk.Frame(self.content, bg=COLORS["background"])
        stats.pack(fill="x", padx=38, pady=(0, 16))
        for index, (label, value, note) in enumerate(
            (
                ("累计复习", f"{len(rows):,}", "次单词作答"),
                ("今日复习", f"{today_count:,}", "次单词作答"),
                ("记住率", f"{accuracy:.0f}%", "不含彻底掌握标记"),
            )
        ):
            stats.grid_columnconfigure(index, weight=1)
            card = self._surface(stats)
            card.grid(
                row=0,
                column=index,
                sticky="ew",
                padx=(0 if index == 0 else 7, 0 if index == 2 else 7),
            )
            inner = tk.Frame(card, bg=COLORS["card"])
            inner.pack(fill="x", padx=18, pady=15)
            tk.Label(
                inner,
                text=label,
                bg=COLORS["card"],
                fg=COLORS["muted"],
                font=(self.font_family, 8),
            ).pack(anchor="w")
            tk.Label(
                inner,
                text=value,
                bg=COLORS["card"],
                fg=COLORS["text"],
                font=(self.font_family, 18, "bold"),
            ).pack(anchor="w", pady=(3, 0))
            tk.Label(
                inner,
                text=note,
                bg=COLORS["card"],
                fg=COLORS["subtle"],
                font=(self.font_family, 8),
            ).pack(anchor="w", pady=(1, 0))

        chart_card = self._surface(self.content)
        chart_card.pack(fill="x", padx=38, pady=(0, 16))
        chart_inner = tk.Frame(chart_card, bg=COLORS["card"])
        chart_inner.pack(fill="x", padx=20, pady=(16, 10))
        tk.Label(
            chart_inner,
            text="近 7 天复习量",
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=(self.font_family, 11, "bold"),
        ).pack(anchor="w")
        chart = WeeklyChart(chart_inner, self.font_family)
        chart.pack(fill="x", expand=True, pady=(4, 0))
        chart.set_data(self._weekly_review_counts(rows))

        recent_card = self._surface(self.content)
        recent_card.pack(fill="both", expand=True, padx=38, pady=(0, 30))
        recent_card.grid_rowconfigure(1, weight=1)
        recent_card.grid_columnconfigure(0, weight=1)
        tk.Label(
            recent_card,
            text="最近复习",
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=(self.font_family, 11, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(15, 10))
        recent_tree = ttk.Treeview(
            recent_card,
            columns=("time", "word", "result", "change"),
            show="headings",
            style="Word.Treeview",
            height=4,
        )
        recent_tree.heading("time", text="时间", anchor="w")
        recent_tree.heading("word", text="单词", anchor="w")
        recent_tree.heading("result", text="结果", anchor="w")
        recent_tree.heading("change", text="熟练度", anchor="w")
        recent_tree.column("time", width=150, stretch=False)
        recent_tree.column("word", width=290, stretch=True)
        recent_tree.column("result", width=120, stretch=False)
        recent_tree.column("change", width=120, stretch=False)
        recent_tree.grid(row=1, column=0, sticky="nsew", padx=(1, 0), pady=(0, 1))
        scrollbar = ttk.Scrollbar(
            recent_card,
            orient="vertical",
            command=recent_tree.yview,
            style="Clean.Vertical.TScrollbar",
        )
        recent_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=1, column=1, sticky="ns", padx=(0, 4), pady=4)
        result_labels = {
            "remembered": "记住了",
            "forgotten": "没想起来",
            "marked_remembered": "记住了（不再复习）",
        }
        for row in reversed(rows[-30:]):
            if len(row) < 6:
                continue
            result = next(
                (
                    label
                    for key, label in result_labels.items()
                    if row[5].startswith(key)
                ),
                row[5],
            )
            try:
                change = f"{row[3]} → {row[4]}"
            except IndexError:
                change = ""
            recent_tree.insert(
                "",
                "end",
                values=(row[0][5:16], row[1], result, change),
            )

    def _read_record_rows(self) -> list[list[str]]:
        try:
            with open(
                core.RECORD_DATA_FILE,
                "r",
                newline="",
                encoding="utf-8",
            ) as file:
                reader = csv.reader(file)
                next(reader, None)
                return [row for row in reader if row]
        except (FileNotFoundError, OSError, UnicodeError):
            return []

    def _weekly_review_counts(
        self,
        rows: Iterable[list[str]],
    ) -> list[tuple[datetime, int]]:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        dates = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
        keys = [date.strftime("%Y-%m-%d") for date in dates]
        counts = Counter(row[0][:10] for row in rows if row and row[0][:10] in keys)
        return [(date, counts[key]) for date, key in zip(dates, keys)]

    def _on_key(self, event: tk.Event) -> None:
        if self.page != "review" or self.current_word is None:
            return
        key = event.keysym
        if self.answer_processed:
            if key in ("Return", "space"):
                self._load_next_word()
            return
        if not self.revealed:
            if key == "1":
                self._reveal_answer()
            elif key == "2":
                self._record_answer("forgotten", advance=False)
            return
        if key == "1":
            self._record_answer("remembered")
        elif key == "2":
            self._record_answer("forgotten")
        elif key == "3":
            self._record_answer("marked_remembered")

    def _on_close(self) -> None:
        if self.page == "review":
            self._finish_session()
        try:
            core.save_words()
        except OSError:
            pass
        self.root.destroy()


def launch_app() -> None:
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    WordBookApp(root)
    root.mainloop()


if __name__ == "__main__":
    launch_app()
