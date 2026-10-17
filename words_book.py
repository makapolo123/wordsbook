import csv
import json
import math
import random
import shutil
import time
from datetime import datetime

WORDS_SAVE_FILE = "words.json"         # 单词本地存档文件
STATISTIC_FILE = "statistic_data.txt"  # 复习数据文件
RECORD_DATA_FILE = "word_record.csv"   # 复习的单词数据

# ===== 熟练度参数 =====
STD_PRO = 90         # 达标熟练度（约对应 90 天记忆强度，即真正掌握）
MAX_PRO = 100        # 最大熟练度（对应记忆强度上限）
MIN_PRO = 50         # 最小熟练度（从未复习/刚答错）

# ===== 记忆强度（调度）参数 =====
MIN_STABILITY_DAYS = 0.25            # 记忆强度下限（约 6 小时），也是熟练度 50 的锚点
INIT_STABILITY_DAYS = 0.5            # 首次答对后的记忆强度（天）
MAX_STABILITY_DAYS = 390.0           # 记忆强度上限（天），对应熟练度 100
STABILITY_FAIL_FACTOR = 0.4          # 答错时记忆强度乘以该系数
EASE_DEFAULT = 2.5                   # 记忆增长系数初始值
EASE_MIN = 1.3                       # 增长系数下限（难记词）
EASE_MAX = 3.0                       # 增长系数上限
EASE_UP = 0.1                        # 答对时增长系数增加量
EASE_DOWN = 0.2                      # 答错时增长系数减少量
MIGRATE_MAX_STABILITY_DAYS = 14.0    # 旧存档迁移时记忆强度的上限

# ===== 抽取策略参数 =====
NEW_POOL_RATIO = 0.5             # 新词池抽取占比，剩余概率给复习池（0~1）
DUE_THRESHOLD = 1.0              # 逾期倍数达到该值才算到期（1 = 正好到计划复习时间）
MIN_REVIEW_GAP_HOURS = 12        # 同一个词两次抽取的最小间隔，避免当天反复抽到同一个词
LATENESS_CAP = 2.0               # 逾期倍数上限：超过后权重不再增加，保证到期词公平轮换
LATENESS_POWER = 2               # 逾期倍数权重指数，越大越偏向逾期久的词

words_data = []    # 单词列表

