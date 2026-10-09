import json


class tool_console():
    # get_weather 是照抄用的模板：注册新工具就是往 tools / impls 两个容器里各填一份，
    # 真接 API 时换掉它的实现即可。
    def __init__(self):
        # impls 的键和 tools 里的 name 必须完全一致：对不上不会在这里报错，
        # 而是在 tool_run 里 KeyError。
        self.impls = {
            "get_weather": self.get_weather,
        }
        self.tools = [
            {
                "name": "get_weather",
                "description": "Get current weather for a city",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string", "description": "City name"}},
                    "required": ["city"],
                },
            },
        ]


    def get_weather(self, city: str) -> dict:
        # 样例实现，返回假数据。真接 API 就换掉这一行——返回值会被下面
        # json.dumps 序列化，所以给可序列化的值就行，不要自己再 dumps 一遍。
        return {"city": city, "temperature_c": 21, "condition": "sunny"}


    def tool_define(self):
        # 中立形状（name / description / parameters），与 provider 无关。
        # 两家线上形状的差异（Anthropic 的 input_schema、OpenAI 的
        # {"type": "function"} 外层）由 wrapper 的 tool_definitions() 抹平，
        # 这里不要按 provider 分叉。
        # 这是本文件最容易踩的坑：注册表若存 Anthropic 形状（input_schema），
        # wrapper 转换时 tool["parameters"] 直接 KeyError；若存 OpenAI 形状，
        # Anthropic 侧凑巧还能跑（键名正好对上，多出的 type 被忽略）——别依赖这个巧合。
        # 返回非空列表才让 wrapper 真的带上 tools 字段（_params 里是 if tools:）——
        # 注册表被清空会静默把工具从请求体里拿掉，不报错。
        return self.tools


    def tool_run(self, name: str, arguments: str) -> str:
        try:
            # arguments 是 JSON 字符串而非 dict，wrapper 的 tool_call_arguments()
            # 已统一过，直接 loads
            return json.dumps(self.impls[name](**json.loads(arguments)), ensure_ascii=False)
        except Exception as error:
            # 捕获的是 Exception：名字对不上（KeyError）、参数不是合法 JSON
            # （JSONDecodeError）、实现签名不匹配（TypeError）、工具自己抛的异常，都汇到这里。
            # 本来都会冒到循环层，而那边只捕获 KeyboardInterrupt / EOFError，会带 traceback
            # 崩掉整个 REPL。转成错误文本回给模型，让它自己看着纠正。
            # 刻意没接 BaseException：KeyboardInterrupt / SystemExit 照旧穿出去，
            # 让 Ctrl-C 仍然受控。
            #
            # tool_error 是带外标志，不是给模型看的（"error" 那个键模型就够读了）：
            # 光靠 "error"，本函数的失败输出和一个恰好返回 {"error": ...} 的工具
            # 结果完全同形，客户端分不出来。所以失败路径额外打一个标志，成功路径
            # 不打——"没有这个键"就是成功。
            # 它是本仓库的保留键，impls 的返回值里不许用。将来要把它提升成
            # Anthropic 的 is_error 字段，靠的就是这个键，tool_run 签名无需再动。
            return json.dumps(
                {"tool_error": True, "error": f"{type(error).__name__}: {error}"},
                ensure_ascii=False,
            )
