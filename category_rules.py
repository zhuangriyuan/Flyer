"""
所有超市共用的分类规则（关键词 -> 中文分类）。

被各个 {store}_convert.py 引用：
    from category_rules import classify, EXCLUDE_CATEGORY_EN

只根据商品名（英文）做判断，不要传入超市自己的英文大类字段一起匹配——
很多超市会把"蔬菜+水果"合并成一个大类（比如 Metro 的 "Fruits &
Vegetables"），大类名字本身就含有 fruit 这种词，混进来匹配会导致整个部门
被误判。大类字段只用来做 EXCLUDE_CATEGORY_EN 那种"排除非食品"的粗筛。
"""

import re
from typing import Optional

# 分类关键词，按优先级从上到下匹配（先匹配到就用哪个类）。
# 顺序很讲究：越"独特、不容易在别的商品里当作风味词出现"的词，排得越靠前；
# 越"容易被别的商品拿来当风味描述"的词（比如奶油/水果口味/蔬菜口味零食），
# 排得越靠后 —— 这样零食/主食这类"实际产品类型"的词会优先于"风味描述"生效，
# 比如"酸奶油洋葱味薯片"会先被"薯片"命中归零食，不会被"洋葱"拽去蔬菜。
CATEGORY_RULES = [
    ("鸡蛋", ["egg", "eggs"]),
    ("宠物", [
        "cat food", "dog food", "dog biscuit", "cat treat", "pet treat",
        "kibble",
    ]),
    ("海鲜", [
        "fish", "salmon", "shrimp", "seafood", "tuna", "tilapia", "cod",
        "squid", "scallop", "scallops", "crab", "lobster", "trout",
        "halibut", "mussel", "mussels", "oyster", "oysters", "clam", "clams",
    ]),
    ("肉", [
        "meat", "beef", "chicken", "pork", "turkey", "ham", "sausage",
        "sausages", "bacon", "wing", "wings", "thigh", "thighs", "breast",
        "breasts", "steak", "lamb", "veal", "ribs", "burger", "burgers",
        "poultry", "drumstick", "drumsticks", "meatball", "meatballs",
        "salami", "pepperoni", "prosciutto", "pastrami", "chorizo",
    ]),
    # 奶制品里"强信号"词——一看就是奶制品本身，不太会被当风味词，所以排早
    ("牛奶", ["milk", "yogurt", "yoghurt", "yogourt", "cheese", "cheeses"]),
    ("零食", [
        "cookie", "cookies", "candy", "candies", "chip", "chips",
        "chocolate", "popcorn", "cracker", "crackers", "marshmallow",
        "marshmallows", "snack", "snacks", "nacho", "nachos", "pretzel",
        "pretzels", "gum", "cake", "cakes", "pie", "pies", "donut",
        "donuts", "doughnut", "doughnuts", "muffin", "muffins",
        "granola", "sorbet", "sorbets", "gelato", "pudding", "puddings",
        "dessert", "desserts", "croissant", "pastry", "sherbet", "brownie",
        "chestnut", "chestnuts", "sunflower seed", "sunflower seeds",
        "trail mix",
    ]),
    ("饮料", [
        "water", "juice", "soda", "pop", "tea", "coffee", "beverage",
        "beverages", "cola", "sparkling", "lemonade", "kombucha", "drink",
        "drinks", "nectar", "seltzer",
    ]),
    ("主食", [
        "pasta", "spaghetti", "rice", "noodle", "noodles", "cereal",
        "bread", "flour", "oat", "oats", "oatmeal", "quinoa", "tortilla",
        "tortillas", "bagel", "bagels", "bun", "buns", "taco", "tacos",
        "pizza", "vermicelli", "ramen", "ramyun", "macaroni", "naan",
        "flatbread", "matzo", "dumpling", "dumplings", "dinner kit",
        "dinner kits",
    ]),
    ("水果", [
        "fruit", "fruits", "berry", "berries", "blueberry", "blueberries",
        "strawberry", "strawberries", "raspberry", "raspberries", "apple",
        "apples", "banana", "bananas", "grape", "grapes", "melon", "peach",
        "peaches", "orange", "oranges", "mango", "mangoes", "pear", "pears",
        "avocado", "avocados", "kiwi", "plum", "plums", "cherry", "cherries",
        "clementine", "clementines", "lemon", "lemons", "lime", "limes",
        "watermelon", "cantaloupe", "pineapple", "mandarin", "tangerine",
        "persimmon", "persimmons", "plantain", "plantains", "blackberry",
        "blackberries",
    ]),
    ("菜", [
        "vegetable", "vegetables", "lettuce", "broccoli", "carrot", "carrots",
        "onion", "onions", "pepper", "peppers", "cabbage", "spinach",
        "cucumber", "cucumbers", "tomato", "tomatoes", "potato", "potatoes",
        "mushroom", "mushrooms", "zucchini", "eggplant", "eggplants", "cauliflower",
        "bean", "beans", "corn", "kale", "celery", "leek", "leeks", "squash",
        "asparagus", "kimchi", "radish", "sprout", "sprouts", "tofu",
        "seaweed", "pea", "peas", "coleslaw", "fries", "fry", "pickle",
        "pickles", "chickpea", "lentil", "salad", "homefries",
    ]),
    # 奶制品里"弱信号"词——容易在别的东西里当风味/成分词出现（冰淇淋、汤、
    # 薯片……），所以放到最后，只有前面所有类目都没命中才轮到它们
    ("牛奶(其他)", ["cream", "butter", "dairy", "margarine"]),
    ("调味品", [
        "salt", "sauce", "sauces", "spice", "spices", "seasoning",
        "ketchup", "mustard", "mayonnaise", "mayo", "vinegar", "syrup",
        "jam", "jams", "honey", "curry", "spread", "spreads", "hummus",
        "tahini", "soup", "pectin", "bouillon", "broth", "stock cube",
    ]),
    ("日用品", [
        "filter", "filters", "toothpaste", "soap", "tissue", "detergent",
        "cleaner", "wipe", "wipes", "foil", "dishwasher", "toilet",
        "shampoo", "conditioner", "battery", "batteries", "diaper",
        "diapers", "bleach", "laundry", "fabric softener", "dryer sheet",
        "scent booster", "air freshener", "disinfectant", "rinse aid",
        "hand wash", "napkin", "towel", "duster", "mop", "mopping",
        "sweeper", "garbage bag", "recycling bag", "spongetowels",
    ]),
]

