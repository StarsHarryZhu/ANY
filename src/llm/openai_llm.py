import openai

class openai_llm:
    def __init__(self, provider: dict):
        self.client = openai.OpenAI(api_key=provider["api_key"], base_url=provider["base_url"])

    def get_model_info(self):
        try:
            return self.client.models.list()
        except openai.APIError:
            return None