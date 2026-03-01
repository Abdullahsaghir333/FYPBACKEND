import asyncio
import os
import sys

# add current directory to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.services.notes_pipeline import extract_text_from_upload, generate_slides_from_notes
from fastapi import UploadFile
from io import BytesIO

async def main():
    try:
        # mock an UploadFile wrapper with some text
        file = UploadFile(filename="test.txt", file=BytesIO(b"Hello world, I am learning about AI."))
        text = await extract_text_from_upload(file)
        print("Extracted Text:", text)
        print("Generating slides...")
        slides = await generate_slides_from_notes(text)
        print("Slides:", slides)
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
