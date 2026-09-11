from fastapi import APIRouter, Depends

from app.api.deps import EmailOutboxServiceDep, get_current_active_superuser
from app.models import EmailOutboxStats

# Whoever administers the deployment, not whoever sent the mail: the outbox
# holds every address the application has ever written to, across households.
router = APIRouter(
    prefix="/email-outbox",
    tags=["email-outbox"],
    dependencies=[Depends(get_current_active_superuser)],
)


@router.get("/stats", response_model=EmailOutboxStats)
def read_email_outbox_stats(*, email_outbox_service: EmailOutboxServiceDep) -> EmailOutboxStats:
    """Report what the outbox is holding.

    A message that gives up says so once, in the log, and after that nothing
    surfaces it. This is where a deployment can see that mail is not arriving
    without going to the table by hand.

    Args:
        email_outbox_service: The email outbox service dependency.

    Returns:
        The backlog still owed to somebody and the messages that gave up.
    """
    return email_outbox_service.stats()
