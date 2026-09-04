from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from schemas.api.request import ReviewRequest
from schemas.domain.enums import ReviewMode


def _infer_virtual_path(diff_content: str) -> str:
    upper_diff = diff_content.upper()
    if any(
        keyword in upper_diff
        for keyword in (
            "SELECT",
            "INSERT",
            "UPDATE",
            "DELETE",
            "CREATE TABLE",
            "ALTER TABLE",
            "DROP TABLE",
        )
    ):
        return "changes.sql"
    if (
        "@REQUESTMAPPING" in upper_diff
        or "@GETMAPPING" in upper_diff
        or "@POSTMAPPING" in upper_diff
    ):
        return "controller.diff"
    if "SERVICE" in upper_diff:
        return "service.diff"
    return "diff.patch"


class BackendSyncRequest(BaseModel):
    projectId: str
    projectName: str
    prUrl: str
    diffContent: str
    mode: ReviewMode
    taskId: UUID | None = None
    entities: list[dict] | None = None
    relations: list[dict] | None = None

    def to_review_request(self, trace_id: str) -> ReviewRequest:
        kwargs: dict = dict(
            projectId=self.projectId,
            repo=self.prUrl,
            branch="unknown",
            diffUrl=self.prUrl,
            files=[
                {
                    "path": _infer_virtual_path(self.diffContent),
                    "diff": self.diffContent,
                }
            ],
            mode=self.mode,
            riskPreferences={},
            metadata={"projectName": self.projectName, "source": "java-backend"},
            traceId=trace_id,
            entities=self.entities,
            relations=self.relations,
        )
        if self.taskId is not None:
            kwargs["taskId"] = self.taskId
        return ReviewRequest(**kwargs)


class BackendAsyncTaskMessage(BackendSyncRequest):
    taskId: UUID
    traceId: str

    def to_review_request(self) -> ReviewRequest:
        request = super().to_review_request(self.traceId)
        return request.model_copy(
            update={"taskId": self.taskId, "mode": ReviewMode.ASYNC}
        )


def parse_sync_payload(payload: dict, trace_id: str) -> ReviewRequest:
    if "files" in payload:
        normalized = dict(payload)
        normalized["traceId"] = normalized.get("traceId") or trace_id
        return ReviewRequest(**normalized)
    return BackendSyncRequest(**payload).to_review_request(trace_id)


def parse_async_payload(payload: dict) -> ReviewRequest:
    if "files" in payload:
        return ReviewRequest(**payload)
    return BackendAsyncTaskMessage(**payload).to_review_request()
