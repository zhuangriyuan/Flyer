"""
超市生鲜食品 英->中 词典 + 翻译函数。

不是真正的机器翻译，是"短语/单词替换"：先匹配长短语（比如 "new zealand" ->
"新西兰"），再逐词替换剩下的部分（比如 "lamb" -> "羊肉"）。翻不出来的词
（品牌名、生僻词）保留英文原样，混在结果里。

好处：完全离线、不依赖任何网络请求、不会失败、可以随时扩充词条。
坏处：不是通顺的中文句子，是"关键词拼接"，但对搜索场景够用 ——
核心目的是让搜"羊肉"能搜到"New Zealand Lamb Shoulder Blade Chop"这种商品。

用法：
    from zh_dictionary import translate_name
    zh_name = translate_name("New Zealand Lamb Shoulder Blade Chop")
    # -> "新西兰 羊肉 肩 扒"
"""

import re

# 多词短语，优先匹配（越长越先匹配，避免被拆碎），大小写不敏感。
PHRASE_DICT = {
    "new zealand": "新西兰",
    "bell pepper": "灯笼椒",
    "black pepper": "黑胡椒",
    "olive oil": "橄榄油",
    "ground beef": "牛肉碎",
    "chicken breast": "鸡胸肉",
    "chicken thigh": "鸡腿肉",
    "chicken wing": "鸡翅",
    "pork belly": "五花肉",
    "pork chop": "猪扒",
    "spring water": "矿泉水",
    "sea salt": "海盐",
    "bok choy": "小白菜",
    "green onion": "青葱",
    "sweet potato": "红薯",
    "brown rice": "糙米",
    "whole wheat": "全麦",
    "peanut butter": "花生酱",
    "almond butter": "杏仁酱",
    "ice cream": "冰淇淋",
    "greek yogurt": "希腊酸奶",
    "soy sauce": "酱油",
    "hot dog": "热狗",
    "coffee filter": "咖啡滤纸",
    "hot sauce": "辣酱",
    "bbq sauce": "烧烤酱",
    "chili sauce": "辣椒酱",
    "baking soda": "小苏打",
    "baking powder": "泡打粉",
    "sour cream": "酸奶油",
    "cottage cheese": "茅屋芝士",
    "whipping cream": "淡奶油",
    "condensed milk": "炼乳",
    "evaporated milk": "淡奶",
    "brussels sprout": "抱子甘蓝",
    "energy drink": "能量饮料",
    "sports drink": "运动饮料",
    "ginger ale": "姜汁汽水",
    "root beer": "根汁汽水",
    "trail mix": "什锦果仁",
    "paper towel": "厨房纸巾",
    "toilet paper": "卫生纸",
    "garbage bag": "垃圾袋",
    "trash bag": "垃圾袋",
    "plastic wrap": "保鲜膜",
    "aluminum foil": "锡纸",
    "dish soap": "洗洁精",
    "hand soap": "洗手液",
    "fabric softener": "衣物柔顺剂",
    "gluten free": "无麸质",
    "dairy free": "无乳制品",
    "sugar free": "无糖",
    "plant based": "植物基",
}

