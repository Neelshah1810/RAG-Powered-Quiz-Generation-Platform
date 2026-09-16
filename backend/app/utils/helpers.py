"""
Academix AI — General Helper Utilities
"""

from datetime import datetime, timezone
from typing import Optional
import re


def utc_now() -> datetime:
    """Get current UTC timestamp."""
    return datetime.now(timezone.utc)


def slugify(text: str) -> str:
    """Convert text to a URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return re.sub(r"-+", "-", text)


def truncate(text: str, max_length: int = 200) -> str:
    """Truncate text to max_length, adding ellipsis if needed."""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."


def generate_course_color(index: int) -> str:
    """
    Generate a banner color for a course based on its index.
    Uses Google Classroom-style color palette.
    """
    colors = [
        "#4285F4",  # Blue
        "#0F9D58",  # Green
        "#DB4437",  # Red
        "#F4B400",  # Yellow
        "#AB47BC",  # Purple
        "#00ACC1",  # Cyan
        "#FF7043",  # Orange
        "#5C6BC0",  # Indigo
        "#26A69A",  # Teal
        "#EC407A",  # Pink
    ]
    return colors[index % len(colors)]


def parse_comma_separated(text: Optional[str]) -> list[str]:
    """Parse a comma-separated string into a list of stripped strings."""
    if not text:
        return []
    return [item.strip() for item in text.split(",") if item.strip()]
