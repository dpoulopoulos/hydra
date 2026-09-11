from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api.deps import get_current_active_superuser, get_current_user, get_db
from app.main import app
from app.models import EmailOutboxStats, User
from app.services import EmailOutboxService


class TestReadEmailOutboxStats:
    """Tests for the outbox stats endpoint (GET /email-outbox/stats)."""

    def test_stats_are_reported_to_a_superuser(
        self, client: TestClient, test_superuser: User, mock_db_session: MagicMock
    ) -> None:
        """This is how a deployment finds out that mail is not arriving."""

        # Arrange: Set up dependency overrides and a failing outbox
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_superuser

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_current_active_superuser] = override_get_current_user

        oldest = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
        stats = EmailOutboxStats(pending=2, failed=3, oldest_failed_at=oldest)

        try:
            with patch.object(EmailOutboxService, "stats", return_value=stats):
                # Act: Ask what the outbox is holding
                response = client.get("/api/v1/email-outbox/stats")

                # Assert: Verify the figures came back
                data = response.json()

                assert response.status_code == 200
                assert data["pending"] == 2
                assert data["failed"] == 3
                assert data["oldest_failed_at"] == "2026-03-01T12:00:00Z"
        finally:
            app.dependency_overrides.clear()

    def test_stats_are_refused_to_an_ordinary_user(
        self, client: TestClient, mock_db_session: MagicMock, auth_headers: dict[str, str], test_user: User
    ) -> None:
        """The outbox holds every address the application has written to."""

        # Arrange: Set up dependency overrides for an ordinary member
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        try:
            # Act: Ask what the outbox is holding
            response = client.get("/api/v1/email-outbox/stats", headers=auth_headers)

            # Assert: Verify the request was refused
            assert response.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_stats_need_a_session(self, client: TestClient) -> None:
        """Nothing about the outbox is public."""
        # Act: Ask what the outbox is holding without signing in
        response = client.get("/api/v1/email-outbox/stats")

        # Assert: Verify the request was refused
        assert response.status_code == 401
