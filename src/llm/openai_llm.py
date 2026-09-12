import openai

class openai_llm:
    def __init__(self, provider: dict):
        self.client = openai.OpenAI(api_key=provider["api_key"], base_url=provider["base_url"])

    def get_model_list(self):
        try:
            model_list = self.client.models.list()
        except openai.APIError:
            return None

        # 迭代而非 .data，SyncPage 会自动翻页
        return [model.id for model in model_list]


    def get_response(self, model: str, instructions: str, input: str):
        response = self.client.responses.create(
            model = model,
            instructions = instructions,
            input = input
        )

        return response
