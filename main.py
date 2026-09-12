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
    
    print(llm.get_model_info())




if __name__ == "__main__":
   main()