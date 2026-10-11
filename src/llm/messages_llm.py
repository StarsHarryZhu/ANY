import json

import anthropic

from src.llm.protocol import llm_protocol, response_protocol, stream_protocol


class messages_llm(llm_protocol):
    def __init__(self, provider: dict):
        self.client = anthropic.Client(api_key=provider["api_key"], base_url=provider["base_url"])

    # Anthropic 侧没实现，所以 get_model_list 不在 llm_protocol 里（OpenAI 侧是活的），
    # 放进去会让本类构造期 TypeError。要给它定协议，先决定这一侧怎么取模型列表。
    # def get_model_list(self):
    #     try:
    #         return self.client.models.list()
    #     except anthropic.APIError:
    #         return None

    def _params(self, model, instructions, input, effort, tools, max_output_tokens):
        # 阻塞与流式两条路共用，避免哪天只改了一边导致请求体悄悄分叉。
        # max_tokens 没有默认值，这个 16384 兜底必须留在这里。
        # 与 responses_llm._params 刻意各留一份、不抽成模块级函数：两侧键名不同
        # （system/messages vs instructions/input，output_config vs reasoning），
        # 合并会把两家差异藏进一个函数，是"看着像重复、其实不能 DRY"。
        params = dict(
            max_tokens = max_output_tokens if max_output_tokens is not None else 16384,
            model = model,
            system = instructions,
            messages = input,
            output_config = {"effort": effort},
        )
        if tools:
            params["tools"] = self.tool_definitions(tools)
        return params

    def tool_definitions(self, tools: list) -> list:
        # 中立 -> Anthropic：schema 的键名是 input_schema，不是 parameters。
        # 名字写错不是"工具不生效"，是整个请求被端点拒掉。
        return [
            {
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["parameters"],
            }
            for tool in tools
        ]

    def context_display(self, context: list) -> list:
        # 存档形状 -> 中立的展示行，只在续档回放时用（契约见协议的 docstring）。
        # 回放要跟当时屏幕上的一致：text 进正文行，tool_use 与后面那条 tool_result
        # 配成一条 [tool] 行，thinking / redacted_thinking 跳过（活着时也没显示过）。
        # 两种消息形状都要认：循环层自己拼的普通轮 content 是字符串，工具轮那两条
        # 信封（assistant 一条、user 一条）才是块列表。
        rows = []
        pending = {}  # tool_use_id -> 那一行，等后面 user 消息里的 tool_result 补上 result
        for message in context:
            # load_session 只校验顶层是 list，元素形状一概不管：坏档在这里要安静跳过，
            # 这里抛异常会落在循环层的 try 之外，直接带 traceback 崩掉启动。
            if not isinstance(message, dict):
                continue
            role = "assistant" if message.get("role") == "assistant" else "user"
            content = message.get("content")
            if isinstance(content, str):
                if content:
                    rows.append({"role": role, "text": content})
                continue
            if not isinstance(content, list):
                continue
            # 攒着的文本遇见工具块就成行：块顺序（thinking, text, tool_use）因此
            # 就是回放的顺序，与当时一致。
            text = []
            for block in content:
                # 按 type 过滤、不按属性取——redacted_thinking 没有 thinking 字段，
                # 按属性取就是 reasoning_text 那边躲过的坑。
                if not isinstance(block, dict):
                    continue
                kind = block.get("type")
                if kind == "text":
                    text.append(block.get("text") or "")
                elif kind == "tool_use":
                    if text:
                        rows.append({"role": role, "text": "".join(text)})
                        text = []
                    row = {
                        "role": "tool",
                        "name": block.get("name") or "",
                        # 与 tool_call_arguments 同一写法：回放那行跟当时屏幕上那行逐字相同
                        "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                        "result": None,
                    }
                    pending[block.get("id")] = row
                    rows.append(row)
                elif kind == "tool_result":
                    row = pending.get(block.get("tool_use_id"))
                    if row is not None:
                        result = block.get("content")
                        if isinstance(result, list):
                            # content 也允许是块列表，取其中的 text（与字符串那种写法等价）
                            result = "".join(
                                inner.get("text") or ""
                                for inner in result
                                if isinstance(inner, dict) and inner.get("type") == "text"
                            )
                        row["result"] = result if isinstance(result, str) else ""
            if text:
                rows.append({"role": role, "text": "".join(text)})
        return rows


    def get_response(self, model: str, instructions: str, input, effort: str, tools: list = None, max_output_tokens: int = None):
        # 注意：非流式会被 SDK 的时间预估卡住——Messages.create 发请求前按
        # 3600 * max_tokens / 128_000 估时，超过 600 秒（模型不在 SDK 已知表里时
        # 即 max_tokens > 21333）直接抛 ValueError("Streaming is required")。
        # 当前配置的输出上限高于它，这条路对现模型必抛。真要复活：显式传 timeout=
        # （守卫条件是 not is_given(timeout)，给了就跳过预估），代价是硬吃 10 分钟
        # 上限。OpenAI 侧没有这条守卫。走长输出请用 start_stream / stream_complete。
        response = self.client.messages.create(
            **self._params(model, instructions, input, effort, tools, max_output_tokens)
        )

        return messages_response(response)

    def start_stream(self, model: str, instructions: str, input, effort: str, tools: list = None, max_output_tokens: int = None):
        manager = self.client.messages.stream(
            **self._params(model, instructions, input, effort, tools, max_output_tokens)
        )

        # 构造 messages_stream 本身不发请求：真正的发送发生在求值 manager.__enter__()
        # 这一行（它是构造实参，别误读成"先构造好再发"）。返回后连接已经开着，
        # 调用方要立刻进 try，中间不要插入可能抛异常的代码。
        return messages_stream(manager, manager.__enter__())

    def stream_complete(self, stream):
        # drain 必须在 close 之前：关掉之后再 get_final_message 会 RuntimeError。
        # drain 自己失败（零事件流的裸 AssertionError、中途网络错误）也要保证关闭。
        try:
            return messages_response(stream.raw.get_final_message())
        finally:
            stream.close()



