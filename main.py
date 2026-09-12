from src.llm.utils import load_api_keys
from src.llm.anthropic_llm import anthropic_llm
from src.llm.openai_llm import openai_llm




def main():
    api_keys = load_api_keys()
    provider = api_keys["providers"][api_keys["current_provider"]]

    print(provider["API"], provider["base_url"], provider["api_key"])

    if(provider["API"] == "anthropic"):
        llm = anthropic_llm(provider)
    elif(provider["API"] == "openai"):
        llm = openai_llm(provider)
    
    model_list = llm.get_model_list()

    if model_list is None:
        print("Error retrieving model information.")
        return

    print(f"Available models: {model_list}")

    model = model_list[0]
    print(f"Using model: {model}")

    response = llm.get_response(model, "You are {model}.", "Hi, who are u?")

    print(response)


if __name__ == "__main__":
   main()