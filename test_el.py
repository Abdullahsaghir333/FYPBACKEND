import os
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs

load_dotenv()
api_key = os.getenv("ElEVENLAB_API")

client = ElevenLabs(api_key=api_key)

try:
    voices = client.voices.get_all()
    print("Available voices:")
    for v in voices.voices[:10]:
        print(f"ID: {v.voice_id}, Name: {v.name}")
except Exception as e:
    print(f"Error accessing ElevenLabs: {e}")
