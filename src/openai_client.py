from openai import OpenAI
from config import ConfigManager

def get_openai_client():
    config = ConfigManager()
    api_key = config.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("Missing OpenAI API Key")
    return OpenAI(api_key=api_key)

# Singleton instance
client = get_openai_client()