# 保存单词
def save_words():
    """将单词列表保存到本地json文件"""
    with open(WORDS_SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(words_data, f, ensure_ascii=False, indent=2)

# 加载单词
def load_words():
    """读取本地单词文件，无文件则初始化空单词列表"""
    global words_data
    try:
        with open(WORDS_SAVE_FILE, "r", encoding="utf-8") as f:
            words_data = json.load(f)
    except FileNotFoundError:
        words_data = []
    normalize_words()

# 存档字段校验与补齐
def normalize_words():
    """每次加载存档后执行：补齐缺失字段、清理废弃字段、按需回填历史并迁移旧存档。
    注意这不是一次性迁移，每次启动都会跑一遍；字段齐全时不做任何事。"""
    changed = False
    pending_backfill = []   # 只记录真正缺对错次数的词，避免重复累加
    legacy_words = []       # 还没有记忆强度字段的旧词，稍后统一迁移
    for word in words_data:
        if "first_review" not in word:
            # 旧存档无此字段，用最后复习时间兜底（0 表示从未复习）
            word["first_review"] = word.get("last_review", 0)
            changed = True
        if "last_reduce" in word:
            # 熟练度不再按天数扣分，该字段已废弃
            word.pop("last_reduce")
            changed = True
        if "review_count" in word:
            # 新词判定已改用 first_review == 0，该字段多余且与对错次数矛盾
            word.pop("review_count")
            changed = True
        if "fail_count" not in word or "success_count" not in word:
            # 首次出现对错次数，稍后从复习记录里回填历史
            word.setdefault("fail_count", 0)
            word.setdefault("success_count", 0)
            pending_backfill.append(word)
            changed = True
        if "stability" not in word or "ease" not in word:
            word.setdefault("stability", 0.0)
            word.setdefault("ease", EASE_DEFAULT)
            legacy_words.append(word)
            changed = True
    if pending_backfill:
        backfill_counts_from_record(pending_backfill)
    if legacy_words:
        migrate_stability(legacy_words)
    if changed:
        save_words()
        print("检测到旧版存档，已自动补齐字段并保存")

# 旧存档迁移：按历史复习顺序估算记忆强度
def migrate_stability(legacy_words):
    """把没有记忆强度的旧词一次性迁移到新模型：
    优先按 word_record.csv 的顺序回放对错序列，没有记录的词用对错次数估算。
    迁移前备份原存档，方便回退。"""
    print("检测到旧版存档，正在按历史复习记录迁移记忆强度...")
    try:
        shutil.copyfile(WORDS_SAVE_FILE, WORDS_SAVE_FILE + ".bak")
        print(f"已备份原存档：{WORDS_SAVE_FILE}.bak")
    except OSError as err:
        print("备份原存档失败：", err)

    sequences = read_history_sequences()
    replayed = 0
    for word in legacy_words:
        results = sequences.get(word["en"])
        if results:
            stability, ease = replay_results(results)
            replayed += 1
        else:
            stability, ease = estimate_stability(word)
        word["stability"] = round(stability, 4)
        word["ease"] = round(ease, 4)
        if word["proficiency"] != 101:
            word["proficiency"] = proficiency_from_stability(stability)
    print(f"已迁移 {len(legacy_words)} 个单词的记忆强度（其中 {replayed} 个来自复习记录）")

def read_history_sequences():
    """按文件顺序读取每个单词的历史对错序列（True 答对 / False 答错）"""
    sequences = {}
    try:
        with open(RECORD_DATA_FILE, "r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)   # 第一行是表头
            for row in reader:
                if len(row) < 6:
                    continue
                result = row[5].strip()
                if result.startswith("marked_remembered"):
                    continue
                if result.startswith("forgotten"):
                    sequences.setdefault(row[1].strip(), []).append(False)
                elif result.startswith("remembered"):
                    sequences.setdefault(row[1].strip(), []).append(True)
    except FileNotFoundError:
        pass
    except Exception as err:
        print("读取复习记录失败：", err)
    return sequences

def replay_results(results):
    """按对错序列回放，得到迁移用的记忆强度与增长系数"""
    stability = 0.0
    ease = EASE_DEFAULT
    for remembered in results:
        stability, ease = apply_answer(stability, ease, remembered)
    return min(stability, MIGRATE_MAX_STABILITY_DAYS), ease

def estimate_stability(word):
    """没有复习记录的旧词：按历史对错次数估算记忆强度"""
    successes = word.get("success_count", 0)
    fails = word.get("fail_count", 0)
    ease = max(EASE_MIN, min(EASE_MAX, EASE_DEFAULT + EASE_UP * successes - EASE_DOWN * fails))
    if successes == 0:
        return 0.0, ease
    # 用对数计算避免大指数溢出，超过迁移上限后结果必然被截断
    log_stability = successes * math.log(ease) + fails * math.log(STABILITY_FAIL_FACTOR)
    stability = math.exp(min(log_stability, 10.0))
    return min(stability, MIGRATE_MAX_STABILITY_DAYS), ease

# 从复习记录回填历史对错次数
def backfill_counts_from_record(words):
    """读取 word_record.csv，为传入的词统计它们历史答对/答错的次数。
    只处理缺少对错次数的词，避免对已有计数的词重复累加"""
    try:
        with open(RECORD_DATA_FILE, "r", newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))[1:]   # 第一行是表头
    except FileNotFoundError:
        return
    except Exception as err:
        print("回填历史对错次数失败：", err)
        return

    index = {word["en"]: word for word in words}
    filled = 0
    for row in rows:
        if len(row) < 6:
            continue
        word = index.get(row[1])
        if word is None:
            continue
        if row[5] == "forgotten":
            word["fail_count"] += 1
        else:
            word["success_count"] += 1
        filled += 1
    if filled:
        print(f"已从复习记录回填 {filled} 次历史结果")

# 导入单词
def import_txt(file_path):
    """导入txt单词文件（格式：英文, 中文\n）"""
    global words_data
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            words = f.readlines()

        # 已存在单词的集合只需构建一次，导入时同步加入新词避免文件内重复
        exists = {w["en"] for w in words_data}
        for word in words:
            word = word.strip()
            if not word or "," not in word:  # 跳过空行、没有逗号分隔的无效行
                continue
            # 割英文和中文
            eng, chn = word.split(",", 1)
            eng = eng.strip()
            chn = chn.strip()
            # 判断单词是否已经存在
            if eng not in exists:
                new_word = {
                    "en" : eng,
                    "cn" : chn,
                    "proficiency" : MIN_PRO,
                    "stability" : 0.0,          # 记忆强度（天），0 表示未复习
                    "ease" : EASE_DEFAULT,      # 记忆增长系数
                    "first_review":0,  # 首次复习时间
                    "last_review": 0,  # 最后复习时间
                    "fail_count" : 0,    # 答错次数
                    "success_count" : 0  # 答对次数
                }
                words_data.append(new_word)
                exists.add(eng)

        save_words()
        print("单词导入成功")
    except Exception as err:
        print("导入失败，错误：", err)

# 根据答对/答错更新记忆强度与增长系数
def apply_answer(stability, ease, remembered):
    """答对：记忆强度乘以增长系数（首次为初始强度）；答错：强度骤减并降低增长系数。
    增长系数会被答错拉低，难记词因此自动获得更短的间隔"""
    if remembered:
        stability = stability * ease if stability > 0 else INIT_STABILITY_DAYS
        ease = min(EASE_MAX, ease + EASE_UP)
    else:
        stability = max(MIN_STABILITY_DAYS, stability * STABILITY_FAIL_FACTOR)
        ease = max(EASE_MIN, ease - EASE_DOWN)
    return min(MAX_STABILITY_DAYS, stability), ease

# 记忆强度换算熟练度
def proficiency_from_stability(stability):
    """把记忆强度（天）换算成 50-100 的熟练度：对数映射，
    记忆强度约 90 天对应 90 分（达标），达到上限 390 天时为 100 分"""
    if stability <= 0:
        return MIN_PRO
    ratio = math.log(stability / MIN_STABILITY_DAYS) / math.log(MAX_STABILITY_DAYS / MIN_STABILITY_DAYS)
    return int(round(MIN_PRO + (MAX_PRO - MIN_PRO) * min(1.0, max(0.0, ratio))))

# 逾期倍数
def overdue_ratio(word, now):
    """距上次复习时间 / 记忆强度：1 表示刚好到了计划复习时间，2 表示已经超期一倍。
    从未复习的新词按上限处理（最高优先级）"""
    stability = word.get("stability", 0)
    last = word.get("last_review", 0)
    if stability <= 0 or not last:
        return LATENESS_CAP
    return max(0.0, (now - last) / (stability * 86400))

# 抽取单词
def pick_random_word(now=None):
    """分层加权抽取：先按固定比例在“新词池/复习池”之间选择，再在池内按逾期倍数加权。
    只从已到期的词里抽（逾期倍数 ≥ DUE_THRESHOLD），所以刚复习过的词在计划间隔内
    不会再次出现；没有到期词时返回 None，由调用方提示用户。
    池内权重 = min(逾期倍数, LATENESS_CAP) ** LATENESS_POWER：
    越拖延的词越容易被抽到；逾期倍数封顶后大家权重相同，因此到期词会公平轮换，
    不会让某几个词霸占所有抽取机会。
    所有单词放在同一个池子里比权重时，词数越多单个词的概率被稀释得越厉害，
    分层后新词和旧词各自保有固定份额，不受词库规模影响"""
    if now is None:
        now = time.time()

    # 已达标(>= STD_PRO 或 101)的词不再抽取，其余只保留已到期的词
    due_words = []
    min_gap = MIN_REVIEW_GAP_HOURS * 3600
    for word in words_data:
        if word["proficiency"] >= STD_PRO:
            continue
        last = word.get("last_review", 0)
        if last and now - last < min_gap:
            continue                          # 距上次抽取太近，避免当天反复抽到
        if overdue_ratio(word, now) >= DUE_THRESHOLD:
            due_words.append(word)
    if not due_words:
        return None   # 没有到期需要复习的单词

    new_pool = [word for word in due_words if word.get("stability", 0) <= 0]
    review_pool = [word for word in due_words if word.get("stability", 0) > 0]

    # 按固定比例选择池子；某个池为空时自动回退到另一个池
    if new_pool and (not review_pool or random.random() < NEW_POOL_RATIO):
        pool = new_pool
        weights = [1.0] * len(pool)
    else:
        pool = review_pool
        weights = [max(0.01, min(overdue_ratio(word, now), LATENESS_CAP)) ** LATENESS_POWER
                   for word in pool]
    return random.choices(pool, weights=weights, k=1)[0]

# 距离最近的单词到期还有多少秒
def next_due_seconds(now=None):
    """返回最近一个未达标词的到期等待时间（秒）；没有未达标词时返回 None"""
    if now is None:
        now = time.time()
    waits = []
    for word in words_data:
        if word["proficiency"] >= STD_PRO:
            continue
        stability = word.get("stability", 0)
        last = word.get("last_review", 0)
        if stability <= 0 or not last:
            return 0
        next_due = last + max(stability * 86400, MIN_REVIEW_GAP_HOURS * 3600)
        waits.append(next_due - now)
    if not waits:
        return None
    return max(0, min(waits))

# 把等待时间格式化成提示文字
def format_wait(seconds):
    if seconds < 3600:
        return f"{max(1, int(seconds // 60))} 分钟"
    if seconds < 86400:
        return f"{seconds / 3600:.1f} 小时"
    return f"{seconds / 86400:.1f} 天"

# 判断所有单词是否达标
def all_word_finish():
    """判断所有单词熟练度是否都超过STD_PRO"""
    for word in words_data:
        if word["proficiency"] < STD_PRO:
            return False
    return True

# 记录每次复习的数据
def statistic_data(start_time, end_time, review_counts, remember_counts, review_words, new_words):
    with open(STATISTIC_FILE, "a", encoding="utf-8") as f:
        start_text = datetime.fromtimestamp(start_time).strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"\n复习时间：{start_text}\n")
        review_time = int(end_time - start_time)
        f.write(f"用时：{int(review_time // 3600)}:{int(review_time % 3600 // 60)}:{int(review_time % 60)}\n")
        f.write(f"复习单词次数：{review_counts}\n")
        f.write(f"记住单词次数：{remember_counts}\n")
        f.write(f"复习单词数：{len(review_words)}\n")
        f.write(f"新单词数：{new_words}\n")
        f.write(f"正确率：{round((remember_counts / review_counts)*100, 2)}%\n")

