from openai import OpenAI

def get_gpt_models_action() -> list[str]:
    client = OpenAI()
    models = client.models.list()
    model_names = [model.id for model in models.data]
    return model_names