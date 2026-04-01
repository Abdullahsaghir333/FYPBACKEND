import os
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
import json

load_dotenv()
api_key = os.getenv("ElEVENLAB_API")

try:
    client = ElevenLabs(api_key=api_key)
    voices = client.voices.get_all()
    v_list = [(v.voice_id, v.name, v.labels.get("accent"), v.labels.get("description"), v.labels.get("use case")) for v in voices.voices if "male" in str(v.labels.get("gender", "")).lower() or not v.labels.get("gender")]
    with open("voices.json", "w") as f:
        json.dump(v_list[:50], f, indent=2)
except Exception as e:
    with open("voices.json", "w") as f:
        f.write(str(e))
