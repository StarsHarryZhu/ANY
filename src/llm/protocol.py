from abc import abstractmethod
from typing import Any, Iterator, Protocol

# 每个 wrapper 的三个类各继承一份协议：漏实现任一成员，构造期就 TypeError。
# 两个 wrapper 的协议成员面是对称的，加协议成员要两边同时加。


class llm_protocol(Protocol):
    """messages_llm 与 responses_llm 共同遵守的契约：循环层握着的全部接口。

    这是最外层的接缝。成员只放循环层真的会调的：get_response 与
    get_model_list 故意不在里面——前者当前配置下不可用，后者只有 OpenAI
    一侧实现了（messages_llm 里是注释掉的），放进来会让
    messages_llm(provider) 在构造期 TypeError。

    与另两个协议同一条理由：两个 wrapper 显式继承，漏实现或签名漂移都在
    构造期炸掉，而不是等某个分支真的跑到才发现。
    """

    @abstractmethod
    def start_stream(self, model: str, instructions: str, input, effort: str, tools: list = None, max_output_tokens: int = None):
        """发起流式请求，返回一个 stream_protocol。

        构造流对象本身不发请求，只有实现里 `manager.__enter__()` 那一行才真正
        发出；返回后连接已经开着，调用方必须立刻进 try，中间不要插入可能抛异常
        的代码。
        """
        ...

    @abstractmethod
    def stream_complete(self, stream):
        """drain 到终稿，返回 response_protocol，并保证底层连接已关闭。

        实现必须是 `try: drain finally: close`，顺序不能反：close 之后再取
        终稿会 RuntimeError，而 drain 自己失败（零事件流、中途网络错误）
        也必须保证关闭。
        """
        ...

    @abstractmethod
    def tool_definitions(self, tools: list) -> list:
        """把中立工具定义转成本家线上形状，请求体里 tools 字段的最终内容。

        中立形状（工具注册表就照这个写，与 provider 无关）：

            {"name": str, "description": str, "parameters": <JSON Schema>}

        两家只在两处不同，所以这个转换必须待在本层：Anthropic 的 schema 键名
        是 input_schema，OpenAI Responses 的 parameters 外面还要包一层
        {"type": "function"}。写得不对的后果是不对称的——Anthropic 端点直接
        拒掉整个请求，OpenAI 只是模型看不到工具。

        _params() 自己会调它，调用方（循环层）传中立的即可，不要预先转换。
        """
        ...


class response_protocol(Protocol):
    """messages_response 与 responses_response 共同遵守的契约。

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
        """总 token = input_tokens + output_tokens，不含缓存读写。

        **这不是上下文长度**，所以别再叫它"上下文用量"：在 Anthropic 上它量的
        是"未被缓存的输入 + 输出"，长会话里缓存命中的那部分全被漏掉（缓存的
        占比越大错得越多）。要上下文长度用 used_context——控制台状态行用的
        就是那个。
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
    def tool_continuation(self, results: list) -> list:
        """工具轮的唯一出口：返回按顺序追加进 context 的整段。

        信封的有无由本方法决定，两个 provider 相反，所以不给调用方拼：
        OpenAI 是裸 item 列表（function_call 项 + 结果项），
        Anthropic 必须包成 assistant / user 两条消息，且 assistant 那条要
        带上完整的原始块列表（含 thinking），否则下一轮请求报错。

        只收 results：调用项由实现从 self.tool_calls 取，与 results 按 zip
        配对，所以调用方只负责 results 的顺序和条数（照 self.tool_calls 遍历
        生成就不会错）。以前 calls 也由调用方传，等于允许它传一份对不上的
        列表，zip 会静默截断成短的那个，最终表现为服务端拒绝一个看不出原因
        的请求。
        """
        ...


class stream_protocol(Protocol):
    """messages_stream 与 responses_stream 共同遵守的契约。

    与 response_protocol 同一条理由：两个 wrapper 显式继承，漏实现任何成员
    实例化就 TypeError。这里 contract 很短，但 close() 是唯一"漏了会漏连接、
    且不会立刻报错"的成员，最值得让它在构造期就炸。
    """

    @property
    @abstractmethod
    def raw(self) -> Any:
        """provider 的原生流对象（已经 __enter__ 过，请求已在飞）。

        注意实现必须是 class 级 @property：ABCMeta 从 class __dict__ 算
        __abstractmethods__，在 __init__ 里 self.raw = raw 覆盖不掉抽象属性。
        """
        ...

    @abstractmethod
    def __iter__(self) -> Iterator[str]:
        """只产出文本增量，思考 / 工具参数 / 各类信封事件都已在 wrapper 内滤掉。

        单次遍历，不可重放：底层 SDK 流只有一个共享生成器。要完整文本请从
        stream_complete 返回的 response.output_text 取。
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """关闭底层连接，幂等。必须在 stream_complete 取到终稿之后调用。"""
        ...
