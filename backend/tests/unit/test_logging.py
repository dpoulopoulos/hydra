import logging

from app.logging import LOG_LEVEL_MAP, get_logger


class TestLogging:
    """Test the logging configuration and utilities."""

    def test_get_logger_returns_logger_instance(self):
        """Test that get_logger returns a logger instance with the correct name."""
        # Arrange: Set up logger name
        logger_name = "test_logger"

        # Act: Get logger instance
        logger = get_logger(logger_name)

        # Assert: Verify logger is correct type and has correct name
        assert isinstance(logger, logging.Logger)
        assert logger.name == logger_name

    def test_get_logger_with_module_name(self):
        """Test that get_logger works with __name__ pattern."""
        # Act: Get logger using module name
        logger = get_logger(__name__)

        # Assert: Verify logger is correct type and has module name
        assert isinstance(logger, logging.Logger)
        assert logger.name == __name__

    def test_log_level_map_contains_all_environments(self):
        """Test that LOG_LEVEL_MAP contains all expected environments."""
        # Assert: Verify all environment keys are present in LOG_LEVEL_MAP
        assert "local" in LOG_LEVEL_MAP
        assert "staging" in LOG_LEVEL_MAP
        assert "production" in LOG_LEVEL_MAP

    def test_log_level_map_local_is_debug(self):
        """Test that local environment uses DEBUG log level."""
        # Assert: Verify local environment is set to DEBUG
        assert LOG_LEVEL_MAP["local"] == logging.DEBUG

    def test_log_level_map_staging_is_info(self):
        """Test that staging environment uses INFO log level."""
        # Assert: Verify staging environment is set to INFO
        assert LOG_LEVEL_MAP["staging"] == logging.INFO

    def test_log_level_map_production_is_warning(self):
        """Test that production environment uses WARNING log level."""
        # Assert: Verify production environment is set to WARNING
        assert LOG_LEVEL_MAP["production"] == logging.WARNING
