import csv
import json
import random
import time
from datetime import datetime

WORDS_SAVE_FILE = "words.json"         # 单词本地存档文件
STATISTIC_FILE = "statistic_data.txt"  # 复习数据文件
RECORD_DATA_FILE = "word_record.csv"   # 复习的单词数据
STD_PRO = 90       # 达标熟练度
MAX_PRO = 100        # 最大熟练度
MIN_PRO = 50         # 最小熟练度
ADD_POINT = 10       # 增加熟练度
SUB_POINT = 8        # 减少熟练度

# ===== 抽取策略参数 =====
NEW_POOL_RATIO = 0.5        # 新词池抽取占比，剩余概率给复习池（0~1）
WEIGHT_POWER = 3            # 熟练度权重指数，越大越偏向低熟练度的词
COOLDOWN_MIN_HOURS = 0.25   # 最低复习间隔（小时），对应最低熟练度
COOLDOWN_MAX_HOURS = 24.0   # 最高复习间隔（小时），对应最高熟练度
OVERDUE_FLOOR = 0.05        # 刚复习过的词的权重系数下限
OVERDUE_CAP = 3.0           # 逾期很久的词的权重系数上限

# ===== 难记词加成参数 =====
HARD_RATE_THRESHOLD = 0.25  # 错误率低于该值不算难记词，权重不受影响
HARD_BOOST = 10.0           # 错误率每超出阈值 0.05，权重就多 0.5 倍
HARD_CAP = 4.0              # 难记加成倍率的上限
HARD_MIN_REVIEWS = 4        # 复习次数少于该值不做难记判定

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
    migrate_data()

# 旧存档字段补齐
def migrate_data():
    """为旧版存档补齐缺失字段，保证后续逻辑使用的字段统一存在"""
    changed = False
    need_backfill = False
    for word in words_data:
        if "first_review" not in word:
            # 旧存档无此字段，用最后复习时间兜底（0 表示从未复习）
            word["first_review"] = word.get("last_review", 0)
            changed = True
        if "last_reduce" not in word:
            word["last_reduce"] = 0
            changed = True
        if "review_count" not in word:
            # 已复习过的词至少记为 1 次
            word["review_count"] = 1 if word.get("last_review", 0) else 0
            changed = True
        if "fail_count" not in word or "success_count" not in word:
            # 首次出现对错次数，稍后从复习记录里回填历史
            word.setdefault("fail_count", 0)
            word.setdefault("success_count", 0)
            need_backfill = True
            changed = True
    if need_backfill:
        backfill_counts_from_record()
    if changed:
        save_words()
        print("检测到旧版存档，已自动补齐字段并保存")

# 从复习记录回填历史对错次数
def backfill_counts_from_record():
    """读取 word_record.csv，统计每个词历史答对/答错的次数，
    让难记词加成在功能上线当天就能生效"""
    try:
        with open(RECORD_DATA_FILE, "r", newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))[1:]   # 第一行是表头
    except FileNotFoundError:
        return
    except Exception as err:
        print("回填历史对错次数失败：", err)
        return

    index = {word["en"]: word for word in words_data}
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
                    "proficiency" : 50,
                    "first_review":0,  # 首次复习时间
                    "last_review": 0,  # 最后复习时间
                    "last_reduce" : 0,   # 上次减少的熟练度
                    "review_count" : 0,  # 复习次数，0 表示新词
                    "fail_count" : 0,    # 答错次数
                    "success_count" : 0  # 答对次数
                }
                words_data.append(new_word)
                exists.add(eng)

        save_words()
        print("单词导入成功")
    except Exception as err:
        print("导入失败，错误：", err)

# 冷却复习时间
def get_cooldown(proficiency):
    """复习时间间隔（秒）：熟练度越高间隔越长，
    从 COOLDOWN_MIN_HOURS 指数增长到 COOLDOWN_MAX_HOURS"""
    ratio = (proficiency - MIN_PRO) / (MAX_PRO - MIN_PRO)
    ratio = min(1.0, max(0.0, ratio))   # 防止熟练度越界导致比值异常
    base_hours = COOLDOWN_MIN_HOURS * (COOLDOWN_MAX_HOURS / COOLDOWN_MIN_HOURS) ** ratio
    jitter = random.uniform(0.9, 1.1)    # 加入 ±10% 的随机抖动
    return int(base_hours * 3600 * jitter)

