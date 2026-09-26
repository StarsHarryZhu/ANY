import json

import anthropic

from src.llm.response_base import response_protocol


class anthropic_llm:
    def __init__(self, provider: dict):
        self.client = anthropic.Client(api_key=provider["api_key"], base_url=provider["base_url"])

    # def get_model_list(self):
    #     try:
    #         return self.client.models.list()
    #     except anthropic.APIError:
    #         return None

    def get_response(self, model: str, instructions: str, input, effort: str, tools: list = None):
        kwargs = {"tools": tools} if tools else {}

        response = self.client.messages.create(
            max_tokens = 16384,
            model = model,
            system = instructions,
            messages = input,
            output_config = {"effort": effort},
            **kwargs
        )

        return anthropic_response(response)



class anthropic_response(response_protocol):
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

    def tool_continuation(self, calls, results):
        # assistant 那条必须带上完整的原始块列表（含 thinking），否则下一轮报错
        return [
            {"role": "assistant", "content": self.output},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": call.id, "content": result}
                for call, result in zip(calls, results)
            ]},
        ]
