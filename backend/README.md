# Backend - FastAPI Application

A production-ready FastAPI backend with PostgreSQL, featuring user authentication, role-based access control, and a
clean layered architecture.

## Features

- **FastAPI Framework**: High-performance async web framework with automatic OpenAPI documentation
- **SQLModel ORM**: Type-safe database models combining SQLAlchemy and Pydantic
- **JWT Authentication**: Secure token-based authentication with bcrypt password hashing
- **Dependency Injection**: Clean separation of concerns with FastAPI's DI system
- **Exception Handling**: Centralized error handling with custom exception hierarchy
- **Database Migrations**: Alembic for schema version control
- **Code Quality**: Ruff formatting/linting and mypy strict type checking
- **Testing**: pytest with coverage reporting
- **Package Management**: Fast dependency resolution with uv

## Project Structure

```
backend/
├── src/app/
│   ├── api/                        # API layer
│   │   ├── deps.py                 # Dependency injection definitions
│   │   ├── main.py                 # Router aggregation
│   │   └── routes/                 # API endpoints
│   ├── core/                       # Core infrastructure
│   │   ├── config.py               # Settings and configuration
│   │   ├── db.py                   # Database setup
│   │   └── security.py             # Authentication utilities
│   ├── models/                     # Data models
│   ├── repositories/               # Data access layer
│   ├── services/                   # Business logic layer
│   ├── exceptions/                 # Custom exceptions
│   ├── templates/email/            # Transactional email templates
│   ├── scripts/                    # Utility scripts
│   │   ├── backend_pre_start.py    # Pre-startup checks
│   │   └── initial_data.py         # Initial data seeding
│   ├── alembic/                    # Database migrations
│   │   └── versions/               # Migration files
│   └── main.py                     # Application entry point
├── scripts/                        # Development scripts
├── tests/                          # Test files
├── alembic.ini                     # Alembic configuration
├── Dockerfile                      # Container image
├── pyproject.toml                  # Python dependencies and tool config
└── uv.lock                         # Dependency lock file
```

## Architecture

### Layered Design

The application follows a clean, layered architecture:

1. **API Layer** ([src/app/api/](src/app/api/))
   - FastAPI routes and endpoint definitions
   - Request/response models
   - Dependency injection setup
   - Route-specific exception mappings

2. **Service Layer** ([src/app/services/](src/app/services/))
   - Business logic and domain rules
   - Transaction boundaries: services commit, repositories do not
   - Example: [services/user.py](src/app/services/user.py)

3. **Repository Layer** ([src/app/repositories/](src/app/repositories/))
   - Query construction and data access
   - Flushes changes but leaves `commit()` to the service layer, so one service
     can span several repositories in a single transaction
   - Example: [repositories/user.py](src/app/repositories/user.py)

4. **Models Layer** ([src/app/models/](src/app/models/))
   - SQLModel database models
   - Pydantic schemas for creation, update, and responses
   - Model mixins for common fields (timestamps, primary keys)
   - Example: [models/user.py](src/app/models/user.py)

5. **Core Layer** ([src/app/core/](src/app/core/))
   - Application configuration ([config.py](src/app/core/config.py))
   - Database engine and session management ([db.py](src/app/core/db.py))
   - Security utilities ([security.py](src/app/core/security.py))

Dependencies point inwards. Services are typed against other services and
repositories, never against `app.api.deps`, so the business logic does not
depend on the web framework.

### Dependency Injection

The application uses FastAPI's dependency injection extensively:

```python
# Common dependencies (defined in api/deps.py)
SessionDep = Annotated[Session, Depends(get_db)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]

# Usage in routes
@router.get("/users/me")
def get_user_me(current_user: CurrentUser) -> UserPublic:
    return UserPublic.model_validate(current_user)
```

Key dependencies:
- `SessionDep`: Database session (auto-cleanup)
- `UserServiceDep`: UserService instance with injected session and repository
- `CurrentUser`: Authenticated user from JWT token
- `get_current_active_superuser`: Superuser verification

### Exception Handling

Custom exceptions are mapped to HTTP status codes in each route module:

