from fastapi import APIRouter

from app.api.routes import email_verification, login, password_reset, users

api_router = APIRouter()
api_router.include_router(users.router)
api_router.include_router(login.router)
api_router.include_router(password_reset.router)
api_router.include_router(email_verification.router)