# 单词词典，覆盖常见肉类/海鲜/蔬果/乳制品/主食/调味品/零食/饮料/部位与修饰词。
WORD_DICT = {
    # 肉类
    "meat": "肉", "beef": "牛肉", "chicken": "鸡肉", "pork": "猪肉",
    "turkey": "火鸡肉", "ham": "火腿", "sausage": "香肠", "sausages": "香肠",
    "bacon": "培根", "lamb": "羊肉", "veal": "小牛肉", "poultry": "禽肉",
    "salami": "萨拉米", "pepperoni": "意式辣香肠", "prosciutto": "意式火腿",
    "pastrami": "烟熏牛肉", "chorizo": "香辣肠", "mince": "肉碎",
    "burger": "汉堡肉", "burgers": "汉堡肉", "meatball": "肉丸",
    "meatballs": "肉丸", "drumstick": "鸡腿", "drumsticks": "鸡腿",
    # 部位/切法（很多肉类共用）
    "shoulder": "肩", "blade": "板", "chop": "扒", "chops": "扒",
    "cutlet": "肉排", "cutlets": "肉排", "fillet": "菲力", "filet": "菲力",
    "loin": "里脊", "sirloin": "西冷", "tenderloin": "嫩肩",
    "rack": "肋排架", "brisket": "牛胸肉", "shank": "小腿肉",
    "wing": "翅", "wings": "翅", "thigh": "腿", "thighs": "腿",
    "breast": "胸", "breasts": "胸", "steak": "牛排", "ribs": "排骨",
    "leg": "腿", "boneless": "去骨", "skinless": "去皮",
    # 海鲜
    "fish": "鱼", "salmon": "三文鱼", "shrimp": "虾", "seafood": "海鲜",
    "tuna": "金枪鱼", "tilapia": "罗非鱼", "cod": "鳕鱼", "squid": "鱿鱼",
    "scallop": "带子", "scallops": "带子", "crab": "蟹", "lobster": "龙虾",
    "trout": "鳟鱼", "halibut": "大比目鱼", "mussel": "青口", "mussels": "青口",
    "sole": "龙脷鱼", "snapper": "红鲷鱼", "oyster": "生蚝", "oysters": "生蚝",
    "clam": "蛤蜊", "clams": "蛤蜊",
    # 蔬菜
    "vegetable": "蔬菜", "vegetables": "蔬菜", "lettuce": "生菜",
    "broccoli": "西兰花", "carrot": "胡萝卜", "carrots": "胡萝卜",
    "onion": "洋葱", "onions": "洋葱", "pepper": "椒", "peppers": "椒",
    "cabbage": "卷心菜", "spinach": "菠菜", "cucumber": "黄瓜",
    "cucumbers": "黄瓜", "tomato": "番茄", "tomatoes": "番茄",
    "potato": "土豆", "potatoes": "土豆", "mushroom": "蘑菇",
    "mushrooms": "蘑菇", "zucchini": "西葫芦", "eggplant": "茄子",
    "cauliflower": "花椰菜", "bean": "豆", "beans": "豆", "corn": "玉米",
    "kale": "羽衣甘蓝", "celery": "芹菜", "leek": "韭葱", "leeks": "韭葱",
    "squash": "南瓜", "asparagus": "芦笋", "garlic": "大蒜", "ginger": "姜",
    "scallion": "香葱", "scallions": "香葱", "sprout": "芽", "sprouts": "芽",
    # 水果
    "fruit": "水果", "fruits": "水果", "berry": "莓", "berries": "莓",
    "blueberry": "蓝莓", "blueberries": "蓝莓", "strawberry": "草莓",
    "strawberries": "草莓", "raspberry": "覆盆子", "raspberries": "覆盆子",
    "apple": "苹果", "apples": "苹果", "banana": "香蕉", "bananas": "香蕉",
    "grape": "葡萄", "grapes": "葡萄", "melon": "瓜", "peach": "桃",
    "peaches": "桃", "orange": "橙", "oranges": "橙", "mango": "芒果",
    "mangoes": "芒果", "pear": "梨", "pears": "梨", "avocado": "牛油果",
    "avocados": "牛油果", "kiwi": "奇异果", "plum": "李子", "plums": "李子",
    "cherry": "樱桃", "cherries": "樱桃", "clementine": "小柑橘",
    "clementines": "小柑橘", "lemon": "柠檬", "lemons": "柠檬",
    "lime": "青柠", "limes": "青柠", "watermelon": "西瓜",
    "cantaloupe": "哈密瓜", "pineapple": "菠萝", "seedless": "无籽",
    # 乳制品/蛋
    "milk": "牛奶", "cream": "奶油", "yogurt": "酸奶", "yoghurt": "酸奶",
    "cheese": "芝士", "butter": "黄油", "dairy": "乳制品",
    "egg": "鸡蛋", "eggs": "鸡蛋",
    # 零食
    "cookie": "曲奇", "cookies": "曲奇", "candy": "糖果", "candies": "糖果",
    "chip": "薯片", "chips": "薯片", "chocolate": "巧克力",
    "popcorn": "爆米花", "cracker": "薄脆饼干", "crackers": "薄脆饼干",
    "marshmallow": "棉花糖", "marshmallows": "棉花糖", "snack": "零食",
    "snacks": "零食", "nacho": "玉米片", "nachos": "玉米片",
    "pretzel": "椒盐卷饼", "pretzels": "椒盐卷饼", "gum": "口香糖",
    # 饮料
    "water": "水", "juice": "果汁", "soda": "汽水", "pop": "汽水",
    "tea": "茶", "coffee": "咖啡", "beverage": "饮料", "beverages": "饮料",
    "cola": "可乐", "sparkling": "气泡", "lemonade": "柠檬水",
    "kombucha": "康普茶", "drink": "饮料", "drinks": "饮料",
    # 主食
    "pasta": "意面", "spaghetti": "意大利面", "rice": "米饭",
    "noodle": "面条", "noodles": "面条", "cereal": "麦片", "bread": "面包",
    "flour": "面粉", "oat": "燕麦", "oats": "燕麦", "oatmeal": "燕麦片",
    "quinoa": "藜麦", "tortilla": "墨西哥薄饼", "tortillas": "墨西哥薄饼",
    "bagel": "百吉饼", "bagels": "百吉饼", "bun": "小圆面包",
    "buns": "小圆面包", "taco": "塔可", "tacos": "塔可", "pizza": "披萨",
    # 调味品
    "salt": "盐", "sauce": "酱", "sauces": "酱", "spice": "香料",
    "spices": "香料", "seasoning": "调味料", "ketchup": "番茄酱",
    "mustard": "芥末", "mayonnaise": "蛋黄酱", "mayo": "蛋黄酱",
    "vinegar": "醋", "syrup": "糖浆", "jam": "果酱", "jams": "果酱",
    "honey": "蜂蜜", "oil": "油",
    # 日用品
    "filter": "滤芯", "filters": "滤芯", "toothpaste": "牙膏",
    "soap": "肥皂", "tissue": "纸巾", "detergent": "洗涤剂",
    "cleaner": "清洁剂", "wipe": "湿巾", "wipes": "湿巾", "foil": "锡纸",
    "dishwasher": "洗碗机",
    # 常见修饰词
    "frozen": "冷冻", "fresh": "新鲜", "organic": "有机", "natural": "天然",
    "whole": "整只", "large": "大", "small": "小", "extra": "特大",
    "mini": "迷你", "family": "家庭装", "value": "超值装",
    "sliced": "切片", "diced": "切丁", "chopped": "切碎", "ground": "碎",
    "cooked": "熟", "raw": "生", "unsalted": "无盐", "salted": "有盐",
    "low": "低", "fat": "脂肪", "reduced": "减", "light": "淡",
    "original": "原味", "premium": "优选",
    # 国家/地区
    "canada": "加拿大", "canadian": "加拿大", "australia": "澳大利亚",
    "australian": "澳大利亚", "china": "中国", "chinese": "中式",
    "italy": "意大利", "italian": "意式", "mexico": "墨西哥",
    "mexican": "墨西哥", "ontario": "安大略", "usa": "美国",
    "american": "美式",
    # 更多蔬菜/香草
    "pumpkin": "南瓜", "radish": "萝卜", "turnip": "芜菁",
    "parsnip": "防风草", "artichoke": "洋蓟", "arugula": "芝麻菜",
    "cilantro": "香菜", "parsley": "欧芹", "basil": "罗勒", "mint": "薄荷",
    "dill": "莳萝", "thyme": "百里香", "rosemary": "迷迭香",
    "herb": "香草", "herbs": "香草",
    # 更多水果
    "fig": "无花果", "figs": "无花果", "date": "椰枣", "dates": "椰枣",
    "apricot": "杏", "apricots": "杏", "pomegranate": "石榴",
    "papaya": "木瓜", "guava": "番石榴", "persimmon": "柿子",
    "nectarine": "油桃", "tangerine": "橘子", "grapefruit": "西柚",
    "coconut": "椰子", "dragonfruit": "火龙果", "passionfruit": "百香果",
    # 更多肉类部位/加工肉
    "chuck": "肩胛肉", "round": "臀肉", "liver": "肝", "heart": "心",
    "gizzard": "胗", "bologna": "香肠", "jerky": "肉干",
    # 更多海鲜
    "anchovy": "凤尾鱼", "sardine": "沙丁鱼", "herring": "鲱鱼",
    "mackerel": "鲭鱼", "octopus": "章鱼", "eel": "鳗鱼", "roe": "鱼子",
    "caviar": "鱼子酱", "catfish": "鲶鱼", "bass": "鲈鱼", "perch": "河鲈",
    # 更多乳制品
    "ricotta": "里科塔芝士", "mozzarella": "马苏里拉芝士",
    "cheddar": "切达芝士", "feta": "菲达芝士", "gouda": "高达芝士",
    "parmesan": "帕玛森芝士", "ghee": "酥油", "margarine": "人造黄油",
    # 更多主食
    "couscous": "库斯库斯", "barley": "大麦", "lentil": "小扁豆",
    "lentils": "小扁豆", "chickpea": "鹰嘴豆", "chickpeas": "鹰嘴豆",
    "millet": "小米", "buckwheat": "荞麦", "vermicelli": "米粉丝",
    "macaroni": "通心粉", "penne": "笔尖面", "lasagna": "千层面",
    "ravioli": "意式饺", "gnocchi": "土豆团子", "croissant": "牛角包",
    "baguette": "法棍", "pita": "口袋饼", "naan": "馕",
    "waffle": "华夫饼", "waffles": "华夫饼", "pancake": "薄煎饼",
    "pancakes": "薄煎饼", "biscuit": "饼干", "biscuits": "饼干",
    # 更多调味品
    "salsa": "莎莎酱", "relish": "腌菜酱", "pickle": "腌黄瓜",
    "pickles": "腌黄瓜", "gravy": "肉汁", "broth": "高汤", "stock": "高汤",
    "bouillon": "浓汤块", "yeast": "酵母", "vanilla": "香草",
    "cinnamon": "肉桂", "nutmeg": "肉豆蔻", "cumin": "孜然",
    "paprika": "红椒粉", "oregano": "牛至", "cayenne": "卡宴辣椒粉",
    # 更多饮料
    "cider": "苹果酒", "smoothie": "冰沙", "milkshake": "奶昔",
    "seltzer": "苏打水", "tonic": "汤力水",
    # 更多零食
    "granola": "格兰诺拉麦片", "gummy": "软糖", "gummies": "软糖",
    "licorice": "甘草糖", "toffee": "太妃糖", "fudge": "乳脂软糖",
    "wafer": "威化饼", "wafers": "威化饼", "donut": "甜甜圈",
    "donuts": "甜甜圈", "muffin": "松饼", "muffins": "松饼",
    # 更多日用品
    "battery": "电池", "batteries": "电池", "diaper": "尿布",
    "diapers": "尿布", "shampoo": "洗发水", "conditioner": "护发素",
    "deodorant": "止汗露", "razor": "剃须刀",
    # 更多修饰词
    "mild": "微辣", "spicy": "辣", "hot": "辣", "sweet": "甜",
    "unsweetened": "无糖", "sweetened": "加糖", "vegan": "纯素",
    "vegetarian": "素食", "multigrain": "多谷物", "jumbo": "特大装",
    "giant": "超大装", "single": "单份",
}

