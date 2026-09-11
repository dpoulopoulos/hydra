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
│   ├── data/                       # Static seed data (default categories)
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

   Entities owned by a household extend `HouseholdScopedRepository` instead of `BaseRepository`. It puts
   `household_id` in the `WHERE` clause of every read, so a caller can never receive a row from another household.

   > **Convention:** if a repository extends `HouseholdScopedRepository`, its service calls `get_for_household()` and
   > never the inherited `get_by_id()`, which is unscoped. A write that references another entity by ID must
   > re-resolve that ID through `get_for_household()` before using it. An ID belonging to another household is
   > reported as `404`, never `403`, so the API does not leak which IDs exist. Where the row itself is not
   > needed, `exists_for_household()` answers the same question without loading it.
   >
   > A read re-resolves its IDs too. A caller-supplied ID used as a filter goes through `get_for_household()` or
   > `exists_for_household()` before it reaches the query. The scoping already keeps another household's rows out
   > of the answer, so this is not what stops a leak; it is what stops an unknown ID from being reported as an
   > empty result. On a finance app "you spent nothing here" and "that account is gone" must not look alike.

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

Timestamp columns use the `UtcDateTime` type from [models/mixins.py](src/app/models/mixins.py), which is
`timestamptz`. Every moment the app stores is UTC and tz-aware, and the column has to record that: a plain
`DateTime` keeps the wall clock and drops the offset, so the API serialises a moment with nothing saying which zone
it is in, and ECMAScript reads a date-time in that shape as *local* time. A new timestamp column names this type,
never `datetime` on its own.

> **Convention:** a moment arriving from a caller is typed `UtcMoment` from [models/fields.py](src/app/models/fields.py),
> which reads an input naming no zone as UTC. Without it, what gets stored depends on the zone the database session
> happens to carry rather than on what was sent.

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
./scripts/format.sh           # Format and autofix
./scripts/lint.sh             # mypy and ruff
./scripts/test.sh             # Unit tests with coverage
./scripts/test-integration.sh # Integration tests, against a real Postgres
```

These are also available as `make format`, `make lint`, `make test-unit` and `make test-integration` from the
repository root.

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
make test-unit   # Unit tests with coverage
make test-integration # Integration tests, against the stack's Postgres
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
| `SECRET_KEY` | JWT signing key | Generated per process in `local`, required and non-empty elsewhere |
| `SESSION_TOKEN_EXPIRE_HOURS` | Session token lifetime | 192 (8 days) |
| `POSTGRES_SERVER` | Database host | Required |
| `POSTGRES_PORT` | Database port | `5432` |
| `POSTGRES_DB` | Database name | `""` |
| `POSTGRES_USER` | Database user | Required |
| `POSTGRES_PASSWORD` | Database password | Required outside `local`, and may be empty only when set on purpose |
| `FIRST_SUPERUSER` | Seeded superuser address | Required |
| `FIRST_SUPERUSER_PASSWORD` | Seeded superuser password | Required, and non-empty outside `local` |
| `BACKEND_CORS_ORIGINS` | Allowed CORS origins | `[]` |
| `FRONTEND_HOST` | Base URL used in email links | `http://localhost:5173` |
| `HOUSEHOLD_INVITE_TOKEN_EXPIRE_HOURS` | Household invitation lifetime | 168 (7 days) |
| `EMAIL_PROVIDER` | How mail leaves: `smtp` or `resend` | `smtp` |
| `RESEND_API_KEY` | Required when the provider is `resend` | `None` |
| `PORT` | Port the server listens on | `8000` |
| `RUN_PRESTART` | Whether the entrypoint migrates and seeds before serving | `true` |

The `Settings` class validates that "changethis" values are not used outside the `local` environment, where it warns
instead. The secrets are held to the same standard when nobody set them at all, because a field with a default is never
missing as far as pydantic is concerned, and a deployment that boots on a default gives no other sign that it did:

- `SECRET_KEY` and `POSTGRES_PASSWORD` must come from the environment. Outside `local` the app refuses to start
  otherwise. The generated `SECRET_KEY` fallback differs per process, which signs sessions with a key the next replica
  or the next restart cannot verify; `POSTGRES_PASSWORD` falls back to an empty password.
- `POSTGRES_PASSWORD` may still be empty when it was set on purpose, for a host that authenticates the connection with
  peer or trust auth and has no password to give.