```python
# In routes/users.py
def user_exception_mappings() -> dict[type[ServiceError], int]:
    return {
        UserNotFoundError: status.HTTP_404_NOT_FOUND,
        UserExistsError: status.HTTP_409_CONFLICT,
        PasswordUnmodifiedError: status.HTTP_400_BAD_REQUEST,
    }
```

These mappings are registered globally in [main.py](src/app/main.py), providing consistent error responses across the
API.

### Models and Schemas

Models use mixins for common fields:

```python
from app.models.mixins import PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin

class User(UserBase, PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, table=True):
    hashed_password: str
```

Separate schemas for different operations:
- `UserCreate`: Fields required for creation
- `UserUpdate`: Fields that can be updated
- `UserPublic`: Safe fields for API responses

Password fields use the `Password` type from [models/fields.py](src/app/models/fields.py), which bounds them to the 72
bytes bcrypt is able to hash. The bound is checked against the UTF-8 encoded length as well as the character count,
since non-ASCII characters encode to more than one byte.

## Getting Started

### Prerequisites

- Python 3.13+
- PostgreSQL 13+
- uv (recommended) or pip

### Installation

1. Install dependencies with uv (recommended):

   ```bash
   uv sync
   ```

   This installs the `dev` dependency group as well. Use `--no-dev` for a runtime-only environment.

2. Set up environment variables:

   ```bash
   # From the repository root
   cp .env.example .env
   # Edit .env with your settings
   ```

   The application, alembic and the test suite all read the `.env` file at the repository root, resolved relative to
   the package rather than the working directory.

3. Create the database and run migrations:

   ```bash
   # Start a local Postgres, for example
   docker run -d --name reeligion-db -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=app -p 5432:5432 postgres:18

   # Run migrations
   uv run alembic upgrade head

   # Create initial superuser
   uv run python src/app/scripts/initial_data.py
   ```

### Development

Start the development server:

```bash
uv run fastapi dev src/app/main.py
```

The API will be available at:
- API: http://localhost:8000
- Interactive docs: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Development Scripts

```bash
./scripts/format.sh   # Format and autofix
./scripts/lint.sh     # mypy and ruff
./scripts/test.sh     # Tests with coverage
```

These are also available as `make format`, `make lint` and `make test-unit` from the repository root.

### Running in Docker

The compose stack at the repository root runs the backend together with Postgres and a mail catcher. From the
repository root:

```bash
make dev
```

That builds the image and starts everything, and then keeps watching the source tree:

- editing anything under `backend/src/app` syncs the change into the running container, which the server's reloader
  picks up in a couple of seconds
- editing `backend/pyproject.toml` or `backend/uv.lock` rebuilds the image, since dependencies cannot be hot swapped

Other targets:

```bash
make stop        # Stop the stack
make clean       # Stop and remove containers, networks, volumes and images
make logs        # Follow the backend logs
make format      # Format Python files
make lint        # mypy and ruff
make test-unit   # Tests with coverage
```

Services and ports:

| Service | Port | Notes |
|---------|------|-------|
| backend | 8000 | API and docs |
| backend | 5678 | Free for attaching a debugger, see below |
| db | 5432 | Postgres |
| mailcatcher | 1080 | Web UI for mail sent by the app |
| mailcatcher | 1025 | SMTP endpoint |

The stack reads the `.env` file at the repository root, overriding `POSTGRES_SERVER` and `SMTP_HOST` so the
containers reach each other over the compose network. `make dev` fails with an explanatory message if that file is
missing.

## Configuration

Configuration is managed through [src/app/core/config.py](src/app/core/config.py) using Pydantic Settings, and loaded
from the `.env` file at the repository root. Every supported variable is documented in
[.env.example](../.env.example).

Key settings:

