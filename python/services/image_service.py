from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from config.settings import AppSettings
from repositories.db import get_minio_client

logger = logging.getLogger(__name__)

IMAGE_MD_PATTERN = re.compile(r"(!\[([^\]]*)\]\(([^)]+)\))")
PLACEHOLDER_PREFIX = "PLACEHOLDER:"


class ImageService:
    def __init__(self, settings: AppSettings | None = None) -> None:
        self._settings = settings or AppSettings()

    def upload_image(self, image_path: Path, source_doc: str) -> str:
        """Upload an image to MinIO incident-images bucket and return public URL."""
        client = get_minio_client(self._settings)
        bucket = self._settings.minio_image_bucket

        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)

        filename = image_path.name
        object_name = f"images/{source_doc}/{filename}"
        content_type = _resolve_content_type(filename)

        client.fput_object(
            bucket_name=bucket,
            object_name=object_name,
            file_path=str(image_path),
            content_type=content_type,
        )

        url = self.generate_image_url(object_name)
        logger.info("Uploaded image %s -> %s", image_path, url)
        return url

    def generate_image_url(self, object_name: str) -> str:
        """Generate a publicly accessible URL for a MinIO object."""
        endpoint = self._settings.minio_endpoint.rstrip("/")
        bucket = self._settings.minio_image_bucket
        return f"{endpoint}/{bucket}/{object_name}"

    def replace_image_urls(self, text: str) -> str:
        """Replace PLACEHOLDER: paths in markdown image syntax with MinIO URLs.

        Matches: ![alt](PLACEHOLDER:source_doc/filename.png)
        Replaces with: ![alt](http://minio:9000/incident-images/images/source_doc/filename.png)
        """
        if not text or PLACEHOLDER_PREFIX not in text:
            return text

        endpoint = self._settings.minio_endpoint.rstrip("/")
        bucket = self._settings.minio_image_bucket

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

    def get_image_mapping(self, source_doc: str) -> dict:
        """Read the mapping file and return entries for a specific source document."""
        mapping = self._load_mapping_file()
        return mapping.get(source_doc, {})

    def get_all_mappings(self) -> dict:
        """Read and return the full mapping file."""
        return self._load_mapping_file()

    def save_mapping(self, mapping: dict) -> None:
        """Save the mapping file to local disk and optionally to MinIO."""
        mapping_path = self._mapping_file_path()
        mapping_path.parent.mkdir(parents=True, exist_ok=True)
        mapping_path.write_text(
            json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("Saved image mapping to %s", mapping_path)

        try:
            from io import BytesIO

            client = get_minio_client(self._settings)
            bucket = self._settings.minio_image_bucket
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)
            body = json.dumps(mapping, indent=2, ensure_ascii=False).encode("utf-8")
            client.put_object(
                bucket_name=bucket,
                object_name="mapping/mapping.json",
                data=BytesIO(body),
                length=len(body),
                content_type="application/json",
            )
        except Exception as exc:
            logger.warning("Failed to upload mapping to MinIO: %s", exc)

    def _mapping_file_path(self) -> Path:
        root = Path(__file__).resolve().parents[1]
        return root / "data" / "mapping.json"

    def _load_mapping_file(self) -> dict:
        path = self._mapping_file_path()
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))


def _resolve_content_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }.get(ext, "application/octet-stream")