- `SECRET_KEY` and `FIRST_SUPERUSER_PASSWORD` may not be empty outside `local`. An empty `SECRET_KEY` signs session
  tokens and every reset, verification and invite link with nothing, which anyone can reproduce;
  `FIRST_SUPERUSER_PASSWORD` seeds the first account in the database, and an empty value gives that account a hash of
  `""`.

`EMAIL_PROVIDER` exists because some hosts block outgoing SMTP. `smtp` talks to a mail server, which is what the local
mail catcher offers. `resend` posts to an HTTPS API instead, and needs `RESEND_API_KEY`.

`RUN_PRESTART` exists because `scripts/entrypoint.sh` migrates and seeds the database before it starts serving, which is
right for one container and wrong for several. A host that can run the migrations as its own step before the deploy sets
this to `false` and runs `scripts/prestart.sh` there instead.

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

### Data Migrations

A revision that rewrites rows rather than the schema carries two extra obligations, because unlike a column
its effect cannot be read back off the models.

- Make the statement idempotent, by restricting it to the rows it has not already written. A deploy can be
  retried, and a back-fill that doubles up on the second run is one nobody can re-run.
- Put the statement in a module level constant and cover it in `tests/integration`, which has a real Postgres
  to run it against. `d9f4c1b73a85_back_fill_the_category_cascade_mark.py` is the worked example: the test
  imports the revision by path and executes the constant, so what is asserted is the statement a deployment
  will run rather than a copy of it.

A back-fill that guesses is usually not reversible — the rows it wrote are indistinguishable from the ones it
left alone — so its `downgrade()` is a no-op with a comment saying why, not an inverse that would also clear
what the application has recorded since.

## Domain

The application is a personal finance manager. Everything below the household
is shared: every member of a household sees and can edit the same accounts,
categories, budgets and transactions.

| Resource | Route | Notes |
|---|---|---|
| Households | `/api/v1/households` | One household per user. Owners manage members and invitations; all money data is shared. |
| Accounts | `/api/v1/accounts` | Cash, current, savings, credit card. Balances are derived from the ledger, never stored. |
| Categories | `/api/v1/categories` | Two levels deep, seeded on household creation. |
| Transactions | `/api/v1/transactions` | Expenses, income and transfers. A transfer is one row, not two. |
| Budgets | `/api/v1/budgets` | One limit per category per month. No rollover. |
| Recurring rules | `/api/v1/recurring-rules` | Materialize real transactions; run from the read paths. |
| Income | `/api/v1/income` | Clients and sessions for work paid by the hour. A session reaches the ledger only once it is paid. Client names are stored encrypted under a per-user key and are opaque here; a client can only be edited by the member who added them. |
| Reports | `/api/v1/reports` | Spend by category, spend over time, budget vs actual, income vs expense, dashboard summary. |
| API tokens | `/api/v1/api-tokens` | Long lived credentials for machine clients. Named, scoped, revocable, and shown once. |

Deleting an account deletes the household it leaves empty. A household is only reachable through its
memberships, and everything below it is keyed on the household rather than on a user, so removing the last
member would otherwise leave the accounts, transactions, budgets and rules behind with nobody able to read
them. `HouseholdService.release_for_user` drops the membership and, when no member is left, the household,
whose financial data cascades with it. A household that still has members keeps everything: the data is
theirs too, and if the departing user was its last owner the longest-standing member is promoted, so the
household is never left without somebody who can rename it, invite, or manage members. Every exit from a
household — being removed, leaving, accepting an invite elsewhere, or deleting the account — goes through the
same path, which takes a row lock on the household first so two members going at once cannot both conclude
the other is still there.

Four conventions run through the domain and are worth knowing before changing it:

- **Money is an integer count of minor units**, on `BigInteger` columns, and every such field is named
  `*_minor`. Amounts are exact, so a budget comparison needs no tolerance, and nothing arrives at the
  frontend as a `Decimal` rendered into a JSON string. The API exposes minor units and the client formats
  them.
- **An amount is always a positive magnitude; the meaning lives in `kind`.** A sign convention cannot be
  enforced by a constraint, so a mis-signed row would be silently wrong forever, and a transfer has no
  natural single sign. The sign is applied once, in SQL. A transfer is therefore a single row with a
  `counter_account_id`, which is why every spending report is simply `kind = 'EXPENSE'` and a transfer can
  never leak into spending.
- **Account balances are computed, never stored.** A stored balance is a cache with no invalidation story
  that survives back-dated edits, re-pointed transfers and recurring runs, and a balance that has quietly
  drifted is the most damaging bug a finance app can have.