# "牛奶(其他)" 只是内部用来分优先级的标记名，实际输出还是要归到"牛奶"
_CATEGORY_LABEL_FIX = {"牛奶(其他)": "牛奶"}

# 2026-08 改动：之前这些词是用来"整个排除、不收录"的（美妆个护/成人用品/
# 厨房小工具/文具/灯泡五金/浴室用品），后来想通了——用户逛超市特价的时候
# 确实也会想买洗衣液、剃须刀这些东西，排除掉反而搜不到。改成正经的分类，
# 不排除了，都能被搜到、也都能按分类筛选，只是分到"个护美妆"/"家居百货"/
# "文具"这几个新类目里，不再混进食品分类。
CATEGORY_RULES += [
    ("个护美妆", [
        "serum", "collagen", "hyaluronic", "hyalulonic", "spf", "essence",
        "toner", "tint", "tatoo", "tattoo", "mascara", "lipstick",
        "foundation", "concealer", "moisturizer", "moisturizing lotion",
        "cleanser", "sunscreen", "skincare", "makeup", "cosmetic",
        "cosmetics", "eyeliner", "eyeshadow", "blush", "lotion",
        "hairspray", "deodorant", "razor", "razor blade", "exfoliating",
        "dandruff", "styling gel", "curls mousse", "foaming wash",
        "body wash", "ointment", "eye gel", "daily scrub", "cleansing",
        "condom", "condoms", "lubricant", "vibrating", "vibrator",
        "massager", "candle",
    ]),
    ("家居百货", [
        "measuring cup", "measuring spoon", "mixing bowl", "kitchen scale",
        "digital thermometer", "wired thermometer", "chef's knife",
        "paring knife", "utility knife", "cleaver knife", "santoku knife",
        "sharpening steel", "kitchen shears", "mesh strainer",
        "garlic press", "citrus juicer", "grilling plank", "dinnerware",
        "the little bento", "balloon whisk", "pancake turner",
        "slotted spoon", "locking tong", "sip bottle", "chugger bottle",
        "go-to bottle", "hydrator bottle", "stella bottle",
        "food storage container", "takealongs", "rubbermaid",
        "thermometer", "mandoline", "whisk", "tongs", "turner",
        "platform scale", "sipper bottle", "short brew", "nylon spoon",
        "air fryer", "led bulb", "light bulb", "sylvania",
        "extension cord", "night light", "shower curtain", "shower liner",
        "tub mat", "curtain rod", "lint roller", "pet roller",
    ]),
    ("文具", [
        "sharpie", "papermate", "ballpoint", "mechanical pencil",
        "gel pen", "permanent marker",
    ]),
]

