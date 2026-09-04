from fastapi import APIRouter

from app.api.routes import (
    accounts,
    budgets,
    categories,
    email_verification,
    households,
    login,
    password_reset,
    reports,
    transactions,
    users,
)

api_router = APIRouter()
api_router.include_router(users.router)
api_router.include_router(households.router)
api_router.include_router(categories.router)
api_router.include_router(accounts.router)
api_router.include_router(transactions.router)
api_router.include_router(budgets.router)
api_router.include_router(reports.router)
api_router.include_router(login.router)
api_router.include_router(password_reset.router)
api_router.include_router(email_verification.router)
