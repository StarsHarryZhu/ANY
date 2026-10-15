# 摘要指令。英文：这段是发给模型的内容，与仓库注释用什么语言无关。
# 明确要求"只回摘要、不要开场白"：返回值会被原样塞进 context 当新历史的开头，
# 多一句 "Sure, here is the summary" 就永远留在那儿了。
SUMMARY_INSTRUCTIONS = (
    "You are compacting a conversation transcript so that it can continue in a smaller context. "
    "Rewrite everything you are given as one dense, self-contained note, written so that the "
    "conversation can pick up from it directly. Keep: what the user is trying to do, their "
    "constraints and preferences, decisions already made, open questions, and every concrete "
    "detail a later turn might depend on (names, paths, numbers, code identifiers, commands). "
    "Drop: greetings, restatements, and the mechanics of tool calls. "
    "Reply with the note itself and nothing else — no preamble, no headings, no meta-commentary."
)

# 压缩后 context 里那一条消息的开头。写清楚"之前的消息被压掉了"，否则读到的模型会以为
# 用户刚说了这么一段话，或者以为对话才刚开始。
SUMMARY_PREFIX = "Summary of the conversation so far (earlier messages were compacted away):\n\n"


class compact():
    # 0x01 / 0x02 已被 current_time / current_location 占用。
    ID = 0x03

    # 契约里的可选能力位：声明它，tool_run 才会把活的 context 和 complete 回调递进来
    # （见 _tool_console.tool_run）。缺省不声明＝只收 JSON 参数，另外两个工具就是那样。
    NEEDS_CONTEXT = True

    # 描述替模型回答"什么时候该调我"。它同时也是敲错指令时的自救依据：用户敲了
    # /compct，模型读到 user_command(compct)，据此知道该调这个工具把指令补完。
    DESCRIPTION = (
        "Replace the conversation so far with a compact summary of it, freeing up context. "
        "Use it when the exchange has grown long and its earlier turns no longer need to be "
        "kept verbatim. The user can also trigger it directly by typing /compact."
    )

    def get_method(self) -> dict:
        # 名字取类名本身，不手抄字符串（同另外两个工具）。
        # 不收参数：指令那条路上尾部文本是发给模型的，不是给工具的（循环层的决定）。
        return {
            "name": type(self).__name__,
            "id": self.ID,
            "description": self.DESCRIPTION,
            "parameters": {"type": "object", "properties": {}},
        }

    def toolcall(self, context: list, complete) -> dict:
        # 就地改写 context（切片赋值），不是重新绑定名字：循环层手里握的是同一个列表对象，
        # 只有就地改它才看得见。写成 context = [...] 等于什么都没发生。
        #
        # 只动 context，不动 messages：messages 是完整历史，压缩只改变"当前发给模型哪一份"。
        # 那是循环层的两份账，工具连 messages 都拿不到。
        before = len(context)
        if before == 0:
            # 空对话不是失败：没有可压的东西，如实回报即可（不抛，别让 tool_error 背这个锅）。
            return {"compacted": False, "reason": "the conversation is empty"}

        # 递一份浅拷贝进去：complete 会在别的栈上跑一轮请求，给它一份与即将被替换的列表
        # 解耦的快照，省得将来有人改成边流边改。
        summary = complete(SUMMARY_INSTRUCTIONS, list(context))
        if not summary.strip():
            # 摘要为空时替换＝把整段历史清空，是最坏的副作用。此时什么都不做，抛出去让
            # tool_run 转成 tool_error（工具整体失败就该 raise，不能 return {"error": ...}）。
            raise RuntimeError("the summarizer returned no text; context left unchanged")

        context[:] = [{"role": "user", "content": SUMMARY_PREFIX + summary}]
        # 返回值里不放摘要正文：tool_run 的返回会被打成一行 [tool] 上屏，几 KB 的摘要没法看，
        # 而摘要本身刚刚已经流式上过屏了。这里只报账。
        return {"compacted": True, "messages_before": before, "messages_after": len(context)}
