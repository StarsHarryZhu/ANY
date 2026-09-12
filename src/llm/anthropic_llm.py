import anthropic

class anthropic_llm:
    def __init__(self, provider: dict):
        self.client = anthropic.Client(api_key=provider["api_key"], base_url=provider["base_url"])
        self.model = provider["model"]
        self.max_tokens = provider.get("max_tokens", 16000)

    def get_model_info(self):
        try:
            return self.client.models.retrieve(self.model)
        except anthropic.APIError:
            return None


