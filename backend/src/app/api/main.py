from fastapi import APIRouter

from app.api.routes import (
    accounts,
    api_tokens,
    budgets,
    categories,
    email_outbox,
    email_verification,
    households,
    income,
    investments,
    login,
    password_reset,
    recurring_rules,
    reports,
    transactions,
    users,
)

api_router = APIRouter()
api_router.include_router(users.router)
api_router.include_router(api_tokens.router)
api_router.include_router(households.router)
api_router.include_router(categories.router)
api_router.include_router(accounts.router)
api_router.include_router(transactions.router)
api_router.include_router(budgets.router)
api_router.include_router(recurring_rules.router)
api_router.include_router(income.router)
api_router.include_router(investments.router)
api_router.include_router(reports.router)
api_router.include_router(login.router)
api_router.include_router(password_reset.router)
api_router.include_router(email_verification.router)
api_router.include_router(email_outbox.router)
