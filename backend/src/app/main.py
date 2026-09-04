from collections.abc import Callable
from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ExceptionHandler

from app.api.main import api_router
from app.api.routes.accounts import account_exception_mappings
from app.api.routes.budgets import budget_exception_mappings
from app.api.routes.categories import category_exception_mappings
from app.api.routes.email_verification import email_verification_exception_mappings
from app.api.routes.households import household_exception_mappings
from app.api.routes.login import login_exception_mappings
from app.api.routes.password_reset import password_reset_exception_mappings
from app.api.routes.reports import report_exception_mappings
from app.api.routes.transactions import transaction_exception_mappings
from app.api.routes.users import user_exception_mappings
from app.core.config import settings
from app.exceptions import ServiceError


def custom_generate_unique_id(route: APIRoute) -> str:
    """Generates a unique ID for an API route based on its tags and name.

    Args:
        route: The APIRoute object.

    Returns:
        A unique string identifier for the route.
    """
    return f"{route.tags[0]}-{route.name}"


def create_error_handler(
    status_code: int,
) -> Callable[[Request, ServiceError], Response]:
    """Create a custom error handler for a given HTTP status code.

    Args:
        status_code: The HTTP status code for which to create the handler.

    Returns:
        A callable error handler that returns a JSONResponse with the
        exception message.
    """

    def handler(_: Request, exc: ServiceError) -> Response:
        """Handle ServiceError exceptions by returning a JSONResponse.

        Args:
            _: The request object (unused).
            exc: The ServiceError exception caught.

        Returns:
            A JSONResponse with the appropriate status code and error message.
        """
        return JSONResponse(
            status_code=status_code,
            content={"detail": exc.message},
        )

    return handler


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
)

# Set all CORS enabled origins
if settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_STR)

assets_dir = Path(__file__).parent / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

exception_mappings = [
    user_exception_mappings(),
    login_exception_mappings(),
    password_reset_exception_mappings(),
    email_verification_exception_mappings(),
    household_exception_mappings(),
    category_exception_mappings(),
    account_exception_mappings(),
    transaction_exception_mappings(),
    budget_exception_mappings(),
    report_exception_mappings(),
]

for mapping in exception_mappings:
    for key, value in mapping.items():
        app.add_exception_handler(key, cast(ExceptionHandler, create_error_handler(value)))
