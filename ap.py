import os
import time
from google import genai
from google.genai import types

# Initialize Client
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def extract_text_from_pdf(pdf_path: str):
    try:
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        response = client.models.generate_content(
            model="gemini-2.5-flash-lite", 
            contents=[
                "Extract ALL text from this PDF accurately.",
                types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
            ]
        )
        return response.text
    except Exception as e:
        return f"Extraction Error: {e}"

def generate_slide_points(text_content: str):
    """Sends the extracted text back to the LLM to create presentation slides."""
    try:
        # Respect the Free Tier 15 RPM limit (Wait between calls)
        print("Cooldown: Waiting 5 seconds before generating slides...")
        time.sleep(5)

        prompt = f"""
        Based on the following notes, create a structured presentation outline.
        For each main topic, provide:
        1. A Slide Title
        2. 3-4 concise bullet points
        
        Notes content:
        {text_content}
        """

        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7, # Slightly higher for better formatting/summarization
            )
        )
        return response.text

    except Exception as e:
        if "429" in str(e):
            return "QUOTA ERROR: Wait 60s before generating slides."
        return f"Slide Generation Error: {e}"

if __name__ == "__main__":
    path = r"C:\Users\abdul\Downloads\Stat Modeling Notes till S1.pdf"
    
    if os.path.exists(path):
        # Step 1: Extract
        print("Step 1: Extracting text from PDF...")
        raw_text = extract_text_from_pdf(path)
        
        if "Error" not in raw_text:
            # Step 2: Generate Slides
            print("Step 2: Generating slide points...")
            slides = generate_slide_points(raw_text)
            
            print("\n----- SUGGESTED SLIDES -----\n")
            print(slides)
            
            # Optional: Save to file so you don't have to run it again
            with open("slides_outline.txt", "w", encoding="utf-8") as f:
                f.write(slides)
            print("\n[Saved to slides_outline.txt]")
    else:
        print("File not found.")