# 有的超市（比如 Metro）给的英文大类字段（比如 "Health & Beauty"）能直接
# 当分类提示用，不用等商品名关键词命中——2026-08 之前是拿这个当"排除"用的
# （EXCLUDE_CATEGORY_EN），现在改成"分类"用，命中就直接归到对应中文类目，
# 不再是"排除不收录"。
CATEGORY_EN_FALLBACK_MAP = {
    "Health & Beauty": "个护美妆",
    "Pharmacy": "个护美妆",
    "Cosmetics": "个护美妆",
    "Beauty": "个护美妆",
}

# 保留这个名字是为了兼容旧代码里 `from category_rules import EXCLUDE_CATEGORY_EN`
# 这种写法不报错，但内容清空了，不再用来排除任何东西。
EXCLUDE_CATEGORY_EN = []

# 同理，这两个也清空+ 恒定返回 False，不再排除任何商品名——保留函数和变量名
# 只是为了兼容各家 {store}_convert.py 里已经写好的
# `from category_rules import is_excluded_by_name` 这种导入，不用逐个改
# 那 7 个文件。
NAME_EXCLUDE_KEYWORDS = []

# 有些词单独匹配会出问题（比如 "butter" 会让 "peanut butter" 被误分到牛奶），
# 所以这些"多词短语"在主分类规则之前先检查，命中就直接用这个分类，不再往下走。
MULTIWORD_OVERRIDES = [
    ("peanut butter", "调味品"),
    ("almond butter", "调味品"),
    ("nut butter", "调味品"),
    ("coffee filter", "日用品"),
    ("ice cream", "零食"),
    ("milk chocolate", "零食"),  # "milk" 是牛奶强信号词，会抢在"chocolate"前面命中，需要单独修正
    ("corn syrup", "调味品"),
    ("corn starch", "调味品"),
    ("egg noodle", "主食"),
    ("egg roll", "零食"),
    ("potato chip", "零食"),
    ("potato bread", "主食"),
    ("corn chip", "零食"),
    ("tomato sauce", "调味品"),
    ("tomato soup", "调味品"),
    ("tomato paste", "调味品"),
    ("tomato juice", "饮料"),
    ("orange juice", "饮料"),
    ("apple juice", "饮料"),
    ("grape juice", "饮料"),
    ("lemon juice", "饮料"),
    ("lime juice", "饮料"),
    ("cranberry juice", "饮料"),
    ("banana chip", "零食"),
    ("fruit juice", "饮料"),
    ("fruit snack", "零食"),
    ("fruit cup", "零食"),
    ("vegetable oil", "调味品"),
    ("vegetable broth", "调味品"),
    ("vegetable soup", "调味品"),
    ("bean sauce", "调味品"),
    ("bean sprout", "菜"),
    ("cheese cake", "零食"),
    ("cheese puff", "零食"),
    ("cheese cracker", "零食"),
    ("yogurt covered", "零食"),
    ("rice cake", "零食"),
    ("rice cracker", "零食"),
    ("rice pudding", "零食"),
    ("milk chocolate bar", "零食"),
    ("soybean paste", "调味品"),
    ("soy sauce", "调味品"),
    ("sesame oil", "调味品"),
    ("curry mix", "调味品"),
    ("curry sauce", "调味品"),
    ("dipping sauce", "调味品"),
    ("fish cake", "海鲜"),
    ("crab meat", "海鲜"),
    ("rice vinegar", "调味品"),
    ("soybean curd", "菜"),
    ("toilet paper", "日用品"),
    ("ginger ale", "饮料"),
    ("paper towel", "日用品"),
    ("waste bag", "日用品"),
    # 2026-08 从 loblaws 数据里补的
    ("olive oil", "调味品"),
    ("veggie dip", "调味品"),
    ("hearts of palm", "菜"),
    ("tater tot", "菜"),
    ("hot dog", "肉"),
    ("cat food", "宠物"),
    ("dog food", "宠物"),
    ("dog biscuit", "宠物"),
    ("cat treat", "宠物"),
    ("pet treat", "宠物"),
    ("valley selections", "菜"),
    ("tam tams", "零食"),
    ("heart of palm", "菜"),
    ("shredded wheat", "主食"),
    ("pepper sauce", "调味品"),
    ("hot sauce", "调味品"),
    ("chili sauce", "调味品"),
    ("laundry detergent", "日用品"),
    ("liquid detergent", "日用品"),
    ("fabric softener", "日用品"),
    ("cheese cracker", "零食"),
    ("cheese flavoured cracker", "零食"),
    ("cheese flavored cracker", "零食"),
    ("bouillon", "调味品"),
    ("stock cube", "调味品"),
]