- **Every numeric bound is mirrored in SQL.** A bound on an input model turns a driver error into a 422 on
  the request path and does nothing for a script, a data migration or a service that writes a row itself.
  So each one has a `CHECK` beside it, and the expression comes from `within_cap_sql` in
  [models/fields.py](src/app/models/fields.py), rendered from the same constant the model validates
  against — so raising a bound in Python cannot leave the database on the old number. This is a rule
  rather than a habit: `tests/unit/models/test_numeric_ceilings.py` walks the models and fails on a
  bounded column with no constraint behind it.

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

Signup answers the same `200` and the same body whether or not the address already has an account, so the reply
does not say which addresses are registered. The submitted password is hashed once, before the address is looked
up, and that one hash is used by whichever path follows, so every signup pays exactly one bcrypt hash — the
dominant cost of the request — whatever the answer is. The two paths are not otherwise
constant-time: only a free address writes a user and a household, so a caller who can measure the difference
precisely may still be able to tell them apart. An address that is already taken is told about the attempt by
email instead, with links to sign in and to reset a password and no token in the message. The `409` for a
duplicate address is still raised by `/api/v1/users/`, where the caller is a superuser who may already list every
account.

An invitation is only ever read for an address that is free, so an invite token that is unknown, used, expired or
addressed to somebody else cannot be reported to the caller either: the error would answer a free address with a
404, 400 or 403 and a taken one with the shared `200`. Such a signup creates the account without the invitation,
with a household of its own, and the verification email it was going to get anyway says that the invitation was not
applied. That paragraph does not say which of the possible reasons applied and does not repeat the token. The
invitation is settled before anything is written, by `HouseholdService.check_signup_invite`, so dropping one costs
no extra hash and no repeated write, and the news about it rides on the verification email rather than a second
message. Every signup therefore does one bcrypt hash, one account write and one blocking send to the mail provider
whatever the answer is, and cannot be told apart by the clock either.

### Password Management

- Passwords are hashed with bcrypt (cost factor 12) via pwdlib
- Passwords are bounded to 72 bytes, the most bcrypt can hash
- Users can update their own password
- Users can request password reset links by email

Password reset and verification resend endpoints return the same response whether or not the address is registered,
so they cannot be used to enumerate accounts.

Login is held to the same rule. An address with no account and an account whose password does not match both answer
`401` with `Incorrect email or password.`, and the unknown address still pays for a bcrypt verification against a
throwaway hash, so neither the status code nor the response time says which addresses are registered. The `403` for an
unverified account is only reachable once the correct password has been supplied.

### API Tokens

A session token is minted for a browser: it expires in eight days and cannot be withdrawn from one client without
withdrawing it from all of them. A machine client — an MCP server, a script — needs a credential of its own, so
`/api/v1/api-tokens` mints one.

```bash
# Only a signed-in session may mint one.
curl -X POST "http://localhost:8000/api/v1/api-tokens/" \
  -H "Authorization: Bearer $SESSION_JWT" -H "Content-Type: application/json" \
  -d '{"name": "Claude Desktop", "scope": "read", "expires_in_days": 90}'
```

The credential is `hyd_<token_id>_<secret>`. Only the first half is stored, in the clear and indexed, so
authenticating is one index probe. The second half is 256 random bits and is kept only as a SHA-256 digest, which
is why the response above is the only place it ever appears.

SHA-256 rather than bcrypt, deliberately. A password hash is slow to make a human-chosen secret expensive to guess,
and there is no dictionary that reaches 256 random bits; the cost would instead be paid on every request a machine
client makes. bcrypt also caps at 72 bytes and salts, and a salted hash cannot be looked up by content, which is
what would force a scan over every row. The random `token_id` already does the lookup.

Presented as a bearer token, it reaches every route a session does:

```bash
curl "http://localhost:8000/api/v1/accounts/" -H "Authorization: Bearer hyd_..."
```

Both credentials are resolved by the same `get_current_user`, because the two cannot be confused: a JWT is base64url
of a JSON header and can never carry the `hyd_` prefix. That is what lets an API token work on every existing route
without one of them being edited, and it keeps the household scope derived from the membership row either way.

Two limits are enforced where the credential is resolved, rather than route by route, so a route added later is
covered without being told that any of this exists:

- A `read` scoped token may only make `GET`, `HEAD` and `OPTIONS` requests. Anything else is `403`. That is the
  method, not the effect: reading the transactions or a report materialises any recurring occurrence now due, so a
  read token can still cause those rows to be written. They would have appeared on the owner's next visit anyway.
