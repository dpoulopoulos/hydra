import secrets
import warnings
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import AnyUrl, BeforeValidator, EmailStr, PostgresDsn, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    """Application settings.

    These settings are loaded from the .env file at the repository root.
    """

    model_config = SettingsConfigDict(
        # Resolve the repository root from this file rather than the working
        # directory, so the app, alembic and the tests all read the same file:
        # <root>/backend/src/app/core/config.py -> parents[4] is <root>.
        # In a container the backend is copied without the repository around it,
        # so no file is found and the settings come from the environment instead.
        env_file=Path(__file__).parents[4] / ".env",
        env_ignore_empty=False,
        extra="ignore",
    )

    def _report_insecure_secret(self, message: str) -> None:
        """Report a secret that is not fit for a deployment.

        Local development is expected to run on placeholders, so there the finding is a warning.
        Anywhere else it stops the process, because a deployment that boots on a placeholder gives
        no other sign that it did.

        Args:
            message: What is wrong with the secret, and what to do about it.

        Raises:
            ValueError: If the environment is not "local".
        """
        if self.ENVIRONMENT == "local":
            warnings.warn(message, stacklevel=1)
        else:
            raise ValueError(message)

    def _check_unset_secret(self, var_name: str) -> None:
        """Check that a secret with a generated default was supplied explicitly.

        A field that is absent from the environment is filled in with its default, which for
        SECRET_KEY is a fresh random token. That boots, but every process signs with a different
        key: sessions break as requests land on other replicas, and every reset, verification and
        invite link in someone's inbox stops verifying on the next restart.

        Args:
            var_name: The name of the variable to check.

        Raises:
            ValueError: If the variable was not set and the environment is not "local".
        """
        if var_name in self.model_fields_set:
            return

        self._report_insecure_secret(
            f"{var_name} is not set, so a random one was generated for this process only. "
            "Set it explicitly, at least for deployments."
        )

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        """Check for default secret values.

        Args:
            var_name: The name of the variable to check.
            value: The value of the variable to check.

        Raises:
            ValueError: If the value is "changethis" and the environment is not "local".
        """
        if value == "changethis":
            self._report_insecure_secret(
                f'The value of {var_name} is "changethis", for security, please change it, at least for deployments.'
            )

    PROJECT_NAME: str
    PROJECT_ID: str

    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = secrets.token_urlsafe(32)
    SESSION_TOKEN_EXPIRE_HOURS: int = 24 * 8  # 8 days
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"

    BACKEND_HOST: str = "http://localhost:8000"
    BACKEND_CORS_ORIGINS: Annotated[list[AnyUrl] | str, BeforeValidator(parse_cors)] = []

    FRONTEND_HOST: str = "http://localhost:5173"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> list[str]:
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS] + [self.FRONTEND_HOST]

    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
        """Get the SQLAlchemy database URI.

        Returns:
            The SQLAlchemy database URI.
        """
        return PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )

    FIRST_SUPERUSER: EmailStr
    FIRST_SUPERUSER_PASSWORD: str

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        """Enforce that default secrets are not used."""
        self._check_unset_secret("SECRET_KEY")
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        self._check_default_secret("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD)
        self._check_default_secret("FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD)

        return self

    # How mail leaves the app. "smtp" talks to a mail server, which is what the
    # local mail catcher offers. "resend" posts to an HTTPS API instead, for
    # hosts that block outgoing SMTP.
    EMAIL_PROVIDER: Literal["smtp", "resend"] = "smtp"
    RESEND_API_KEY: str | None = None

    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 587
    SMTP_HOST: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: EmailStr | None = None
    # A display name, not an address: it is used as the name half of the From header.
    EMAILS_FROM_NAME: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        if not self.EMAILS_FROM_EMAIL:
            return False
        if self.EMAIL_PROVIDER == "resend":
            return bool(self.RESEND_API_KEY)
        return bool(self.SMTP_HOST)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def assets_base_url(self) -> str:
        return f"{str(self.BACKEND_HOST).rstrip('/')}/assets"

    EMAIL_PASSWORD_RESET_TOKEN_EXPIRE_HOURS: int = 24  # 1 day
    EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS: int = 48  # 2 days
    HOUSEHOLD_INVITE_TOKEN_EXPIRE_HOURS: int = 168  # 7 days


settings = Settings()  # type: ignore
