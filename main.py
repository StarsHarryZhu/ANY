from src.utils import load_api_config
from src.llm.messages_llm import messages_llm
from src.llm.responses_llm import responses_llm
from src.control_loop import control_loop


def main():
    apis_config = load_api_config()
    provider = apis_config["providers"][apis_config["current_provider"]]
    api = provider["API"]

    if api == "messages":
        llm = messages_llm(provider)
    elif api == "responses":
        llm = responses_llm(provider)
    else:
        # 没有这个 else 的话，API 写错不会报配置错误，而是 llm 未绑定、
        # 下一行 NameError，看不出是配置问题。取值只认这两个。
        raise ValueError(f'providers.{apis_config["current_provider"]}.API 必须是 "messages" 或 "responses"，现在是 {api!r}')

    control_loop(
        llm,
        provider["models"],
        # 只作为不透明身份写进会话文件（用于判断能否续档），循环层不解读。
        provider_meta={"provider": apis_config["current_provider"], "API": api},
    )


if __name__ == "__main__":
    main()