def is_excluded_by_name(name_en: str) -> bool:
    """2026-08 起不再排除任何商品——NAME_EXCLUDE_KEYWORDS 已清空，这个函数
    恒返回 False。保留函数本身只是为了兼容各家 {store}_convert.py 里已经
    写好的 `from category_rules import is_excluded_by_name` 这种导入和调用，
    不用逐个改那几个文件。以前这些关键词对应的商品（美妆个护/厨具/文具等）
    现在会被 classify() 正常分类到"个护美妆"/"家居百货"/"文具"这几个新类目，
    不再是"排除不收录"。"""
    text = (name_en or "").lower()
    for kw in NAME_EXCLUDE_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}s?\b", text):
            return True
    return False


def classify(name_en: str, category_en: Optional[str] = None) -> Optional[str]:
    """只用商品名判断分类。category_en 参数保留是为了兼容旧调用方式，不参与匹配。
    返回 None 表示"没有匹配到具体类目"，调用方通常应该 fallback 成"其他"再收录，
    而不是直接丢弃——具体要不要排除，用 is_excluded_by_name() 单独判断。"""
    text = (name_en or "").lower()

    # 长短语优先判断（比如 "milk chocolate" 应该整体归"零食"，
    # 不能被更短的规则半路截胡）
    for phrase, zh_category in sorted(MULTIWORD_OVERRIDES, key=lambda kv: -len(kv[0])):
        if phrase in text:
            return _CATEGORY_LABEL_FIX.get(zh_category, zh_category)

    for zh_category, keywords in CATEGORY_RULES:
        for kw in keywords:
            # \b 单词边界匹配 + 结尾允许可选的 's'：pepper 不会命中 pepperoni，
            # cod 不会命中 avocado，但 tissue 能命中 Tissues、cereal 能命中
            # Cereals——很多关键词表里只手动列了单数形式，靠这个兜底匹配复数，
            # 不用每个词都手动补一份 xxx/xxxs。
            if re.search(rf"\b{re.escape(kw)}s?\b", text):
                return _CATEGORY_LABEL_FIX.get(zh_category, zh_category)
    return None


