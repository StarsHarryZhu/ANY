from src.utils import select, to_questionary_type

def control_loop(llm, models: list, system_prompt: str = None, context: list = None):

    model = select(to_questionary_type(models, "name"), "Select model")
    
    if model is None:
        print("Cancelled.")
        return

    model_name = model["name"]
    max_context_window = model["context_window"]

    effort = select(to_questionary_type(model["efforts"], None), "Select reasoning effort")
    if effort is None:
        print("Cancelled.")
        return

    if system_prompt is None:
        system_prompt = f"You are {model_name}."

    print(f"Using model: {model_name} (effort={effort})")

    if context is None:
        context = []

    while True:
        try:
            user_input = input("User: ")

            context.append({"role": "user", "content": user_input})

            response = llm.get_response(model_name, system_prompt, " ".join([msg["content"] for msg in context]), effort)

            context.append({"role": "assistant", "content": response.output_text})

            print(f"Model: {response.output_text}")
            print(f"context: {response.usage.input_tokens} / {max_context_window}")

        except (KeyboardInterrupt, EOFError):
            print("\nExiting control loop.")
            break
