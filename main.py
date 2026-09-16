from src.utils import load_api_config
from src.llm.anthropic_llm import anthropic_llm
from src.llm.openai_llm import openai_llm
from src.control_loop import control_loop


def main():
    apis_config = load_api_config()
    provider = apis_config["providers"][apis_config["current_provider"]]

    if(provider["API"] == "anthropic"):
        llm = anthropic_llm(provider)
    elif(provider["API"] == "openai"):
        llm = openai_llm(provider)

    control_loop(llm, provider["models"])


if __name__ == "__main__":
   main()