# ============================================================================
# 中文商品名分类规则（给 T&T 这种商品名本身就是中文的超市用）。
#
# 跟上面英文那套的核心区别：中文没有空格分词，\b 单词边界在连续汉字之间基本
# 不存在（"去骨鸡腿肉"里"鸡"前后都是汉字，没有边界），所以这里改用最简单的
# 子串包含匹配（`kw in text`），不用 \b。代价是单字关键词容易"顺手"命中不
# 相关的商品（比如"油炸"里的"油"），所以：
#   1. 关键词尽量用 2 字以上的词，避免用太短容易误伤的单字；
#   2. 分类顺序一样讲究"更具体/更不容易被别的商品误蹭"的排前面；
#   3. 跟英文版一样，返回 None 表示没分到具体类目，调用方应该 fallback 到
#      "其他"，而不是丢弃——真正要不要排除，用 is_excluded_by_name_zh() 判断。
# ============================================================================

CATEGORY_RULES_ZH = [
    ("鸡蛋", ["鸡蛋", "鸭蛋", "皮蛋", "咸蛋", "鹌鹑蛋", "蛋黄酥"]),
    ("海鲜", [
        "三文鱼", "龙虾", "带子", "扇贝", "鲍鱼", "海参", "鱿鱼", "鳕鱼",
        "鱼丸", "鱼蛋", "鱼滑", "鱼柳", "鱼片", "鱼干", "鱼扒", "秋刀鱼",
        "鲈鱼", "黑鱼", "带鱼", "蒲烧鳗", "青口", "北极贝", "北极虾",
        "翡翠螺", "海螺", "虎虾", "基围虾", "甜虾", "螃蟹", "蟹肉", "鱼子酱",
        "生蚝", "鲩鱼", "虾仁", "河虾", "游水虾", "生猛", "海鲜",
    ]),
    ("肉", [
        "五花肉", "叉烧", "腊肉", "腊肠", "香肠", "培根", "热狗", "午餐肉",
        "牛腩", "牛腱", "牛柳", "牛排", "牛肉", "鸡翅", "鸡腿", "鸡胸",
        "鸡全翅", "鸡全翼", "肉丸", "肉卷", "肉片", "肉排", "排骨", "猪蹄",
        "猪排", "猪扒", "羊肉", "羊肩", "鸭肉", "烧鸭", "盐水鸭", "走地鸡",
        "全鸡", "肉干", "牛肉干", "猪肉干", "牛五花", "猪肉", "鸡肉",
        "牛腿", "眼扒", "金钱腱", "仔腩", "牛筋", "肉丝", "叉烧肉", "腊味",
    ]),
    ("牛奶", [
        "牛奶", "豆浆", "酸奶", "芝士", "奶酪", "起司", "炼乳", "淡奶",
        "鲜奶油", "淡奶油", "椰奶", "旺仔牛奶", "麦精", "鸡精",
    ]),
    ("零食", [
        "饼干", "薯片", "巧克力", "曲奇", "蛋卷", "雪糕", "冰棒", "冰淇淋",
        "冰糕", "布丁", "果冻", "月饼", "蛋黄酥", "话梅", "陈皮梅", "梅丁",
        "杨梅", "果脯", "海苔脆片", "虾片", "爆米花", "坚果", "腰果", "杏仁",
        "碧根果", "开心果", "桃酥", "麻薯", "大福", "太妃糖", "牛肉干",
        "猪肉干", "肉铺", "薯条", "蛋卷礼盒",
    ]),
    ("主食", [
        "拉面", "乌冬", "河粉", "意粉", "意面", "螺蛳粉", "米粉", "米线",
        "泡面", "杯面", "方便面", "刀削面", "热干面", "重庆小面", "小笼包",
        "水饺", "饺子", "云吞", "馄饨", "汤圆", "年糕", "面包", "面皮",
        "馒头", "烧卖", "包子", "寿司海苔", "捞饭", "捞面", "煲仔饭",
        "五常大米", "大米", "糯米", "糙米", "十谷米", "多谷米", "面粉",
        "糯米粉", "饺子皮", "云吞皮", "面条", "拌面", "炒面", "山水米",
        "螺蛳粉", "麦片", "麦精", "葱抓饼", "抓饼", "热干面",
    ]),
    ("水果", [
        "苹果", "香蕉", "橙", "蜜橘", "西瓜", "哈密瓜", "美浓香瓜", "香瓜",
        "绿宝石甜瓜", "葡萄", "草莓", "蓝莓", "榴莲", "山竹", "芒果",
        "白玉桃", "水蜜桃", "雪梨", "柚子", "柠檬", "青提", "龙眼", "荔枝",
        "樱桃", "冬枣", "无花果", "猕猴桃", "百香果", "杨桃", "枇杷",
        "晴王葡萄",
    ]),
    ("菜", [
        "高丽菜", "白菜", "娃娃菜", "小白菜", "青葱", "生姜", "大蒜",
        "青椒", "灯笼椒", "长青辣椒", "螺丝椒", "南瓜", "冬瓜", "茄子",
        "豆腐", "豆干", "豆芽", "毛豆", "枝豆", "杏鲍菇", "蘑菇", "花菇",
        "冬菇", "香菇", "木耳", "土豆", "蕃薯", "地瓜", "红薯", "白萝卜",
        "蕃茄", "西红柿", "西兰花", "生菜", "芹菜", "韭菜", "青豆",
        "竹笋", "青瓜", "黄瓜", "西洋菜", "芥兰", "菜心", "空心菜",
        "苦瓜", "冬瓜",
    ]),
    ("调味品", [
        "花生油", "芥花籽油", "菜籽油", "橄榄油", "牛油果油", "芝麻油",
        "香油", "生抽", "老抽", "酱油", "蚝油", "豉油", "米醋", "陈醋",
        "白醋", "花雕", "料酒", "咖喱", "蜂蜜", "麦卢卡", "淀粉", "花椒",
        "辣椒干", "辣椒粉", "五香粉", "鸡精", "汤底", "火锅底料", "XO酱",
        "沙拉酱", "调味料", "腐乳", "豆瓣酱", "甜面酱", "辣酱", "味噌",
        "橄榄油", "山楂片", "魔芋爽", "豆豉鲮鱼",
    ]),
    ("饮料", [
        "矿泉水", "椰子水", "果汁", "橙汁", "苹果汁", "菠萝汁", "凉茶",
        "茉莉花茶", "普洱茶", "乌龙茶", "花旗参", "西洋参", "燕窝", "豆奶",
        "米酒", "醪糟", "酒酿", "汽水", "奶茶",
    ]),
    ("日用品", [
        "湿巾", "湿纸巾", "纸巾", "垃圾袋", "保鲜膜", "锡纸", "消毒",
        "牙刷", "牙膏", "洗洁精", "洗衣液",
    ]),
]

