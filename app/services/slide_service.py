"""Slide generation service integrating Pluslide export API.

Pluslide exports PPTX/PDF based on templates you design in their editor. We use
the project's templates to build a visual deck. The easiest way to show slides
one-by-one in the browser is to export PDF and render pages client-side.
"""

from __future__ import annotations

from typing import Dict, List, Any, Optional

import httpx

from app.core.config import get_settings

settings = get_settings()


def _can_export_with_pluslide() -> bool:
    return bool(settings.slide_api_key and settings.pluslide_project_id)


async def export_deck_pdf_url(slides_data: List[Dict[str, Any]]) -> Optional[str]:
    """Export a PDF deck from slide dicts and return the download URL.

    Requires:
    - SLIDE_API_KEY
    - PLUSLIDE_PROJECT_ID
    - Templates (keys) compatible with the content we send
    """
    if not _can_export_with_pluslide():
        return None

    slide_list: List[Dict[str, Any]] = []
    for idx, slide in enumerate(slides_data):
        title = str(slide.get("title") or f"Slide {idx + 1}")
        points = slide.get("points") or []
        bullets = [str(p) for p in points] if isinstance(points, list) else [str(points)]

        template_key = settings.pluslide_title_template_key if idx == 0 else settings.pluslide_bullets_template_key
        content: Dict[str, Any] = {"title": title}

        # Common convention: title slide uses subtitle; bullet slide uses bullets[]
        if idx == 0 and len(bullets) > 0:
            content["subtitle"] = bullets[0]
        else:
            content["bullets"] = bullets

        slide_list.append(
            {
                "templateKey": template_key,
                "content": content,
                "attributes": {
                    # keep speaker notes empty; scripts are generated separately in our app
                    "speakerNote": "",
                },
            }
        )

    payload = {
        "projectId": settings.pluslide_project_id,
        "presentation": {"slideList": slide_list},
        "options": {
            "format": "pdf",
            "compressImages": True,
            "embedFonts": True,
        },
    }

    headers = {
        "Authorization": f"Bearer {settings.slide_api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post("https://api.pluslide.com/v1/project/export", json=payload, headers=headers)
            if not resp.is_success:
                print(f"Pluslide export failed: {resp.status_code} - {resp.text}")
                return None
            data = resp.json()
            url = data.get("url")
            return url if isinstance(url, str) and url.startswith("http") else None
    except httpx.TimeoutException:
        print("Pluslide export timed out (PDF).")
        return None
    except Exception as e:
        print(f"Pluslide export error (PDF): {e}")
        return None


# Backward compatible API for existing session.py background task.
# Previously this attempted to return per-slide images; now we instead export
# a PDF deck and return slides unchanged.
async def generate_visual_slides(slides_data: List[Dict[str, Any]], theme: str = "professional") -> List[Dict[str, Any]]:
    _ = theme
    return slides_data


async def get_slide_image(slide_title: str, slide_content: str, theme: str = "professional") -> Optional[str]:
    _ = slide_title, slide_content, theme
    return None
