import requests
import json 
import google.generativeai as genai
import os
from dotenv import load_dotenv
# ---------- Load environment variables ----------
load_dotenv()  # loads variables from .env file

# ---------- LLM Configuration ----------
ACTIVE_LLM = os.getenv("ACTIVE_LLM", "mistral_cloud")              # "gemini", "mistral_cloud", "mistral_local"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-1")            # for Gemini
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_API_URL = os.getenv("MISTRAL_API_URL", "http://localhost:11434/api/generate")  # local Ollama or custom endpoint
MISTRAL_CLOUD_URL = os.getenv("MISTRAL_CLOUD_URL", "https://api.mistral.ai/v1/chat/completions")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "")  # fallback model name for both
MISTRAL_MODEL_CLOUD = os.getenv("MISTRAL_MODEL_CLOUD", "mistral-small")
MISTRAL_MODEL_LOCAL = os.getenv("MISTRAL_MODEL_LOCAL", "mistral:latest")


def call_llm(prompt: str) -> str:
    try:
        #  Gemini Cloud
        if ACTIVE_LLM == "gemini":
            genai.configure(api_key=GEMINI_API_KEY)
            model = genai.GenerativeModel(MODEL_NAME)
            response = model.generate_content(prompt)
            return response.text.strip()

        #  Mistral Cloud API
        elif ACTIVE_LLM == "mistral_cloud":
            url = MISTRAL_CLOUD_URL
            headers = {
                "Authorization": f"Bearer {MISTRAL_API_KEY}",
                "Content-Type": "application/json"
            }
            model_name = MISTRAL_MODEL or MISTRAL_MODEL_CLOUD or "mistral-small"
            payload = {
                "model": model_name,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3
            }
            res = requests.post(url, json=payload, headers=headers, timeout=60)
            res.raise_for_status()
            data = res.json()
            return data["choices"][0]["message"]["content"].strip()

        #  Local Ollama / custom API
        elif ACTIVE_LLM == "mistral_local":
            model_name = MISTRAL_MODEL or MISTRAL_MODEL_LOCAL or "mistral:latest"
            payload = {"model": model_name, "prompt": prompt, "stream": False}
            res = requests.post(MISTRAL_API_URL, json=payload, timeout=60)
            res.raise_for_status()
            data = res.json()
            if isinstance(data, dict):
                if "response" in data:
                    return data["response"].strip()
                if "choices" in data and data["choices"]:
                    return data["choices"][0].get("text", "").strip()
            return json.dumps(data)

        # Invalid LLM setting
        else:
            return "[LLM Error] Invalid ACTIVE_LLM configuration."

    except Exception as e:
        return f"[LLM Error] {str(e)}"
# Force reload

# Force reload 2
