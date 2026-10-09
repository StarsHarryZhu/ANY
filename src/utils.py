import json
import questionary
from rich.console import Console

# 相对当前工作目录写死：只从仓库根目录运行才对。否则 FileNotFoundError 会被吞成
# {}，问题推迟到下游的 KeyError。
API_KEYS_FILE = "src/api_keys.json"

# highlight=False: 关掉 rich 对数字/字符串的自动高亮，否则模型输出会被随机染色。
# 全仓库共用这一个 console：Live 状态挂在它的 _live_stack 上，另建 Console() 会各管
# 各的，live.stop() 清理到的就不是同一个。
console = Console(highlight=False)

def load_api_config():
    # 配置缺失不在这里报错：吞掉 FileNotFoundError 返回 {}，不做任何校验。
    try:
        with open(API_KEYS_FILE, "r") as f:
            api_config = json.load(f)
    except FileNotFoundError:
        api_config = {}
    return api_config

def to_questionary_type(choices: list, key: str) -> list:
    return [
        {"name": str(item[key]), "value": item} if isinstance(item, dict) else item
        for item in choices
    ]

def select(choices: list, message: str, key: str = "name"):
    # key 是死参数：收下但从不用，调用方都是先用 to_questionary_type(choices, key)
    # 转换好再传进来。新增选择器沿用这个两步走法。取消时返回 None，调用方要判空。
    return questionary.select(message, choices).ask()