# 2026-08 改动：以前这些词是用来"整个排除、不收录"的（美妆个护/小家电/
# 收纳容器），现在改成正经分类——用户逛超市特价也会想买沐浴露、电饭煲这些
# 东西，排除掉反而搜不到。归到"个护美妆"/"家居百货"这两个新类目，不再是
# 排除。
#
# ⚠️ 用 = [...] + CATEGORY_RULES_ZH（塞到最前面），不是 += （塞到最后面）：
# 食品类目里有些单字关键词（比如"橙"）很容易在香型描述里"顺手"命中，比如
# "青柠橙花沐浴露"这种沐浴露命名里带"橙"字，如果食品类目排在前面检查，
# 会被误判成水果。个护美妆/家居百货的关键词都是"沐浴露"这种两个字以上、
# 不太会在食品名里出现的词，排最前面优先检查更安全。
CATEGORY_RULES_ZH = [
    ("个护美妆", [
        "沐浴露", "沐浴", "洗发", "护发", "面膜", "精华", "爽肤水", "身体乳",
        "牙膏", "剃须", "安全套", "润滑",
    ]),
    ("家居百货", [
        "电磁炉", "电饭煲", "电饭锅", "电热水壶", "电风扇", "空气炸锅",
        "保鲜盒", "密封盒", "储物盒", "玻璃盒", "玻璃长盒", "保温盒", "水壶",
    ]),
] + CATEGORY_RULES_ZH

