import google.generativeai as genai

genai.configure(api_key="AIzaSyB4pFQKLM1DXA-bqfeLkW3RndY3sUH4kIY")

for m in genai.list_models():
    if 'generateContent' in m.supported_generation_methods:
        print(m.name)