# 短语按长度从长到短排序，避免长短语被短词典先拆碎
_SORTED_PHRASES = sorted(PHRASE_DICT.items(), key=lambda kv: -len(kv[0]))


def translate_name(name_en: str) -> str:
    """把英文商品名转成"中英混合"的可搜索名称。翻不出来的词保留英文。"""
    if not name_en:
        return name_en

    text = name_en

    for phrase, zh in _SORTED_PHRASES:
        # 短语允许结尾带复数 s（chicken thigh / chicken thighs 都能匹配）
        pattern = re.compile(re.escape(phrase) + r"s?", re.IGNORECASE)
        text = pattern.sub(zh, text)

    def _replace_word(match: re.Match) -> str:
        word = match.group(0)
        zh = WORD_DICT.get(word.lower())
        return zh if zh else word

    text = re.sub(r"[A-Za-z']+", _replace_word, text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


if __name__ == "__main__":
    # 简单自测，跑一下看效果
    samples = [
        "New Zealand Lamb Shoulder Blade Chop",
        "Boneless Chicken Thighs",
        "Frozen Pepperoni Thin Crust Pizza",
        "Seedless Green Grapes",
        "Crunchy Peanut Butter",
        "Natural Spring Water",
        "One Minute Oatmeal",
        "Xxl Quantum Ultimate Dishwasher Tab",
    ]
    for s in samples:
        print(f"{s}\n  -> {translate_name(s)}\n")