# 保留这个空列表 + 下面这个恒返回 False 的函数，只是为了兼容
# tnt_convert.py 里已经写好的
# `from category_rules import is_excluded_by_name_zh` 这种导入，不用改
# 那个文件。以前这些词对应的商品现在会被 classify_zh() 正常分类，不再是
# "排除不收录"。
EXCLUDE_KEYWORDS_ZH = []


def is_excluded_by_name_zh(name: str) -> bool:
    """2026-08 起不再排除任何商品，恒返回 False，详见上面的说明。"""
    text = name or ""
    return any(kw in text for kw in EXCLUDE_KEYWORDS_ZH)


def classify_zh(name: str) -> Optional[str]:
    """给商品名本身就是中文的超市（比如 T&T）用的分类函数，子串匹配，
    按 CATEGORY_RULES_ZH 顺序，先匹配到哪个类就用哪个。匹配不到返回 None。"""
    text = name or ""
    for zh_category, keywords in CATEGORY_RULES_ZH:
        for kw in keywords:
            if kw in text:
                return zh_category
    return None


# ============================================================================
# Google 商品分类 -> 中文分类（给用 Flipp 传单系统的超市用，比如 Longo's——
# 它们的接口会直接带 item_categories 这个 Google 分类树 l1~l7，比只看商品名
# 关键词准得多）。longos_convert.py 在用这张表，以后再有别的 Flipp 店也
# 直接复用，不用每家重新写一遍。
#
# 查表顺序是从细到粗（l7...l3），细分类优先——比如同样是"Bakery"底下，
# "Breads & Buns"该归主食，"Cookies"该归零食，两个都比笼统的"Bakery"本身
# 准，所以调用方传进来的 category_names 列表要保证细分类排在前面
# （T&T Longo's/Walmart 的 scraper.py 里 flatten_categories() 已经处理好了
# 这个顺序）。
# ============================================================================
GOOGLE_CATEGORY_MAP = {
    # 肉/海鲜/蛋
    "Meat": "肉",
    "Lunch & Deli Meats": "肉",
    "Seafood": "海鲜",
    "Eggs": "鸡蛋",
    # 奶制品
    "Dairy Products": "牛奶",
    "Yogurt": "牛奶",
    "Cheese": "牛奶",
    "Milk": "牛奶",
    # 零食/甜品
    "Candy & Chocolate": "零食",
    "Frozen Desserts & Novelties": "零食",
    "Snack Foods": "零食",
    "Cookies": "零食",
    "Pies & Tarts": "零食",
    "Cakes & Dessert Bars": "零食",
    "Muffins": "零食",
    "Chips": "零食",
    "Crackers": "零食",
    "Ice Pops": "零食",
    "Ice Cream & Frozen Yogurt": "零食",
    "Marshmallows": "零食",
    "Pretzels": "零食",
    "Fruit Snacks": "零食",
    "Cheese Puffs": "零食",
    "Puffed Rice Cakes": "零食",
    "Cereal & Granola Bars": "零食",
    # 饮料
    "Soda": "饮料",
    "Coffee": "饮料",
    "Tea & Infusions": "饮料",
    "Water": "饮料",
    "Juice": "饮料",
    "Sports & Energy Drinks": "饮料",
    "Beer": "饮料",
    "Hard Cider": "饮料",
    "Nutrition Drinks & Shakes": "饮料",
    "Beverages": "饮料",  # 兜底：只有 l2 有、更细的 l3 没给的情况才会走到这
    # 主食
    "Grains, Rice & Cereal": "主食",
    "Pasta & Noodles": "主食",
    "Breads & Buns": "主食",
    "Rice": "主食",
    "Cereal & Granola": "主食",
    "Oats, Grits & Hot Cereal": "主食",
    "Waffle & Pancake Mixes": "主食",
    # 水果
    "Fresh & Frozen Fruits": "水果",
    "Berries": "水果",
    "Melons": "水果",
    "Citrus Fruits": "水果",
    "Apples": "水果",
    "Stone Fruits": "水果",
    "Pomegranates": "水果",
    "Coconuts": "水果",
    "Grapes": "水果",
    "Oranges": "水果",
    "Peaches & Nectarines": "水果",
    # 菜
    "Fresh & Frozen Vegetables": "菜",
    "Greens": "菜",
    "Beans": "菜",
    "Tomatoes": "菜",
    "Onions": "菜",
    "Peppers": "菜",
    "Cauliflower": "菜",
    "Carrots": "菜",
    "Potatoes": "菜",
    "Kale": "菜",
    "Salad Mixes": "菜",
    "Lettuce": "菜",
    "Guacamole": "菜",
    # 调味品
    "Condiments & Sauces": "调味品",
    "Cooking & Baking Ingredients": "调味品",
    "Dips & Spreads": "调味品",
    "Seasonings & Spices": "调味品",
    "Mayonnaise": "调味品",
    "Mustard": "调味品",
    "Nut Butters": "调味品",
    "Jams & Jellies": "调味品",
    "Bread Crumbs": "调味品",
    "Sugar & Sweeteners": "调味品",
    "Cooking Oils": "调味品",
    "Soups & Broths": "调味品",
    "Gravy": "调味品",
    "Pizza Sauce": "调味品",
    "Honey": "调味品",
    "Vinegar": "调味品",
    # 日用品
    "Household Cleaning Supplies": "日用品",
    "Household Paper Products": "日用品",
    "Laundry Supplies": "日用品",
    "Duster Refills": "日用品",
    "Toilet Paper": "日用品",
    "Paper Towels": "日用品",
    "Laundry Detergent": "日用品",
    # 宠物
    "Cat Food": "宠物",
    "Dog Food": "宠物",
    "Dog Treats": "宠物",
    "Cat Treats": "宠物",
    "Cat Litter": "宠物",
    "Pet Food": "宠物",
    "Pet Supplies": "宠物",
    "Pet Medical Tape & Bandages": "宠物",
}

# "Bakery" 单独没有更细的 l4（比如某些商品分类只做到 l3）时的兜底——
# 面包/餐包该进主食，其余（蛋糕/曲奇之类）默认零食。不放进上面主表是因为
# 它比大多数 l3 更模糊，单独在 classify_by_google_categories() 里处理更清楚。
GOOGLE_CATEGORY_BAKERY_FALLBACK = "零食"


def classify_by_google_categories(category_names: list) -> Optional[str]:
    """category_names 是从细到粗排列的 Google 分类名列表（l7...l3），
    查 GOOGLE_CATEGORY_MAP，第一个命中的就用；都没命中但列表里有"Bakery"
    就用面包/零食那个兜底；再没有就返回 None，交给调用方 fallback 到
    英文关键词 classify() 或者"其他"。"""
    for name in category_names:
        if name in GOOGLE_CATEGORY_MAP:
            return GOOGLE_CATEGORY_MAP[name]
    if "Bakery" in category_names:
        return GOOGLE_CATEGORY_BAKERY_FALLBACK
    return None
