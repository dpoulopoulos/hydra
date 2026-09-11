from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for the MCP server.

    Read from the environment, and from the .env file at the repository root
    when there is one, so a developer running this outside a container gets the
    same values the compose stack hands the container.
    """

    model_config = SettingsConfigDict(
        env_file="../.env",
        env_ignore_empty=True,
        extra="ignore",
    )

    # Where hydra's API lives. Inside compose this is overridden to reach the
    # backend over the compose network rather than the host.
    HYDRA_API_BASE_URL: AnyHttpUrl = AnyHttpUrl("http://localhost:8000")
    HYDRA_API_PREFIX: str = "/api/v1"

    # The public URL of this server's MCP endpoint. It is what a token is
    # nominally issued for, and it has to match what a client connects to.
    MCP_RESOURCE_URL: AnyHttpUrl = AnyHttpUrl("http://localhost:8002/mcp")

    MCP_HOST: str = "0.0.0.0"  # noqa: S104
    MCP_PORT: int = 8002
    MCP_PATH: str = "/mcp"

    HYDRA_REQUEST_TIMEOUT_SECONDS: float = 30.0
    # How long a checked token is trusted without asking hydra again. Short,
    # because this is what decides how quickly a revoked token stops working.
    TOKEN_CACHE_SECONDS: float = 30.0

    @property
    def api_root(self) -> str:
        """The base every request is built on.

        Returns:
            The API base URL and version prefix, without a trailing slash.
        """
        return f"{str(self.HYDRA_API_BASE_URL).rstrip('/')}{self.HYDRA_API_PREFIX}"


settings = Settings()
