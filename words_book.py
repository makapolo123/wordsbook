import json
import random
import time

SAVE_FILE = "words.json"
STD_SCORE = 90       # 达标熟练度
MAX_PRO = 100        # 最大熟练度
MIN_PRO = 50         # 最小熟练度
ADD_POINT = 10       # 增加熟练度
SUB_POINT = 8        # 减少熟练度

words_data = []   # 单词列表

# 保存单词
def save_words():
    """将单词列表保存到本地json文件"""
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(words_data, f, ensure_ascii=False, indent=2)

# 加载单词
def load_words():
    """读取本地单词文件，无文件则初始化空单词列表"""
    global words_data
    try:
        with open(SAVE_FILE, "r", encoding="utf-8") as f:
            words_data = json.load(f)
    except FileNotFoundError:
        words_data = []

# 导入单词
def import_txt(file_path):
    """导入txt单词文件（格式：英文，中文\n）"""
    global words_data
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            words = f.readlines()

        for word in words:
            word = word.strip()
            if not word or "," not in word:  # 跳过空行、没有逗号分隔的无效行
                continue
            # 割英文和中文
            eng, chn = word.split(",", 1)
            eng = eng.strip()
            chn = chn.strip()
            # 判断单词是否已经存在
            exists = {w["en"] for w in words_data}
            if eng not in exists:
                new_word = {
                    "en" : eng,
                    "cn" : chn,
                    "proficiency" : 50,
                    "last_review": 0  # 新增：最后复习时间
                }
                words_data.append(new_word)

        save_words()
        print("单词导入成功")
    except Exception as err:
        print("导入失败，错误：", err)

def get_cooldown(proficiency):
    base_time = (proficiency / 100) * 900 - 330
    # 加入 ±20% 的随机抖动
    jitter = random.uniform(0.8, 1.2)
    return int(base_time * jitter)

# 抽取单词
def pick_random_word():
    """根据复习时间间隔和熟练度加权随机抽取单词，复习时间间隔长的，熟练度越低越容易出现"""
    now = time.time()
    # 优先从未达标和长时间没复习的词中抽
    candidates = [
        word for word in words_data
        if word["proficiency"] < STD_SCORE
        and now - word.get("last_review", 0) > get_cooldown(word["proficiency"])
    ]
    if candidates:
        weight_list = []
        for word in candidates:
            # 熟练度越低，权重越大
            weight = max(0, MAX_PRO - word["proficiency"])
            weight_list.append(weight)
        # 按权重抽取1个单词
        target_word = random.choices(candidates, weights=weight_list, k=1)[0]
        return target_word
    return random.choice(words_data)

# 判断所有单词是否达标
def all_word_finish():
    """判断所有单词熟练度是否都超过STD_SCORE"""
    for word in words_data:
        if word["proficiency"] < STD_SCORE:
            return False
    return True

# 单词检测
def start_review():
    if len(words_data) == 0:
        print("暂无单词，请先导入单词！")
        return
    
    print("\n========== 单词背诵模式 ==========")
    print("操作指令：1=认识  2=不认识  0=退出背诵")

    while True:
        if all_word_finish():
            print("所有单词已达标！")
            break

        # 抽取单词
        current_word = pick_random_word()
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
                # 熟练度增加，最高不能超过MAX_PRO
                if next_act == '1':
                    current_word["proficiency"] = min(MAX_PRO, current_word["proficiency"] + ADD_POINT)
                    break
                # 熟练度减少，最低不能小于MIN_PRO
                elif next_act == '2':
                    current_word["proficiency"] = max(MIN_PRO, current_word["proficiency"] - SUB_POINT)
                    break
                # 已经记牢了，直接将熟练度改为达标值，后续不再出现
                elif next_act == '3':
                    current_word["proficiency"] = STD_SCORE
                    break
                else:
                    print("输入错误！请重新输入！")
                    next_act = input("操作指令：1=下一个  2=记错了  3=记住了：").strip()

        # '2' 不认识
        elif select == '2':
            print(f"释义：{current_word['cn']}")
            # 熟练度减少，最低不能小于MIN_PRO
            current_word["proficiency"] = max(MIN_PRO, current_word["proficiency"] - SUB_POINT)

        else:
            print("输入错误!请重新输入！")
            continue
        # 记录复习时间
        current_word["last_review"] = time.time()
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