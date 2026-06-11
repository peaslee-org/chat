"""
Unit tests for the health endpoints.

These run without a database — init_db is mocked so the lifespan
doesn't try to connect to Postgres.

The critical assertion is follow_redirects=False on the ALB path
(/api/v1/health): a 307 here means the ALB health check will mark
every task unhealthy and the service will never stabilise.
"""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    with patch("app.db.session.init_db", new_callable=AsyncMock):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac


async def test_health_returns_200(client: AsyncClient) -> None:
    """GET /api/v1/health/ must return 200 without redirecting.

    The ALB target group health check is configured at /api/v1/health/
    (infra/modules/ecs/main.tf). If this path redirects instead of
    returning 200, every task will be marked unhealthy and deploys will
    never stabilise.
    """
    response = await client.get("/api/v1/health", follow_redirects=False)
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}. "
        "A 307 here means the ALB health check path doesn't match the FastAPI route."
    )
    assert response.json()["status"] == "ok"
