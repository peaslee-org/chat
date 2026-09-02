from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import ForbiddenError
from app.dependencies import get_current_user, get_db
from app.main import app
from app.schemas.conversation import ConversationOut


@pytest.fixture
async def client():
    app.dependency_overrides[get_current_user] = lambda: {"sub": "user1"}
    app.dependency_overrides[get_db] = lambda: None
    with patch("app.db.session.init_db", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.clear()


async def test_patch_conversation_visibility(client):
    cid = uuid4()
    out = ConversationOut(
        id=cid, title="t", model_id="m", is_public=True,
        input_price_per_1k_tokens=None, output_price_per_1k_tokens=None,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    with patch("app.api.v1.endpoints.conversations.ConversationService") as cls:
        cls.return_value.set_visibility = AsyncMock(return_value=out)
        r = await client.patch(f"/api/v1/conversations/{cid}", json={"is_public": True})
    assert r.status_code == 200 and r.json()["is_public"] is True
    cls.return_value.set_visibility.assert_awaited_once_with(cid, user_sub="user1", is_public=True)


async def test_patch_conversation_not_owner_is_403(client):
    with patch("app.api.v1.endpoints.conversations.ConversationService") as cls:
        cls.return_value.set_visibility = AsyncMock(side_effect=ForbiddenError("Access denied"))
        r = await client.patch(f"/api/v1/conversations/{uuid4()}", json={"is_public": True})
    assert r.status_code == 403
