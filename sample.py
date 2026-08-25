from openai import AzureOpenAI
import os

endpoint = "https://ai-starcare-hrm-b4ac0.openai.azure.com/"
api_key = ""

client = AzureOpenAI(
    azure_endpoint=endpoint,
    api_key=api_key,
    api_version="2024-10-21"
)

response = client.chat.completions.create(
    model="gpt-5-mini",  # DEPLOYMENT NAME
    messages=[
        {
            "role": "system",
            "content": "You are a helpful assistant."
        },
        {
            "role": "user",
            "content": "What is artificial intelligence? Explain it simply."
        }
    ]
)

print(response.choices[0].message.content)