| Setting | Description | Default |
|---------|-------------|---------|
| `PROJECT_NAME` | Human readable project name | Required |
| `PROJECT_ID` | Identifier used as the JWT issuer and audience | Required |
| `SECRET_KEY` | JWT signing key | Generated per process if unset |
| `SESSION_TOKEN_EXPIRE_HOURS` | Session token lifetime | 192 (8 days) |
| `POSTGRES_SERVER` | Database host | Required |
| `POSTGRES_PORT` | Database port | `5432` |
| `POSTGRES_DB` | Database name | `""` |
| `POSTGRES_USER` | Database user | Required |
| `POSTGRES_PASSWORD` | Database password | `""` |
| `FIRST_SUPERUSER` | Seeded superuser address | Required |
| `FIRST_SUPERUSER_PASSWORD` | Seeded superuser password | Required |
| `BACKEND_CORS_ORIGINS` | Allowed CORS origins | `[]` |
| `FRONTEND_HOST` | Base URL used in email links | `http://localhost:5173` |

The `Settings` class validates that "changethis" values are not used outside the `local` environment, where it warns
instead.

## Database Migrations

### Creating Migrations

After modifying models:

```bash
# Auto-generate migration
uv run alembic revision --autogenerate -m "add user role field"

# Review the generated migration in src/app/alembic/versions/
# Edit if needed, then apply:
uv run alembic upgrade head
```

Autogenerate compares the live database against `SQLModel.metadata`, so a model that is not imported from
`app.models` will not be detected.

### Managing Migrations

```bash
uv run alembic current      # Show current version
uv run alembic history      # Show migration history
uv run alembic upgrade head # Upgrade to latest
uv run alembic downgrade -1 # Rollback one version
```

### Migration Best Practices

- Always review auto-generated migrations
- Test migrations on a copy of production data
- Include both `upgrade()` and `downgrade()` operations
- Drop enum types explicitly in `downgrade()`. Alembic drops the table but leaves the Postgres enum behind, so
  without this a downgrade followed by an upgrade fails with `DuplicateObject`
- Never edit applied migrations

## Authentication

### JWT Token Flow

1. **Login**: POST to `/api/v1/login/access-token` with credentials

   ```bash
   curl -X POST "http://localhost:8000/api/v1/login/access-token" \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "username=admin@example.com&password=changethis"
   ```

2. **Response**: JWT token in JSON

   ```json
   {
     "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
     "token_type": "bearer"
   }
   ```

3. **Authenticated Requests**: Include token in Authorization header

   ```bash
   curl "http://localhost:8000/api/v1/users/me" \
     -H "Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc..."
   ```

Tokens are typed. A session token is not accepted where a password reset or email verification token is expected, and
the issuer and audience are both derived from `PROJECT_ID`.

### Registration and Email Verification

Accounts created through `/api/v1/users/signup` start inactive and receive a verification email. Logging in before
verifying returns 403 with a message asking the user to verify. Accounts created by a superuser through
`/api/v1/users/` are active immediately and receive a welcome email.

### Password Management

- Passwords are hashed with bcrypt (cost factor 12) via pwdlib
- Passwords are bounded to 72 bytes, the most bcrypt can hash
- Users can update their own password
- Users can request password reset links by email

Password reset and verification resend endpoints return the same response whether or not the address is registered,
so they cannot be used to enumerate accounts.

### Protected Routes

Use dependency injection for authentication:

```python
@router.get("/users/me")
def get_user_me(current_user: CurrentUser) -> UserPublic:
    """Get current authenticated user."""
    return UserPublic.model_validate(current_user)

@router.get("/admin/stats", dependencies=[Depends(get_current_active_superuser)])
def get_stats() -> dict:
    """Admin-only endpoint."""
    return {"users": 42}
```

## Testing

### Running Tests

```bash
# Run all tests with coverage
./scripts/test.sh

# Run specific test file
uv run pytest tests/unit/api/routes/test_users.py

# Run with verbose output
uv run pytest -v
```

Tests are unit tests: the database session is mocked, so no Postgres instance is required.

### Writing Tests

Use the fixtures in [tests/conftest.py](tests/conftest.py) for common setup:

```python
def test_get_user_me(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/users/me", headers=auth_headers)
    assert response.status_code == 200
```

## Code Quality

### Formatting

Ruff is used for code formatting (120 character line length):

```bash
uv run ruff format --check src   # Check formatting
uv run ruff format src           # Format code
```

### Linting

