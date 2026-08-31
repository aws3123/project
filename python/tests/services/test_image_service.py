"""Tests for image_service module (requires MinIO running for integration tests)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from services.image_service import ImageService, _resolve_content_type
from services.image_url_replacer import replace_markdown_image_urls


class TestImageServiceUnit:
    """Unit tests for ImageService (mocked MinIO client)."""

    def setup_method(self) -> None:
        self.settings = MagicMock()
        self.settings.minio_endpoint = "http://localhost:9000"
        self.settings.minio_image_bucket = "incident-images"
        self.service = ImageService(self.settings)

    @patch("services.image_service.get_minio_client")
    def test_upload_image(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.bucket_exists.return_value = False
        mock_get_client.return_value = mock_client

        from pathlib import Path
        url = self.service.upload_image(Path("dummy.png"), "incident-001")

        mock_client.make_bucket.assert_called_once_with("incident-images")
        assert "images/incident-001/dummy.png" in url
        assert "localhost:9000/incident-images" in url

    def test_generate_image_url(self) -> None:
        url = self.service.generate_image_url("images/incident-001/arch.png")
        assert url == "http://localhost:9000/incident-images/images/incident-001/arch.png"

    def test_replace_image_urls_via_service(self) -> None:
        text = "![图](PLACEHOLDER:inc-001/x.png)"
        result = self.service.replace_image_urls(text)
        assert "localhost:9000/incident-images/images/inc-001/x.png" in result

    def test_replace_image_urls_no_placeholder(self) -> None:
        text = "没有占位符的文本"
        assert self.service.replace_image_urls(text) == text

    def test_replace_image_urls_external(self) -> None:
        text = "![ext](https://example.com/img.png)"
        assert self.service.replace_image_urls(text) == text

    @patch("services.image_service.ImageService._load_mapping_file")
    def test_get_image_mapping(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {
            "incident-001": {
                "arch.png": {
                    "url": "http://localhost:9000/...",
                    "ocr_text": "架构图文字",
                    "source_doc": "incident-001",
                }
            }
        }
        result = self.service.get_image_mapping("incident-001")
        assert "arch.png" in result
        assert result["arch.png"]["ocr_text"] == "架构图文字"

    @patch("services.image_service.ImageService._load_mapping_file")
    def test_get_image_mapping_not_found(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {}
        assert self.service.get_image_mapping("nonexistent") == {}


class TestContentType:
    def test_png(self) -> None:
        assert _resolve_content_type("image.png") == "image/png"

    def test_jpg(self) -> None:
        assert _resolve_content_type("photo.jpg") == "image/jpeg"

    def test_jpeg(self) -> None:
        assert _resolve_content_type("photo.jpeg") == "image/jpeg"

    def test_unknown(self) -> None:
        assert _resolve_content_type("file.bin") == "application/octet-stream"


class TestUrlReplacerIntegration:
    """Integration-style tests for URL replacer with realistic patterns."""

    def test_summary_with_image(self) -> None:
        summary = (
            "风险评分: 75/100。"
            "参考历史事故 DELETE 缺少 WHERE 的架构图: ![SQL注入示意图](PLACEHOLDER:incident-001/sql-delete-no-where.png)"
        )
        result = replace_markdown_image_urls(summary, "http://localhost:9000", "incident-images")
        assert "http://localhost:9000/incident-images/images/incident-001/sql-delete-no-where.png" in result
        assert "PLACEHOLDER" not in result

    def test_details_with_images(self) -> None:
        details = [
            "发现1: 代码中存在风险",
            "相关监控截图: ![监控](PLACEHOLDER:incident-002/cascade-failure-monitor.png)",
        ]
        result = [
            replace_markdown_image_urls(d, "http://localhost:9000", "incident-images")
            for d in details
        ]
        assert "PLACEHOLDER" not in result[1]
        assert "incident-images/images/incident-002/cascade-failure-monitor.png" in result[1]