# 熟练度遗忘衰减
def forgetting_reduce():
    """根据距离上次复习的时间，自然降低熟练度"""
    now = time.time()
    for word in words_data:
        last = word.get("last_review", 0)
        if last == 0 or word["proficiency"] == 101:
            continue
        reduce = int(max(0, (now - last) // 86400 * 2 - 1))     # 随着时间间隔变长而减少相应的熟练度
        if reduce > word["last_reduce"]:
            word["proficiency"] = int(max(MIN_PRO, word["proficiency"] - reduce))
            word["last_reduce"] = reduce

# 达标的新单词熟练度减少
def new_word_reduce():
    now = time.time()
    for word in words_data:
        if word.get("first_review"):
            if now - word["first_review"] <= 86400 and STD_PRO <= word["proficiency"] <= MAX_PRO: # 新单词复习时间少于1天且熟练度达标
                word["proficiency"] = int(STD_PRO - 0.8 * ADD_POINT)

# 计算单词的“难记”加成倍率
def word_difficulty(word):
    """错误率越高说明越难记住，权重倍率越大；
    错误率低于 HARD_RATE_THRESHOLD 的词不受影响（倍率保持 1）"""
    total = word.get("fail_count", 0) + word.get("success_count", 0)
    if total < HARD_MIN_REVIEWS:
        return 1.0   # 复习次数太少，不足以判定是否难记
    fail_rate = word.get("fail_count", 0) / total
    excess = max(0.0, fail_rate - HARD_RATE_THRESHOLD)
    return min(HARD_CAP, 1.0 + HARD_BOOST * excess)

# 计算单个单词的抽取权重
def word_weight(word, now):
    """熟练度越低权重越大，并叠加“超期未复习”和“难记程度”的加成"""
    weight = (MAX_PRO - word["proficiency"]) ** WEIGHT_POWER
    weight *= word_difficulty(word)

    cooldown = get_cooldown(word["proficiency"])
    last = word.get("last_review", 0) or word.get("first_review", 0)
    if last and cooldown > 0:
        overdue = (now - last) / cooldown
    else:
        # 从未复习过的词按最高优先级处理
        overdue = OVERDUE_CAP

    # 软冷却：刚复习过的词权重被压低，逾期越久权重越高（封顶）
    return weight * min(OVERDUE_CAP, max(OVERDUE_FLOOR, overdue))

# 抽取单词
def pick_random_word():
    """分层加权抽取：先按固定比例在“新词池/复习池”之间选择，再在池内按权重抽取。
    所有单词放在同一个池子里比权重时，词数越多单个词的概率被稀释得越厉害，
    分层后新词和旧词各自保有固定份额，不受词库规模影响"""
    now = time.time()

    # 从未复习过的是新词，其余是待复习的旧词；已达标(>= STD_PRO 或 101)的词不参与
    new_pool = []
    review_pool = []
    for word in words_data:
        if word["proficiency"] >= STD_PRO:
            continue
        if word.get("review_count", 0) == 0:
            new_pool.append(word)
        else:
            review_pool.append(word)

    # 按固定比例选择池子；某个池为空时自动回退到另一个池
    if new_pool and (not review_pool or random.random() < NEW_POOL_RATIO):
        pool = new_pool
    elif review_pool:
        pool = review_pool
    else:
        return None  # 已无未达标的单词

    weights = [word_weight(word, now) for word in pool]
    return random.choices(pool, weights=weights, k=1)[0]

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
        forgetting_reduce()
        new_word_reduce()
        if all_word_finish():
            print("所有单词已达标！")
            break

        if not start_flag:
            start_time = time.time()  # 复习开始时间
        start_flag = True
        
        # 抽取单词
        current_word = pick_random_word()
        if current_word is None:  # 兜底：已无未达标的单词
            print("所有单词已达标！")
            break
        word_record_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S") # 单个单词复习时间
        initial_proficiency = current_word["proficiency"]

        print(f"\n[单词]{current_word['en']}")
        select = input("请输入你的选择：").strip()
        
        # ‘0’ 退出
        if select == '0':
            end_time = time.time()  # 复习结束时间
            statistic_data(start_time, end_time, review_counts, remember_counts,review_words, new_words)
            save_words()
            print("进度已保存，退出")
            break

        # '1' 认识
        elif select == '1':
            print(f"释义：{current_word['cn']}")
            next_act = input("操作指令：1=下一个  2=记错了  3=记住了：").strip()
            while True:
                # 熟练度增加，最高不能超过MAX_PRO
                if next_act == '1':
                    current_word["proficiency"] = int(min(MAX_PRO, current_word["proficiency"] + ADD_POINT))
                    remember_counts += 1
                    result = "remembered"
                    break
                # 熟练度减少，最低不能小于MIN_PRO
                elif next_act == '2':
                    current_word["proficiency"] = int(max(MIN_PRO, current_word["proficiency"] - SUB_POINT))
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
            # 熟练度减少，最低不能小于MIN_PRO
            current_word["proficiency"] = int(max(MIN_PRO, current_word["proficiency"] - SUB_POINT))
            result = "forgotten"

        else:
            print("输入错误!请重新输入！")
            continue

        # 记录复习情况
        now = time.time()
        if current_word["last_review"] == 0:
            new_words += 1
            current_word["first_review"] = now
        # 累计复习次数，首次复习后不再算作新词
        current_word["review_count"] = current_word.get("review_count", 0) + 1
        # 累计对错次数，用于识别难记词
        if result == "forgotten":
            current_word["fail_count"] = current_word.get("fail_count", 0) + 1
        else:
            current_word["success_count"] = current_word.get("success_count", 0) + 1
        review_counts += 1
        review_words.add(current_word["en"])
        current_word["last_review"] = now
        final_proficiency = current_word["proficiency"]
        word_record([word_record_time, current_word["en"], current_word["cn"], initial_proficiency, final_proficiency, result])
        # 减少的熟练度归零
        current_word["last_reduce"] = 0
        save_words()

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