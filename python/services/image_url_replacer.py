from __future__ import annotations

import re

IMAGE_MD_PATTERN = re.compile(r"(!\[([^\]]*)\]\(([^)]+)\))")
PLACEHOLDER_PREFIX = "PLACEHOLDER:"


def replace_markdown_image_urls(text: str, minio_endpoint: str, bucket: str) -> str:
    """Replace PLACEHOLDER: paths in markdown image syntax with MinIO public URLs.

    Input:  ![架构图](PLACEHOLDER:incident-001/arch.png)
    Output: ![架构图](http://minio:9000/incident-images/images/incident-001/arch.png)

    Non-placeholder URLs are left unchanged.
    """
    if not text or PLACEHOLDER_PREFIX not in text:
        return text

    endpoint = minio_endpoint.rstrip("/")

    def _replace(match: re.Match) -> str:
        full_match = match.group(1)
        alt_text = match.group(2)
        url = match.group(3)
        if url.startswith(PLACEHOLDER_PREFIX):
            relative = url[len(PLACEHOLDER_PREFIX):]
            resolved = f"{endpoint}/{bucket}/images/{relative}"
            return f"![{alt_text}]({resolved})"
        return full_match

    return IMAGE_MD_PATTERN.sub(_replace, text)


def extract_image_references(text: str) -> list[str]:
    """Extract all image URLs from markdown image syntax."""
    if not text:
        return []
    return [match.group(3) for match in IMAGE_MD_PATTERN.finditer(text)]