- `SessionUser`, the inverse of `CurrentUser`, requires a browser session. It guards minting and revoking tokens,
  changing the password or the address, deleting the account, every change to household membership, and everything
  behind `get_current_active_superuser` — the operations a leaked token could otherwise use to entrench itself. The
  superuser routes are in that list because they create users and set any user's password, so a token reaching them
  could mint a second superuser it knew the password of.

Every way of failing answers `401` with the same message. Unknown, revoked, expired, a wrong secret and an inactive
owner are indistinguishable from outside, for the reason login does not say whether an address is registered.
Revoking flips a status rather than deleting the row, so when the token was last used survives it. `last_used_at`
is written at most every five minutes, so a chatty client does not turn each of its reads into a write.

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

The suite has two tiers, and they answer different questions.

### Unit tests

[tests/unit/](tests/unit/) mocks the database session, so no Postgres instance is required and no SQL is executed.
This is the fast tier and where most tests belong. The run fails below the coverage threshold in
[scripts/test.sh](scripts/test.sh), so coverage cannot regress unnoticed.

```bash
# Run the unit tests with coverage
./scripts/test.sh

# Run a specific test file
uv run pytest tests/unit/api/routes/test_users.py

# Run with verbose output
uv run pytest tests/unit -v
```

Use the fixtures in [tests/conftest.py](tests/conftest.py) for common setup:

```python
def test_get_user_me(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/users/me", headers=auth_headers)
    assert response.status_code == 200
```

### Integration tests

A mock enforces no constraint and runs no query, so anything that lives in SQL is invisible to the tier above it:
household scoping, the `CHECK`, `RESTRICT` and `UNIQUE` constraints -- including the unique index that makes
a materialization pass idempotent -- the composite foreign keys that pin a row to its household, and the money
arithmetic the reports and the computed balances are built from. [tests/integration/](tests/integration/)
covers those against a real server.

It is also the only tier that can check an invariant spanning two services. A mocked session gives each service
its own answers, so a write path and the report that reads what it wrote are never run over the same data.
[tests/integration/test_budget_invariant.py](tests/integration/test_budget_invariant.py) does exactly that: it
runs each budget write path and then reads the month back through the budget report, which is the shape of test
that would have caught #10.

```bash
# Needs a Postgres. `make dev` from the repository root is enough.
./scripts/test-integration.sh
```

The tests connect to the server the `POSTGRES_*` settings point at and create a database of their own next to it,
named after `POSTGRES_DB` with `_integration` appended, so running them never touches the rows of a local stack.
The schema is created from the model metadata rather than by migrating, which the migrations workflow already
proves equivalent. Each test runs inside a transaction that is rolled back afterwards, so the tests do not have to
clean up after one another.

Use the fixtures in [tests/integration/conftest.py](tests/integration/conftest.py), which give you a session, two
seeded households and every service wired to the real session:

```python
def test_a_foreign_account_is_not_found(
    db_session: Session,
    account_service: AccountService,
    household_a: HouseholdContext,
    household_b: HouseholdContext,
) -> None:
    foreign = make_account(db_session, household_id=household_b.household_id)

    with pytest.raises(AccountNotFoundError):
        account_service.get_account(household=household_a, account_id=foreign.id)
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

mypy runs in strict mode, over the sources and the tests alike:

```bash
uv run mypy src tests
```

Configuration in [pyproject.toml](pyproject.toml):
- `strict = true`: Enables all strict checks
- Excludes: venv, .venv, alembic
- `tests.*` turns off `method-assign` and `attr-defined`: a unit test patches a service method with a
  `MagicMock` and reads the recorded calls back off it, which neither code has a way to allow. The rest
  of strict mode, annotations included, holds over the suite.

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

An `Args:` section has to name exactly the parameters of the signature above it, in the same order, leaving
out `self` and `cls`. Documenting only some of them is not an option, and neither is leaving the section out
of a docstring on a function that takes parameters: a docstring either describes the whole signature or the
function goes without one.

A `Returns:` section has to be there when the function returns something, and has to be gone when it returns
`None`. A generator writes `Yields:` instead. The description itself is not checked against the value, only
whether there is one to describe.

A `Raises:` section has to name every exception the function raises itself. It may name more: most of what a
service documents is raised for it by a repository or a helper, and that is the section a caller reads to
decide what to catch, so listing what propagates is the point of it. Only what the body raises directly can
be checked, and a bare `raise` or a `raise` of a variable names no class and is not asked for.

`tests/unit/test_docstrings.py` walks the package and fails on anything else, because neither ruff nor mypy
reads a docstring.

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
