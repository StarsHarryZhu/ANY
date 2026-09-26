import json


class tool_console():
    def __init__(self):
        self.impls = {}
        self.tools = []


    def tool_define(self):
        return self.tools
        # return [
        #     {
        #         "type": "function",
        #         "name": "get_weather",
        #         "description": "Get current weather for a city",
        #         "parameters": {
        #             "type": "object",
        #             "properties": {"city": {"type": "string", "description": "City name"}},
        #             "required": ["city"],
        #         },
        #     },
        # ]


    def tool_run(self, name: str, arguments: str) -> str:
        return json.dumps(self.impls[name](**json.loads(arguments)), ensure_ascii=False)