```bash
uv run ruff check src            # Run linter
uv run ruff check --fix src      # Fix auto-fixable issues
```

Enabled rules (see [pyproject.toml](pyproject.toml)):
- E, W: pycodestyle errors and warnings
- F: pyflakes
- I: isort (import sorting)
- B: flake8-bugbear
- C4: flake8-comprehensions
- UP: pyupgrade
- ARG001: unused function arguments
- T201: no print statements

### Type Checking

mypy runs in strict mode:

```bash
uv run mypy src
```

Configuration in [pyproject.toml](pyproject.toml):
- `strict = true`: Enables all strict checks
- Excludes: venv, .venv, alembic

## Adding New Features

### Adding a New Model

1. Create the model in `src/app/models/` and export it from `models/__init__.py` so alembic can see it:

   ```python
   # src/app/models/post.py
   import uuid
   from sqlmodel import Field, SQLModel

   from .mixins import CreatedAtMixin, PrimaryKeyMixin, UpdatedAtMixin

   class PostBase(SQLModel):
       title: str = Field(max_length=255)
       content: str

   class Post(PostBase, PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, table=True):
       user_id: uuid.UUID = Field(foreign_key="user.id", ondelete="CASCADE")
   ```

2. Create the migration:

   ```bash
   uv run alembic revision --autogenerate -m "add post model"
   uv run alembic upgrade head
   ```

### Adding a New Repository and Service

1. Add a repository in `src/app/repositories/`, subclassing `BaseRepository[Post]`, and export it.
2. Add a service in `src/app/services/` that takes the session and the repository, and owns the `commit()`.
3. Add the dependencies in `src/app/api/deps.py`:

   ```python
   def get_post_repository(session: SessionDep) -> PostRepository:
       return PostRepository(session=session)

   PostRepositoryDep = Annotated[PostRepository, Depends(get_post_repository)]

   def get_post_service(session: SessionDep, post_repository: PostRepositoryDep) -> PostService:
       return PostService(session=session, post_repository=post_repository)

   PostServiceDep = Annotated[PostService, Depends(get_post_service)]
   ```

### Adding a New Route

1. Create the route file in `src/app/api/routes/`, exposing a `router` and a `*_exception_mappings()` function.
2. Register the router in `src/app/api/main.py`.
3. Add the mappings to the `exception_mappings` list in `src/app/main.py`, so the domain errors it raises are
   translated to status codes.

## Debugging

### Logging

Use the logger created by the [logging module](src/app/logging.py):

```python
from app.logging import get_logger

logger = get_logger(__name__)
```

The level follows `ENVIRONMENT`: DEBUG locally, INFO in staging, WARNING in production.

### Using debugpy

`debugpy` is available in the dev dependency group, so a process can be started under it when a debugger is needed:

```bash
uv run python -m debugpy --listen 0.0.0.0:5678 -m fastapi run src/app/main.py
```

## Docstring Style

Use Google-style docstrings in imperative mode:

```python
def create_user(self, user_create: UserCreate) -> UserPublic:
    """Create a new user.

    Args:
        user_create: The user creation data.

    Returns:
        The created user.

    Raises:
        UserExistsError: If a user with the same email already exists.
    """
```

## Production Considerations

- Set strong `SECRET_KEY` (use `openssl rand -hex 32`)
- Use managed PostgreSQL service
- Enable connection pooling
- Set up proper logging and monitoring
- Configure rate limiting
- Use HTTPS only
- Set restrictive CORS origins
- Regular security updates
- Database backups
- Health check endpoints

## Troubleshooting

### Database Connection Issues

```bash
# Test database connection
uv run python src/app/scripts/backend_pre_start.py
```

### Settings Fail to Load

A `ValidationError` naming `PROJECT_NAME`, `POSTGRES_SERVER` or similar on startup usually means the `.env` file at
the repository root is missing. Copy it from `.env.example`.

### Import Errors

Ensure you are running from the backend directory and using `uv run`, or have activated the virtual environment.

## Additional Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLModel Documentation](https://sqlmodel.tiangolo.com/)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [uv Documentation](https://docs.astral.sh/uv/)
