from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BackportConfigPayload(BaseModel):
    project_url: str = ""
    project_dir: str = ""
    source_branch: str = ""
    target_path: str = ""
    target_release: str = ""
    patch_dataset_dir: str = ""
    signer_name: str = ""
    signer_email: str = ""
    current_excel_path: str = ""
    current_report_path: str = ""
    current_filtered_report_path: str = ""


class BackportConfigUpdateResponse(BaseModel):
    ok: bool
    config_path: str = ""


class BackportRunRequest(BaseModel):
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)


class BackportToolSnapshotResponse(BaseModel):
    tool_name: str
    arguments_text: str
    response_text: str
    is_error: bool


class BackportRunResponse(BaseModel):
    agentId: str
    agentName: str
    sessionId: str
    assistantText: str
    parsedResult: dict[str, Any] | None = None
    toolSnapshots: list[BackportToolSnapshotResponse] = Field(default_factory=list)
