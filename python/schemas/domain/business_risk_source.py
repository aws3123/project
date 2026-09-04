from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class BusinessRiskLineMap(BaseModel):
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)


class BusinessRiskMethodSkeleton(BaseModel):
    method_id: str | None = None
    signature: str
    annotations: list[str] = Field(default_factory=list)
    control_flow_summary: list[str] = Field(default_factory=list)
    key_calls: list[str] = Field(default_factory=list)
    snippet: str | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    line_map: BusinessRiskLineMap | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_method(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if data.get("method_id") is None:
            signature = str(data.get("signature") or "method")
            start_line = (
                data.get("start_line")
                or (data.get("line_map") or {}).get("start_line")
                or 1
            )
            data["method_id"] = f"{signature}@{start_line}"
        if (
            data.get("line_map") is None
            and data.get("start_line") is not None
            and data.get("end_line") is not None
        ):
            data["line_map"] = {
                "start_line": data.get("start_line"),
                "end_line": data.get("end_line"),
            }
        if data.get("start_line") is None and data.get("line_map") is not None:
            data["start_line"] = data["line_map"].get("start_line")
        if data.get("end_line") is None and data.get("line_map") is not None:
            data["end_line"] = data["line_map"].get("end_line")
        return data


class BusinessRiskHotspot(BaseModel):
    method_id: str | None = None
    raw_snippet: str | None = None
    snippet: str | None = None
    reason: str
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    line_map: BusinessRiskLineMap | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_hotspot(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if data.get("snippet") is None and data.get("raw_snippet") is not None:
            data["snippet"] = data.get("raw_snippet")
        if data.get("raw_snippet") is None and data.get("snippet") is not None:
            data["raw_snippet"] = data.get("snippet")
        if (
            data.get("line_map") is None
            and data.get("start_line") is not None
            and data.get("end_line") is not None
        ):
            data["line_map"] = {
                "start_line": data.get("start_line"),
                "end_line": data.get("end_line"),
            }
        if data.get("start_line") is None and data.get("line_map") is not None:
            data["start_line"] = data["line_map"].get("start_line")
        if data.get("end_line") is None and data.get("line_map") is not None:
            data["end_line"] = data["line_map"].get("end_line")
        if data.get("method_id") is None:
            start_line = (
                data.get("start_line")
                or (data.get("line_map") or {}).get("start_line")
                or 1
            )
            data["method_id"] = f"hotspot@{start_line}"
        return data


class BusinessRiskSourceFile(BaseModel):
    path: str
    language: Literal["java"] = "java"
    package_name: str | None = None
    class_name: str | None = None
    annotations: list[str] = Field(default_factory=list)
    class_summary: str | None = None
    method_skeletons: list[BusinessRiskMethodSkeleton] = Field(default_factory=list)
    hotspots: list[BusinessRiskHotspot] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_file(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if data.get("method_skeletons") is None and data.get("methods") is not None:
            data["method_skeletons"] = data.pop("methods")
        return data


class BusinessRiskSourceBudget(BaseModel):
    decision: str
    raw_total_bytes: int = Field(ge=0)
    prepared_total_bytes: int = Field(ge=0)
    dropped_files: list[str] = Field(default_factory=list)


class BusinessRiskSourcePackage(BaseModel):
    file_count: int = Field(ge=0)
    files: list[BusinessRiskSourceFile] = Field(default_factory=list)
    budget: BusinessRiskSourceBudget | None = None


class BusinessRiskSourceRequest(BaseModel):
    schema_version: str
    java_preprocess_version: str
    project_id: str
    repo: str
    branch: str
    request_id: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    trace_id: str | None = None
    source_package: BusinessRiskSourcePackage | None = None
    metadata: dict = Field(default_factory=dict)
    memory_context: dict = Field(default_factory=dict)
    user_feedback_signals: dict = Field(default_factory=dict)
    dialog_turn: int | None = None
    memory_version: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_payload(cls, data):
        if not isinstance(data, dict):
            return data
        if data.get("source_package") is None and data.get("source_bundle") is not None:
            data = dict(data)
            data["source_package"] = data.pop("source_bundle")
        return data

    @model_validator(mode="after")
    def validate_package_limit(self):
        if self.source_package is None:
            raise ValueError("source_package is required")
        if len(self.source_package.files) > 200:
            raise ValueError("source_package.files exceeds max 200")
        if self.source_package.file_count != len(self.source_package.files):
            raise ValueError("file_count mismatch")
        return self
