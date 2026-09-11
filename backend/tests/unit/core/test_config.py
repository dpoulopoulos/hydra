import warnings

import pytest

from app.core.config import Settings, parse_cors


class TestSettings:
    """Test the Settings class."""

    def test_settings_with_valid_env(self, base_settings_env: None) -> None:
        """Test that settings load correctly with valid environment variables."""
        # Act: Create settings instance with environment variables
        settings = Settings()  # type: ignore

        # Assert: Verify all settings are loaded correctly
        assert settings.PROJECT_NAME == "Test Project"
        assert settings.POSTGRES_SERVER == "localhost"
        assert settings.POSTGRES_USER == "test_user"
        assert settings.POSTGRES_PASSWORD == "secure_password"
        assert settings.POSTGRES_DB == "test_db"
        assert settings.FIRST_SUPERUSER == "admin@example.com"
        assert settings.FIRST_SUPERUSER_PASSWORD == "secure_password"
        assert settings.ENVIRONMENT == "local"
        assert settings.SESSION_TOKEN_EXPIRE_HOURS == 24 * 8
        assert settings.API_V1_STR == "/api/v1"

    def test_sqlalchemy_database_uri(self, base_settings_env: None) -> None:
        """Test that the database URI is constructed correctly."""
        # Act: Create settings instance and get database URI
        settings = Settings()  # type: ignore

        # Assert: Verify the database URI is constructed correctly
        expected_uri = "postgresql+psycopg://test_user:secure_password@localhost:5432/test_db"
        assert str(settings.SQLALCHEMY_DATABASE_URI) == expected_uri

    def test_default_secret_warning_in_local_environment(
        self, base_settings_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that a warning is issued for default secrets in local environment."""
        # Arrange: Set up environment with default secret key
        monkeypatch.setenv("SECRET_KEY", "changethis")

        # Act: Create settings instance and capture warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Settings()  # type: ignore

            # Assert: Verify warning was issued for default SECRET_KEY
            assert len(w) >= 1
            assert any("SECRET_KEY" in str(warning.message) for warning in w)

    def test_default_secret_error_in_staging_environment(
        self, base_settings_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that an error is raised for default secrets in staging environment."""
        # Arrange: Set up staging environment with default secret key
        monkeypatch.setenv("SECRET_KEY", "changethis")
        monkeypatch.setenv("ENVIRONMENT", "staging")

        # Act & Assert: Verify ValueError is raised for default SECRET_KEY
        with pytest.raises(ValueError) as exc_info:
            Settings()  # type: ignore

        assert "SECRET_KEY" in str(exc_info.value)
        assert "changethis" in str(exc_info.value)

    def test_default_secret_error_in_production_environment(
        self, base_settings_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that an error is raised for default secrets in production environment."""
        # Arrange: Set up production environment with default secret key
        monkeypatch.setenv("SECRET_KEY", "changethis")
        monkeypatch.setenv("ENVIRONMENT", "production")

        # Act & Assert: Verify ValueError is raised for default SECRET_KEY
        with pytest.raises(ValueError) as exc_info:
            Settings()  # type: ignore

        assert "SECRET_KEY" in str(exc_info.value)
        assert "changethis" in str(exc_info.value)

    def test_unset_secret_key_warning_in_local_environment(
        self, base_settings_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that an unset SECRET_KEY only warns in the local environment."""
        # Arrange: Remove SECRET_KEY so the generated default is used
        monkeypatch.delenv("SECRET_KEY", raising=False)

        # Act: Create settings instance and capture warnings, ignoring any .env at the repository root
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            settings = Settings(_env_file=None)  # type: ignore

            # Assert: Verify a key was generated and the omission was reported
            assert settings.SECRET_KEY
            assert any("SECRET_KEY" in str(warning.message) for warning in w)

    def test_unset_secret_key_error_in_staging_environment(
        self, base_settings_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that an unset SECRET_KEY is rejected in the staging environment."""
        # Arrange: Set up staging environment without a SECRET_KEY
        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "staging")

        # Act & Assert: Verify ValueError is raised for the missing SECRET_KEY
        with pytest.raises(ValueError) as exc_info:
            Settings(_env_file=None)  # type: ignore

        assert "SECRET_KEY" in str(exc_info.value)

    def test_unset_secret_key_error_in_production_environment(
        self, base_settings_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that an unset SECRET_KEY is rejected in the production environment."""
        # Arrange: Set up production environment without a SECRET_KEY
        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "production")

        # Act & Assert: Verify ValueError is raised for the missing SECRET_KEY
        with pytest.raises(ValueError) as exc_info:
            Settings(_env_file=None)  # type: ignore

        assert "SECRET_KEY" in str(exc_info.value)

    def test_explicit_secret_key_accepted_in_production_environment(
        self, base_settings_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that an explicit SECRET_KEY boots the production environment."""
        # Arrange: Set up production environment with an explicit SECRET_KEY
        monkeypatch.setenv("SECRET_KEY", "an-explicit-production-key")
        monkeypatch.setenv("ENVIRONMENT", "production")

        # Act: Create settings instance
        settings = Settings(_env_file=None)  # type: ignore

        # Assert: Verify the explicit key was kept
        assert settings.SECRET_KEY == "an-explicit-production-key"

    def test_empty_secret_key_warning_in_local_environment(
        self, base_settings_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that an empty SECRET_KEY only warns in the local environment."""
        # Arrange: Set an empty SECRET_KEY
        monkeypatch.setenv("SECRET_KEY", "")

        # Act: Create settings instance and capture warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Settings(_env_file=None)  # type: ignore

            # Assert: Verify the empty key was reported
            assert any("SECRET_KEY" in str(warning.message) for warning in w)

    def test_empty_secret_key_error_in_staging_environment(
        self, base_settings_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that an empty SECRET_KEY is rejected in the staging environment."""
        # Arrange: Set up staging environment with an empty SECRET_KEY
        monkeypatch.setenv("SECRET_KEY", "")
        monkeypatch.setenv("ENVIRONMENT", "staging")

        # Act & Assert: Verify ValueError is raised for the empty SECRET_KEY
        with pytest.raises(ValueError) as exc_info:
            Settings(_env_file=None)  # type: ignore

        assert "SECRET_KEY" in str(exc_info.value)

    def test_empty_secret_key_error_in_production_environment(
        self, base_settings_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that an empty SECRET_KEY is rejected in the production environment."""
        # Arrange: Set up production environment with an empty SECRET_KEY
        monkeypatch.setenv("SECRET_KEY", "")
        monkeypatch.setenv("ENVIRONMENT", "production")

        # Act & Assert: Verify ValueError is raised for the empty SECRET_KEY
        with pytest.raises(ValueError) as exc_info:
            Settings(_env_file=None)  # type: ignore

        assert "SECRET_KEY" in str(exc_info.value)

    def test_unset_postgres_password_warning_in_local_environment(
        self, base_settings_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that an unset POSTGRES_PASSWORD only warns in the local environment."""
        # Arrange: Remove POSTGRES_PASSWORD so the empty default is used
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

        # Act: Create settings instance and capture warnings, ignoring any .env at the repository root
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            settings = Settings(_env_file=None)  # type: ignore

            # Assert: Verify the empty default was kept and the omission was reported
            assert settings.POSTGRES_PASSWORD == ""
            assert any("POSTGRES_PASSWORD" in str(warning.message) for warning in w)

    def test_unset_postgres_password_error_in_staging_environment(
        self, base_settings_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that an unset POSTGRES_PASSWORD is rejected in the staging environment."""
        # Arrange: Set up staging environment without a POSTGRES_PASSWORD
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "staging")

        # Act & Assert: Verify ValueError is raised for the missing POSTGRES_PASSWORD
        with pytest.raises(ValueError) as exc_info:
            Settings(_env_file=None)  # type: ignore

        assert "POSTGRES_PASSWORD" in str(exc_info.value)

    def test_unset_postgres_password_error_in_production_environment(
        self, base_settings_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that an unset POSTGRES_PASSWORD is rejected in the production environment."""
        # Arrange: Set up production environment without a POSTGRES_PASSWORD
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "production")

        # Act & Assert: Verify ValueError is raised for the missing POSTGRES_PASSWORD
        with pytest.raises(ValueError) as exc_info:
            Settings(_env_file=None)  # type: ignore

        assert "POSTGRES_PASSWORD" in str(exc_info.value)

    def test_explicit_empty_postgres_password_accepted_in_production_environment(
        self, base_settings_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that an explicitly empty POSTGRES_PASSWORD boots the production environment.

        A host that authenticates the database connection another way, with peer or trust auth,
        legitimately has no password to give. Saying so explicitly is the difference between that
        and forgetting to set one.
        """
        # Arrange: Set up production environment with an explicitly empty POSTGRES_PASSWORD
        monkeypatch.setenv("POSTGRES_PASSWORD", "")
        monkeypatch.setenv("ENVIRONMENT", "production")

        # Act: Create settings instance
        settings = Settings(_env_file=None)  # type: ignore

        # Assert: Verify the empty password was accepted
        assert settings.POSTGRES_PASSWORD == ""

    def test_empty_first_superuser_password_warning_in_local_environment(
        self, base_settings_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that an empty FIRST_SUPERUSER_PASSWORD only warns in the local environment."""
        # Arrange: Set an empty FIRST_SUPERUSER_PASSWORD
        monkeypatch.setenv("FIRST_SUPERUSER_PASSWORD", "")

        # Act: Create settings instance and capture warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Settings(_env_file=None)  # type: ignore

            # Assert: Verify the empty password was reported
            assert any("FIRST_SUPERUSER_PASSWORD" in str(warning.message) for warning in w)

    def test_empty_first_superuser_password_error_in_staging_environment(
        self, base_settings_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that an empty FIRST_SUPERUSER_PASSWORD is rejected in the staging environment."""
        # Arrange: Set up staging environment with an empty FIRST_SUPERUSER_PASSWORD
        monkeypatch.setenv("FIRST_SUPERUSER_PASSWORD", "")
        monkeypatch.setenv("ENVIRONMENT", "staging")

        # Act & Assert: Verify ValueError is raised for the empty FIRST_SUPERUSER_PASSWORD
        with pytest.raises(ValueError) as exc_info:
            Settings(_env_file=None)  # type: ignore

        assert "FIRST_SUPERUSER_PASSWORD" in str(exc_info.value)

    def test_empty_first_superuser_password_error_in_production_environment(
        self, base_settings_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that an empty FIRST_SUPERUSER_PASSWORD is rejected in the production environment."""
        # Arrange: Set up production environment with an empty FIRST_SUPERUSER_PASSWORD
        monkeypatch.setenv("FIRST_SUPERUSER_PASSWORD", "")
        monkeypatch.setenv("ENVIRONMENT", "production")

        # Act & Assert: Verify ValueError is raised for the empty FIRST_SUPERUSER_PASSWORD
        with pytest.raises(ValueError) as exc_info:
            Settings(_env_file=None)  # type: ignore

        assert "FIRST_SUPERUSER_PASSWORD" in str(exc_info.value)

    def test_explicit_first_superuser_password_accepted_in_production_environment(
        self, base_settings_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that a real FIRST_SUPERUSER_PASSWORD boots the production environment."""
        # Arrange: Set up production environment with a real FIRST_SUPERUSER_PASSWORD
        monkeypatch.setenv("FIRST_SUPERUSER_PASSWORD", "an-explicit-production-password")
        monkeypatch.setenv("ENVIRONMENT", "production")

        # Act: Create settings instance
        settings = Settings(_env_file=None)  # type: ignore

        # Assert: Verify the password was kept
        assert settings.FIRST_SUPERUSER_PASSWORD == "an-explicit-production-password"


class TestParseCors:
    """Test the parse_cors function."""

    def test_parse_cors_with_comma_separated_string(self) -> None:
        """Test that parse_cors correctly parses comma-separated string into a list."""
        # Arrange: Set up a comma-separated string of CORS origins
        cors_string = "http://localhost:3000, http://localhost:5173"

        # Act: Parse the comma-separated string
        result = parse_cors(cors_string)

        # Assert: Verify the string was parsed into a list with whitespace stripped
        assert result == ["http://localhost:3000", "http://localhost:5173"]

    def test_parse_cors_with_list_input(self) -> None:
        """Test that parse_cors returns list as-is when input is already a list."""
        # Arrange: Set up a list of CORS origins
        cors_list = ["http://localhost:3000", "http://localhost:5173"]

        # Act: Parse the list input
        result = parse_cors(cors_list)

        # Assert: Verify the list is returned unchanged
        assert result == cors_list

    def test_parse_cors_with_json_array_string(self) -> None:
        """Test that parse_cors returns JSON array string as-is when string starts with '['."""
        # Arrange: Set up a JSON array string starting with '['
        cors_json = '["http://localhost:3000", "http://localhost:5173"]'

        # Act: Parse the JSON array string
        result = parse_cors(cors_json)

        # Assert: Verify the JSON string is returned unchanged
        assert result == cors_json

    def test_parse_cors_with_invalid_input(self) -> None:
        """Test that parse_cors raises ValueError for invalid input types."""
        # Arrange: Set up an invalid input type (integer)
        invalid_input = 12345

        # Act & Assert: Verify ValueError is raised for non-string/non-list input
        with pytest.raises(ValueError) as exc_info:
            parse_cors(invalid_input)

        assert str(exc_info.value) == "12345"
