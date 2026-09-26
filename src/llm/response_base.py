from abc import abstractmethod
from typing import Any, Protocol


class response_protocol(Protocol):
    """anthropic_response 与 response_response 共同遵守的契约。

    两个 wrapper 显式继承本协议：漏实现任何一个成员，实例化时就会 TypeError，
    这样两边不会悄悄漂移。协议本身不参与运行，只是清单 + 类型提示。

    成员上的 @abstractmethod 只对显式继承的子类生效，是刻意的：没有它，
    Protocol 默认不强制任何东西（__abstractmethods__ 为空），清单就只是注释。
    """

    @property
    @abstractmethod
    def raw(self) -> Any:
        """provider 的原生响应对象。保真出口，协议没覆盖的字段从这里取。"""
        ...

    @property
    @abstractmethod
    def usage(self) -> Any:
        """provider 的原生 usage 对象，原始字段名都在这里。"""
        ...

    @property
    @abstractmethod
    def input_tokens(self) -> int:
        """当前这一轮的输入 token。

        注意两侧口径不同：Anthropic 的 input_tokens 不含缓存读/写部分
        （那部分在 cache_read_tokens / cache_write_tokens 里），
        OpenAI 的 input_tokens 已包含 cached_tokens。别直接横向比。
        """
        ...

    @property
    @abstractmethod
    def output_tokens(self) -> int:
        """当前这一轮的输出 token，两侧都含思考/推理 token。"""
        ...

    @property
    @abstractmethod
    def total_tokens(self) -> int:
        """上下文总用量 = input_tokens + output_tokens。

        沿用 input + output 口径，不含缓存读写（见 input_tokens 的说明）。
        在 Anthropic 上它量的是"未被缓存的输入 + 输出"，不是上下文长度；
        要那个用 used_context。
        """
        ...

    @property
    @abstractmethod
    def used_context(self) -> int:
        """本轮实际占用的上下文长度 = 全部输入 + 输出。

        这是"下一轮请求将要携带的上下文长度"，两侧同一口径可比：
        Anthropic 要把缓存读写的部分加回来（它的 input_tokens 不含），
        OpenAI 的 input_tokens 已含 cached_tokens，所以与 total_tokens 同值。
        """
        ...

    @property
    @abstractmethod
    def cache_read_tokens(self) -> int:
        """命中输入缓存的 token 数。Anthropic 取 cache_read_input_tokens，
        OpenAI 取 input_tokens_details.cached_tokens。"""
        ...

    @property
    @abstractmethod
    def cache_write_tokens(self) -> int:
        """写入输入缓存的 token 数。Anthropic 取 cache_creation_input_tokens，
        OpenAI 取 input_tokens_details.cache_write_tokens。"""
        ...

    @property
    @abstractmethod
    def cache_hit_rate(self) -> float:
        """缓存命中率 = 命中 / 本次请求的全部输入 token，分母为 0 时返回 0.0。

        分母两侧算法不同，因为 input_tokens 的语义不同：Anthropic 的
        input_tokens 不含缓存，要加上命中与写入；OpenAI 的 input_tokens
        已含 cached_tokens（子集语义），直接用它就行，再加会重复计算。
        """
        ...

    @property
    @abstractmethod
    def reasoning_tokens(self) -> int:
        """思考/推理 token 数，已包含在 output_tokens 里。"""
        ...

    @property
    @abstractmethod
    def output(self) -> list:
        """本轮输出的原始块列表，保真。Anthropic 是 content，OpenAI 是 output。"""
        ...

    @property
    @abstractmethod
    def output_text(self) -> str:
        """最终回答的纯文本，不含思考、不含工具调用参数。"""
        ...

    @property
    @abstractmethod
    def reasoning_text(self) -> str:
        """思考/推理文本。两侧都可能为空串。"""
        ...

    @property
    @abstractmethod
    def tool_calls(self) -> list:
        """本轮的工具调用项，provider 原生形状（Anthropic 是 tool_use 块，
        OpenAI 是 function_call 项）。差异由下面四个方法抹平。"""
        ...

    @property
    @abstractmethod
    def model(self) -> str:
        """实际响应的模型名。"""
        ...

    @property
    @abstractmethod
    def id(self) -> str:
        """响应 id。"""
        ...

    @property
    @abstractmethod
    def stop_reason(self) -> str | None:
        """原生停止原因（Anthropic 是 stop_reason，OpenAI 是 status）。
        两侧词表不互通，仅作展示。"""
        ...

    @abstractmethod
    def tool_call_name(self, call) -> str:
        """取工具名。"""
        ...

    @abstractmethod
    def tool_call_arguments(self, call) -> str:
        """取工具参数，统一成 JSON 字符串，好让 tool_console.tool_run 直接 json.loads。

        Anthropic 的 call.input 本来就是 dict，这里会 dumps 一次。
        """
        ...

    @abstractmethod
    def tool_call_id(self, call) -> str:
        """取工具调用 id。Anthropic 用 .id，OpenAI 用 .call_id。"""
        ...

    @abstractmethod
    def tool_continuation(self, calls: list, results: list) -> list:
        """工具轮的唯一出口：返回按顺序追加进 context 的整段。

        信封的有无由本方法决定，两个 provider 相反，所以不给调用方拼：
        OpenAI 是裸 item 列表（function_call 项 + 结果项），
        Anthropic 必须包成 assistant / user 两条消息，且 assistant 那条要
        带上完整的原始块列表（含 thinking），否则下一轮请求报错。

        内部按 zip(calls, results) 配对，调用方需保持顺序。
        """
        ...