class messages_response(response_protocol):
    def __init__(self, response):
        self.response = response

    def __repr__(self):
        return repr(self.response)

    @property
    def raw(self):
        return self.response

    @property
    def usage(self):
        return self.response.usage

    @property
    def input_tokens(self):
        return self.usage.input_tokens or 0

    @property
    def output_tokens(self):
        return self.usage.output_tokens or 0

    @property
    def total_tokens(self):
        return self.input_tokens + self.output_tokens

    @property
    def cache_read_tokens(self):
        return self.usage.cache_read_input_tokens or 0

    @property
    def cache_write_tokens(self):
        return self.usage.cache_creation_input_tokens or 0

    @property
    def used_context(self):
        # input_tokens 不含缓存，真实上下文要把命中与写入加回来
        return self.total_tokens + self.cache_read_tokens + self.cache_write_tokens

    @property
    def cache_hit_rate(self):
        # input_tokens 不含缓存，总输入要把命中与写入加回来
        total = self.input_tokens + self.cache_read_tokens + self.cache_write_tokens
        return self.cache_read_tokens / total if total else 0.0

    @property
    def reasoning_tokens(self):
        details = self.usage.output_tokens_details
        return (details.reasoning_tokens or 0) if details else 0

    @property
    def output(self):
        return self.response.content

    @property
    def output_text(self):
        return "".join(b.text for b in self.output if b.type == "text")

    @property
    def reasoning_text(self):
        # redacted_thinking 块没有 .thinking，靠 type 过滤掉
        return "".join(b.thinking for b in self.output if b.type == "thinking")

    @property
    def tool_calls(self):
        return [b for b in self.output if b.type == "tool_use"]

    @property
    def model(self):
        return self.response.model

    @property
    def id(self):
        return self.response.id

    @property
    def stop_reason(self):
        return self.response.stop_reason

    def tool_call_name(self, call):
        return call.name

    def tool_call_arguments(self, call):
        # input 本来就是 dict，转成 JSON 字符串好让 tool_run 直接 json.loads
        return json.dumps(call.input, ensure_ascii=False)

    def tool_call_id(self, call):
        return call.id

    def tool_continuation(self, results):
        # assistant 那条必须带上完整的原始块列表（含 thinking），否则下一轮报错。
        # 调用项从 self.tool_calls 现取，不再由调用方传进来：两边同源，就不存在
        # 传一份对不上的列表被 zip 静默截断的可能。
        return [
            {"role": "assistant", "content": self.output},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": call.id, "content": result}
                for call, result in zip(self.tool_calls, results)
            ]},
        ]


class messages_stream(stream_protocol):
    def __init__(self, manager, raw):
        self.manager = manager
        self._raw = raw

    def __repr__(self):
        return repr(self._raw)

    @property
    def raw(self):
        return self._raw

    def __iter__(self):
        # 和 SDK 自己的 MessageStream.text_stream 等价——但不用它是有意的：沿用和
        # responses_llm.__iter__ 同一套手筛，两边读起来一致，不是因为 text_stream 不可用。
        # 另注：text_stream 是 SDK 在 __init__ 里挂上的实例属性、不是 class 属性，
        # dir(MessageStream) 查不到，别因此以为它不存在。
        # 必须遍历 self._raw 这个 SDK 流对象，不能穿透到它内部的 _raw_stream：终稿快照是
        # MessageStream 在 __stream__ 里累积的，绕过去就会"有增量、没终稿"，最后在
        # stream_complete 里炸出一个看不出原因的 AssertionError。
        for event in self._raw:
            if event.type == "content_block_delta" and event.delta.type == "text_delta":
                yield event.delta.text

    def close(self):
        # 走 manager.__exit__ 而不是 raw.close()，SDK 将来加在 manager 上的
        # 清理也能一并生效。幂等。
        self.manager.__exit__(None, None, None)
