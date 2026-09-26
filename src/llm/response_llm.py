import openai

from src.llm.response_base import response_protocol, stream_protocol

class response_llm:
    def __init__(self, provider: dict):
        self.client = openai.OpenAI(api_key=provider["api_key"], base_url=provider["base_url"])

    def get_model_list(self):
        try:
            model_list = self.client.models.list()
        except openai.APIError:
            return None

        # 迭代而非 .data，SyncPage 会自动翻页
        return [model.id for model in model_list]


    def _params(self, model, instructions, input, effort, tools, max_output_tokens):
        # 阻塞与流式两条路共用，避免哪天只改了一边导致请求体悄悄分叉
        params = dict(
            max_output_tokens = max_output_tokens if max_output_tokens is not None else 16384,
            temperature = 1,
            model = model,
            instructions = instructions,
            input = input,
            reasoning = {"effort": effort},
        )
        if tools:
            params["tools"] = tools
            params["tool_choice"] = "auto"
        return params


    def get_response(self, model: str, instructions: str, input, effort: str, tools: list = None, max_output_tokens: int = None):
        response = self.client.responses.create(
            **self._params(model, instructions, input, effort, tools, max_output_tokens)
        )

        return response_response(response)


    def start_stream(self, model: str, instructions: str, input, effort: str, tools: list = None, max_output_tokens: int = None):
        manager = self.client.responses.stream(
            **self._params(model, instructions, input, effort, tools, max_output_tokens)
        )

        # __enter__ 这一行才真正发出请求；返回后连接已经开着，调用方要立刻
        # 进 try，中间不要插入可能抛异常的代码。
        return response_stream(manager, manager.__enter__())


    def stream_complete(self, stream):
        # drain 必须在 close 之前，drain 自己失败也要保证关闭
        try:
            return response_response(stream.raw.get_final_response())
        finally:
            stream.close()


class response_response(response_protocol):
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
        # 已包含 cached_tokens，不要再加
        return self.usage.input_tokens or 0

    @property
    def output_tokens(self):
        return self.usage.output_tokens or 0

    @property
    def total_tokens(self):
        return self.input_tokens + self.output_tokens

    @property
    def cache_read_tokens(self):
        # input_tokens_details 可能是 None
        details = self.usage.input_tokens_details
        return (details.cached_tokens or 0) if details else 0

    @property
    def cache_write_tokens(self):
        details = self.usage.input_tokens_details
        return (details.cache_write_tokens or 0) if details else 0

    @property
    def used_context(self):
        # input_tokens 已含 cached_tokens，所以与 total_tokens 同值
        return self.total_tokens

    @property
    def cache_hit_rate(self):
        # input_tokens 已含 cached_tokens，不能再加一遍
        return self.cache_read_tokens / self.input_tokens if self.input_tokens else 0.0

    @property
    def reasoning_tokens(self):
        details = self.usage.output_tokens_details
        return (details.reasoning_tokens or 0) if details else 0

    @property
    def output(self):
        return self.response.output

    @property
    def output_text(self):
        return self.response.output_text

    @property
    def reasoning_text(self):
        parts = []
        for item in self.output:
            if item.type != "reasoning":
                continue
            # 思考文本在内层 content；空的时候退回 summary
            blocks = item.content or []
            if blocks:
                parts.extend(b.text for b in blocks if b.type == "reasoning_text")
            else:
                parts.extend(s.text for s in (item.summary or []))
        return "".join(parts)

    @property
    def tool_calls(self):
        return [item for item in self.output if item.type == "function_call"]

    @property
    def model(self):
        return self.response.model

    @property
    def id(self):
        return self.response.id

    @property
    def stop_reason(self):
        return self.response.status

    def tool_call_name(self, call):
        return call.name

    def tool_call_arguments(self, call):
        # 本来就是 JSON 字符串，原样给 tool_run
        return call.arguments

    def tool_call_id(self, call):
        return call.call_id

    def tool_continuation(self, calls, results):
        # OpenAI 这边工具项是顶层裸 item，不能套 {"role": ...} 信封
        return list(calls) + [
            {"type": "function_call_output", "call_id": call.call_id, "output": result}
            for call, result in zip(calls, results)
        ]


class response_stream(stream_protocol):
    def __init__(self, manager, raw):
        self.manager = manager
        self._raw = raw

    def __repr__(self):
        return repr(self._raw)

    @property
    def raw(self):
        return self._raw

    def __iter__(self):
        # OpenAI 这边没有 anthropic 那种 text_stream 便利属性，只能自己筛事件。
        # 同样必须遍历 self._raw：终稿是 ResponseStream 内部按事件累积出来的。
        for event in self._raw:
            if event.type == "response.output_text.delta":
                yield event.delta

    def close(self):
        self.manager.__exit__(None, None, None)
