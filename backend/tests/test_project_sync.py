import json

import pytest

from app.services.project_sync import ProjectSyncError, extract_project_items


def test_project_items_support_mcp_text_content() -> None:
    result = {"content": [{"type": "text", "text": json.dumps([{"id": "p1", "name": "Demo"}])}]}
    assert extract_project_items(result) == [{"id": "p1", "name": "Demo"}]


def test_project_items_support_nested_mcp_text_content() -> None:
    result = {"content": [{"type": "text", "text": json.dumps({"projects": [{"id": "p1"}]})}]}
    assert extract_project_items(result) == [{"id": "p1"}]


def test_project_items_reject_invalid_shape() -> None:
    with pytest.raises(ProjectSyncError, match="MCP_PROJECTS_RESPONSE_INVALID"):
        extract_project_items({"content": [{"type": "image", "data": "..."}]})
