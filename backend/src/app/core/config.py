import secrets
import warnings
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import AnyUrl, BeforeValidator, EmailStr, Field, PostgresDsn, computed_field, model_validator
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

    def _check_unset_secret(self, var_name: str, consequence: str) -> None:
        """Check that a secret with a default was supplied explicitly.

        A field that is absent from the environment is filled in with its default, and a default
        is never a secret. Pydantic sees nothing missing either way, so without this the difference
        between a secret someone chose and one nobody did is invisible at boot.

        Args:
            var_name: The name of the variable to check.
            consequence: What the default means for this field, for the error message.

        Raises:
            ValueError: If the variable was not set and the environment is not "local".
        """
        if var_name in self.model_fields_set:
            return

        self._report_insecure_secret(
            f"{var_name} is not set, so {consequence}. Set it explicitly, at least for deployments."
        )

    def _check_empty_secret(self, var_name: str, value: str) -> None:
        """Check that a secret is not the empty string.

        An empty string satisfies a required str field, so a secret set to nothing is
        indistinguishable from one set to something as far as pydantic is concerned.

        Args:
            var_name: The name of the variable to check.
            value: The value of the variable to check.

        Raises:
            ValueError: If the value is empty and the environment is not "local".
        """
        if value:
            return

        self._report_insecure_secret(f"{var_name} is empty. Give it a real value, at least for deployments.")

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
        """Enforce that default secrets are not used.

        Returns:
            The settings, once every secret has been checked.
        """
        # A generated key boots, but every process signs with a different one: sessions break as
        # requests land on other replicas, and every reset, verification and invite link in
        # someone's inbox stops verifying on the next restart.
        self._check_unset_secret("SECRET_KEY", "a random one was generated for this process only")
        # Set but empty is worse than unset: nothing is signed with a secret at all, and anyone can
        # mint a session token or a password reset link for any account.
        self._check_empty_secret("SECRET_KEY", self.SECRET_KEY)
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        # An empty password is legitimate where the host authenticates the connection another way,
        # with peer or trust auth, so it is the omission that is rejected rather than the value.
        self._check_unset_secret("POSTGRES_PASSWORD", "the database is being connected to with an empty password")
        self._check_default_secret("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD)
        # The seeded superuser is created from this, so an empty one hands the first account in the
        # database a hash of "" - no host authenticates that another way.
        self._check_empty_secret("FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD)
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

    # Where the investments section gets prices.
    #
    # "eodhd" is the default and needs a key, free from eodhd.com. It is the
    # one checked source that quotes European listings on a free plan, which
    # is what this feature is mostly for.
    #
    # "yahoo" needs no key and quotes nearly everything, but its endpoints are
    # unofficial and rate limit hard: a handful of requests from one address
    # earns a ban across every endpoint at once, the token handshake included.
    # It is kept as an escape hatch rather than recommended.
    #
    # "none" switches market data off. Instruments and trades are still
    # recorded, and a position is simply not valued.
    MARKET_DATA_PROVIDER: Literal["eodhd", "yahoo", "none"] = "eodhd"

    # EODHD counts one API call per ticker, not per request, so a five-holding
    # refresh spends five of a free plan's twenty daily calls. That budget is
    # what MARKET_DATA_CACHE_HOURS exists to protect.
    EODHD_API_KEY: str = ""
    EODHD_BASE_URL: str = "https://eodhd.com/api"

    # Exchange rates come from Frankfurter rather than from whoever supplies
    # prices. It is free, needs no key, publishes the European Central Bank's
    # daily rates, and asks for one request per base currency however many
    # pairs are wanted. Keeping rates off the metered provider means the whole
    # quote budget goes to quotes.
    FRANKFURTER_BASE_URL: str = "https://api.frankfurter.dev/v1"

    # How long a fetched price or rate is reused before the provider is asked
    # again. The cache is the stored price itself: an instrument records when
    # it was last priced, and a refresh inside this window is answered from the
    # database without spending an API call. Raise it if the daily budget runs
    # out; lower it only on a plan that can afford it.
    MARKET_DATA_CACHE_HOURS: float = 2.0

    YAHOO_FINANCE_BASE_URL: str = "https://query1.finance.yahoo.com"
    YAHOO_FINANCE_SEARCH_URL: str = "https://query2.finance.yahoo.com/v1/finance/search"
    # Short on purpose. A slow provider must not hold a request open: the page
    # has a cached price to fall back on, and a timeout is what makes it use it.
    MARKET_DATA_TIMEOUT_SECONDS: float = 10.0
    # Yahoo refuses the default User-Agent an HTTP library sends, so this is a
    # requirement rather than politeness.
    MARKET_DATA_USER_AGENT: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    # Delivery is retried out of the outbox table rather than in the request
    # that asked for the mail. A message is attempted at most
    # EMAIL_OUTBOX_MAX_ATTEMPTS times, waiting twice as long after each
    # failure, starting at the base delay and never exceeding the maximum.
    EMAIL_OUTBOX_MAX_ATTEMPTS: int = Field(default=6, ge=1)
    EMAIL_OUTBOX_RETRY_BASE_SECONDS: int = Field(default=60, ge=1)
    EMAIL_OUTBOX_RETRY_MAX_SECONDS: int = Field(default=3600, ge=1)  # 1 hour
    EMAIL_OUTBOX_BATCH_SIZE: int = Field(default=20, ge=1)
    # How often the background dispatcher looks for messages that came due.
    EMAIL_OUTBOX_POLL_SECONDS: int = Field(default=60, ge=1)

    # A row holds the whole rendered body of its message - the welcome mail is
    # about 11 KB - so a table that keeps every send forever grows with every
    # registration, invite and reset. Settled rows are dropped once they are
    # this old. A message that gave up is kept far longer than a delivered
    # one: it is the row somebody still has to act on.
    EMAIL_OUTBOX_SENT_RETENTION_DAYS: int = Field(default=7, ge=1)
    EMAIL_OUTBOX_FAILED_RETENTION_DAYS: int = Field(default=90, ge=1)
    # How often the background pruner applies those windows.
    EMAIL_OUTBOX_PRUNE_INTERVAL_SECONDS: int = Field(default=3600, ge=1)  # 1 hour

    EMAIL_PASSWORD_RESET_TOKEN_EXPIRE_HOURS: int = 24  # 1 day
    EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS: int = 48  # 2 days
    HOUSEHOLD_INVITE_TOKEN_EXPIRE_HOURS: int = 168  # 7 days


settings = Settings()  # type: ignore
