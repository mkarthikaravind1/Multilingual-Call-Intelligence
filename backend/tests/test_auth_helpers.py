import time

from fastapi.testclient import TestClient

from app.api.app_factory import create_app
from app.domain.user import User, UserRole
from app.security.jwt import create_access_token


def authenticate_client(
    services,
    role: UserRole = UserRole.ICR,
) -> tuple[TestClient, str]:
    app = create_app(services)

    user = User(
        user_id=f"test-{role.value.lower()}",
        email=f"test-{role.value.lower()}@example.com",
        password_hash="test-password-hash",
        role=role,
        is_active=True,
        created_at=time.time(),
    )

    app.state.services.user_repository.save(user)

    token = create_access_token(user)

    client = TestClient(
        app,
        headers={"Authorization": f"Bearer {token}"},
    )

    return client, token