import anthropic

class anthropic_llm:
    def __init__(self, provider: dict):
        self.client = anthropic.Client(api_key=provider["api_key"], base_url=provider["base_url"])

    # def get_model_list(self):
    #     try:
    #         return self.client.models.list()
    #     except anthropic.APIError:
    #         return None