# 复习的每个单词的情况
def word_record(word_record_data):
    with open(RECORD_DATA_FILE, "a+", newline="", encoding="utf-8") as f:
        f.seek(0)
        reader = csv.reader(f)
        # 第一行为表头
        first_row = next(reader, None)
        writer = csv.writer(f)
        if first_row is None:
            writer.writerow(["复习时间", "英文", "中文", "初始熟练度", "最终熟练度", "结果"])
        writer.writerows([word_record_data])


# 单词检测
def start_review():
    review_counts = 0    # 复习单词次数
    remember_counts = 0  # 记住单词次数
    new_words = 0        # 新单词数
    start_flag = False   # 开始复习标志
    review_words = set() # 复习的单词

    if len(words_data) == 0:
        print("暂无单词，请先导入单词！")
        return
    
    print("\n========== 单词背诵模式 ==========")
    print("操作指令：1=认识  2=不认识  0=退出背诵")

    while True:
        if all_word_finish():
            print("所有单词已达标！")
            break

        if not start_flag:
            start_time = time.time()  # 复习开始时间
        start_flag = True
        
        # 抽取单词：只抽已经到期的词
        current_word = pick_random_word()
        if current_word is None:
            wait = next_due_seconds()
            if wait is None:
                print("所有单词已达标！")
            else:
                print(f"当前没有到期需要复习的单词，最近的一个约 {format_wait(wait)} 后到期")
                print("稍后再来，或先导入新的单词。")
            break
        word_record_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S") # 单个单词复习时间
        initial_proficiency = current_word["proficiency"]

        print(f"\n[单词]{current_word['en']}")
        select = input("请输入你的选择：").strip()
        
        # ‘0’ 退出
        if select == '0':
            save_words()
            print("进度已保存，退出")
            break

        # '1' 认识
        elif select == '1':
            print(f"释义：{current_word['cn']}")
            next_act = input("操作指令：1=下一个  2=记错了  3=记住了：").strip()
            while True:
                # 记住了：记忆强度乘以增长系数（首次按初始强度）
                if next_act == '1':
                    remembered = True
                    remember_counts += 1
                    result = "remembered"
                    break
                # 记错了：记忆强度骤减，增长系数降低
                elif next_act == '2':
                    remembered = False
                    result = "forgotten"
                    break
                # 已经记牢了，将熟练度改为特殊值，后续不再出现
                elif next_act == '3':
                    current_word["proficiency"] = 101
                    result = "marked_remembered"
                    break
                else:
                    print("输入错误！请重新输入！")
                    next_act = input("操作指令：1=下一个  2=记错了  3=记住了：").strip()

        # '2' 不认识
        elif select == '2':
            print(f"释义：{current_word['cn']}")
            remembered = False
            result = "forgotten"

        else:
            print("输入错误!请重新输入！")
            continue

        # 更新记忆强度与熟练度（“记住了”只写特殊值 101，不参与计算）
        if result != "marked_remembered":
            current_word["stability"], current_word["ease"] = apply_answer(
                current_word.get("stability", 0),
                current_word.get("ease", EASE_DEFAULT),
                remembered,
            )
            current_word["proficiency"] = proficiency_from_stability(current_word["stability"])

        # 记录复习情况
        now = time.time()
        if current_word["first_review"] == 0:
            # 首次复习：记录首次复习时间，之后不再算作新词
            new_words += 1
            current_word["first_review"] = now
        # 累计对错次数，用于统计正确率
        if result == "forgotten":
            current_word["fail_count"] = current_word.get("fail_count", 0) + 1
        else:
            current_word["success_count"] = current_word.get("success_count", 0) + 1
        review_counts += 1
        review_words.add(current_word["en"])
        current_word["last_review"] = now
        final_proficiency = current_word["proficiency"]
        word_record([word_record_time, current_word["en"], current_word["cn"], initial_proficiency, final_proficiency, result])
        save_words()

    # 只要本次复习过单词就写入统计，无论正常退出、全部达标还是没有到期词
    if review_counts:
        statistic_data(start_time, time.time(), review_counts, remember_counts, review_words, new_words)

# 主菜单函数
def main_menu():
    load_words()
    while True:
        print("\n========== 单词记忆辅助程序 ==========")
        print("1. 导入单词txt文件")
        print("2. 开始背诵复习")
        print("3. 退出程序")
        choice = input("请选择功能序号：").strip()
        if choice == "1":
            file_path = input("请输入单词文件名称（例如 words.txt）：")
            import_txt(file_path)
        elif choice == "2":
            start_review()
        elif choice == "3":
            save_words()
            print("已保存所有进度，程序关闭！")
            break
        else:
            print("输入无效，请重新输入！")
            
if __name__ == "__main__":
    main_menu()