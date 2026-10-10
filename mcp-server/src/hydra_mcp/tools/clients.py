import datetime
import uuid
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ..money import money, signed_money, to_minor
from ..resolve import PAGE_SIZE, Named, accounts_of, categories_of
from ..vault import LOCKED, Keyring, keyring
from ._common import DESTRUCTIVE, READ_ONLY, WRITES, Month, as_str, current_token, hydra

# Monday is 0, as hydra and the page both count them.
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

Weekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
Frequency = Literal["none", "daily", "weekly", "monthly", "yearly"]
SessionStatus = Literal["scheduled", "attended", "missed", "cancelled"]
PaymentStatus = Literal["pending", "paid", "waived"]

ClientName = Annotated[str, Field(description="The client, by name, or by id from an earlier result.")]
SessionId = Annotated[str, Field(description="The session's id, from list_sessions.")]
Schedule = Annotated[
    Frequency | None,
    Field(description="How often they are seen. none is as and when; weekly with every=2 is a fortnight."),
]
Every = Annotated[int | None, Field(description="Every how many periods. Defaults to 1.", ge=1, le=365)]
StartsOn = Annotated[
    datetime.date | None,
    Field(description="The date the pattern is pinned to. A monthly one keeps this day. Defaults to today."),
]
Weekdays = Annotated[
    list[Weekday] | None,
    Field(description="For a weekly pattern, the days it falls on. Leave out to keep the start date's weekday."),
]
ClientNote = Annotated[str | None, Field(description="Anything worth remembering about them.", max_length=1000)]


class Clients:
    """The household's clients, for one tool call, with their names opened.

    Clients are not resolved through `Named` alone, because two of them may
    share a name: the encryption that hides names is also what stops hydra
    refusing a duplicate. A name that matches two clients is asked about
    rather than settled by whichever came last.
    """

    def __init__(self, rows: list[dict[str, Any]], keys: Keyring) -> None:
        """Initialize the lookup.

        Args:
            rows: Every client, as hydra reports them.
            keys: The keyring that opens the current person's names.
        """
        self.keys = keys
        self.by_id = {uuid.UUID(row["id"]): row for row in rows}
        self.names = {client_id: keys.read(row["name_ct"]) for client_id, row in self.by_id.items()}

    def name(self, client_id: Any) -> str | None:
        """Get a client's name, if this person can read it.

        Args:
            client_id: The id as hydra reported it.

        Returns:
            The name, or None if it is locked or under someone else's key.
        """
        return self.names.get(uuid.UUID(str(client_id)))

    def row(self, wanted: str) -> dict[str, Any]:
        """Resolve what a caller wrote into a client.

        Args:
            wanted: A name or an id.

        Returns:
            The client, as hydra reports them.

        Raises:
            ToolError: If nothing matches, or more than one client does.
        """
        try:
            as_uuid = uuid.UUID(wanted)
        except ValueError:
            pass
        else:
            if as_uuid in self.by_id:
                return self.by_id[as_uuid]
            raise ToolError(f"There is no client with the id {wanted} in this household.")

        if not self.keys.unlocked:
            raise ToolError(LOCKED)

        lowered = wanted.strip().lower()
        matches = [client_id for client_id, name in self.names.items() if name is not None and name.lower() == lowered]
        if len(matches) > 1:
            listed = ", ".join(f"{self.names[m]} ({m}, {_since(self.by_id[m])})" for m in matches)
            raise ToolError(f"More than one client is called '{wanted}'. Say which one by id: {listed}.")
        if matches:
            return self.by_id[matches[0]]

        readable = {client_id: name for client_id, name in self.names.items() if name is not None}
        # Named does the near-miss suggestions, which are worth the same here.
        Named(readable, "client").id(wanted)
        raise ToolError(f"There is no client called '{wanted}' in this household.")

    def own(self, wanted: str) -> dict[str, Any]:
        """Resolve a client the current person may change.

        Checked here rather than left to hydra, whose 403 would reach the host
        as a refused token rather than the model as a reason.

        Args:
            wanted: A name or an id.

        Returns:
            The client.

        Raises:
            ToolError: If the client belongs to another member of the household.
        """
        row = self.row(wanted)
        if not self.keys.owns(row):
            raise ToolError(
                "That client was added by another member of the household. Only they can change or delete them."
            )
        return row


async def clients_of(ctx: Context, token: str) -> Clients:
    """Fetch every client, archived ones too, with their names opened.

    Args:
        ctx: The tool's context, carrying the PIN header.
        token: The hydra API token to present.

    Returns:
        The clients.
    """
    keys = await keyring(ctx, token)

    rows: list[dict[str, Any]] = []
    skip = 0
    while True:
        payload = await hydra().get(
            "/income/clients", token=token, subject="client", params={"skip": skip, "limit": PAGE_SIZE}
        )
        rows.extend(payload["data"])
        skip += len(payload["data"])
        if not payload["data"] or skip >= payload["count"]:
            break

    return Clients(rows, keys)


async def _currency(token: str) -> str:
    """Read the household's currency, which every fee is in.

    Args:
        token: The hydra API token to present.

    Returns:
        The currency code.
    """
    household = await hydra().get("/households/me", token=token, subject="household")
    currency: str = household["currency_code"]
    return currency


def _since(row: dict[str, Any]) -> str:
    """Say when a client was added, to tell two of the same name apart.

    Args:
        row: The client.

    Returns:
        A short phrase.
    """
    return f"added {str(row['created_at'])[:10]}"


def describe_schedule(row: dict[str, Any]) -> dict[str, Any] | None:
    """Describe how often a client is seen.

    Args:
        row: The client.

    Returns:
        The pattern, or None for somebody seen as and when.
    """
    if row.get("cadence_frequency") is None:
        return None

    return {
        "frequency": row["cadence_frequency"],
        "every": row["cadence_interval"],
        "starts_on": row["cadence_anchor_on"],
        "weekdays": [WEEKDAYS[day] for day in row.get("cadence_weekdays") or []],
    }


def describe_client(
    row: dict[str, Any], clients: Clients, accounts: Named, categories: Named, currency: str
) -> dict[str, Any]:
    """Describe one client.

    Args:
        row: The client, as hydra reports them.
        clients: The lookup their name is opened through.
        accounts: The household's accounts.
        categories: The household's categories.
        currency: The household's currency.

    Returns:
        The fields worth reading.
    """
    mine = clients.keys.owns(row)
    return {
        "id": row["id"],
        # None when the name is someone else's, or no PIN was given.
        "name": clients.name(row["id"]),
        "added_by_you": mine,
        "rate": money(row["default_rate_minor"], currency),
        "schedule": describe_schedule(row),
        "account": accounts.name(row["default_account_id"]),
        "category": categories.name(row.get("default_category_id")),
        "note": clients.keys.read(row.get("note_ct")) if mine else None,
        "archived": row.get("archived_at") is not None,
    }


def describe_session(row: dict[str, Any], clients: Clients, currency: str) -> dict[str, Any]:
    """Describe one session.

    Args:
        row: The session, as hydra reports it.
        clients: The lookup its client's name is opened through.
        currency: The household's currency.

    Returns:
        The fields worth reading.
    """
    return {
        "id": row["id"],
        "client": clients.name(row["client_id"]),
        "client_id": row["client_id"],
        "on": row["occurs_on"],
        "fee": money(row["fee_minor"], currency),
        "status": row["status"],
        "payment": row["payment_status"],
        "paid_on": row.get("paid_on"),
    }


def schedule_fields(
    schedule: Frequency | None,
    every: int | None,
    starts_on: datetime.date | None,
    weekdays: list[Weekday] | None,
    current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Turn the schedule arguments into the fields hydra stores.

    hydra refuses half a schedule, so a frequency always travels with the
    date it is pinned to, and days of the week only with a weekly pattern.

    Args:
        schedule: The frequency, "none", or None to leave it alone.
        every: Every how many periods.
        starts_on: The date the pattern is pinned to.
        weekdays: The days a weekly pattern falls on.
        current: The client as it stands, when editing one.

    Returns:
        The fields to send. Empty when nothing about the schedule was given.

    Raises:
        ToolError: If days are given for a pattern that is not weekly.
    """
    if schedule == "none":
        return {"cadence_frequency": None, "cadence_anchor_on": None, "cadence_weekdays": [], "cadence_interval": 1}

    frequency = schedule or (current or {}).get("cadence_frequency")
    if frequency is None:
        if every is not None or starts_on is not None or weekdays is not None:
            raise ToolError("Say how often they are seen as well: daily, weekly, monthly or yearly.")
        return {}

    if weekdays and frequency != "weekly":
        raise ToolError("Days of the week only go with a weekly pattern.")

    fields: dict[str, Any] = {}
    if schedule is not None:
        fields["cadence_frequency"] = schedule
        if frequency != "weekly":
            fields["cadence_weekdays"] = []
    if every is not None:
        fields["cadence_interval"] = every
    if weekdays is not None:
        fields["cadence_weekdays"] = sorted({WEEKDAYS.index(day) for day in weekdays})

    anchor = starts_on or (current or {}).get("cadence_anchor_on")
    if starts_on is not None or anchor is None:
        fields["cadence_anchor_on"] = (starts_on or datetime.date.today()).isoformat()
    return fields


def register(mcp: MCPServer) -> None:
    """Register the tools for clients and the sessions they attend.

    Args:
        mcp: The server to register them on.
    """

    @mcp.tool(annotations=READ_ONLY)
    async def list_clients(
        ctx: Context,
        include_archived: Annotated[bool, Field(description="Include clients no longer seen.")] = False,
    ) -> dict[str, Any]:
        """List the people seen by the session, with their rate and schedule.

        A name is only readable by the person who added the client, and only
        when the connection carries their PIN. Anybody else's clients are
        listed with their name as null, the same as on the page.

        Args:
            ctx: The request context, which carries the PIN.
            include_archived: Whether to include archived clients.

        Returns:
            The clients.
        """
        token = current_token()
        clients = await clients_of(ctx, token)
        accounts = await accounts_of(token)
        categories = await categories_of(token)
        currency = await _currency(token)

        listed = [
            describe_client(row, clients, accounts, categories, currency)
            for row in clients.by_id.values()
            if include_archived or row.get("archived_at") is None
        ]
        listed.sort(key=lambda c: (c["name"] is None, (c["name"] or "").lower()))
        return {"clients": listed, "count": len(listed), "names_unlocked": clients.keys.unlocked}

    @mcp.tool(annotations=WRITES)
    async def create_client(
        ctx: Context,
        name: Annotated[str, Field(description="Their name.", min_length=1, max_length=200)],
        account: Annotated[str, Field(description="The account their payments land in, by name.")],
        rate: Annotated[str, Field(description="What they usually pay a session, in major units, e.g. 60.00.")],
        category: Annotated[str | None, Field(description="The income category for their payments.")] = None,
        schedule: Schedule = None,
        every: Every = None,
        starts_on: StartsOn = None,
        weekdays: Weekdays = None,
        note: ClientNote = None,
    ) -> dict[str, Any]:
        """Add a client.

        Their name and note are locked with the PIN before they leave this
        server, so this needs the PIN on the connection. Two clients may share
        a name; check list_clients first, because adding someone twice makes
        two of them.

        Args:
            ctx: The request context, which carries the PIN.
            name: Their name.
            account: Where their payments land.
            rate: What they usually pay.
            category: The income category for their payments.
            schedule: How often they are seen.
            every: Every how many periods.
            starts_on: The date the pattern is pinned to.
            weekdays: The days a weekly pattern falls on.
            note: Anything worth remembering.

        Returns:
            The client as added.
        """
        token = current_token()
        keys = await keyring(ctx, token)
        accounts = await accounts_of(token)
        categories = await categories_of(token)
        currency = await _currency(token)

        body: dict[str, Any] = {
            "name_ct": keys.write(name.strip()),
            "default_account_id": as_str(accounts.id(account)),
            "default_category_id": as_str(categories.id(category)),
            "default_rate_minor": to_minor(rate, currency),
            "note_ct": keys.write(note) if note else None,
            **schedule_fields(schedule, every, starts_on, weekdays),
        }
        created = await hydra().post("/income/clients", token=token, subject="client", json=body)
        return describe_client(created, Clients([created], keys), accounts, categories, currency)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def update_client(
        ctx: Context,
        client: ClientName,
        name: Annotated[str | None, Field(description="A new name.", min_length=1, max_length=200)] = None,
        rate: Annotated[str | None, Field(description="A new usual rate, in major units.")] = None,
        account: Annotated[str | None, Field(description="A new account for their payments.")] = None,
        category: Annotated[str | None, Field(description="A new income category for their payments.")] = None,
        schedule: Schedule = None,
        every: Every = None,
        starts_on: StartsOn = None,
        weekdays: Weekdays = None,
        note: Annotated[
            str | None, Field(description="A new note. An empty string removes it.", max_length=1000)
        ] = None,
        archived: Annotated[bool | None, Field(description="True to archive them, false to bring them back.")] = None,
    ) -> dict[str, Any]:
        """Change a client, or archive them.

        Only the fields given are changed. Archive someone who has stopped
        coming rather than deleting them: their sessions are the record of the
        work. Changing the account or category does not move past payments.
        Only the person who added a client can change them.

        Args:
            ctx: The request context, which carries the PIN.
            client: Which client.
            name: A new name.
            rate: A new usual rate.
            account: A new account.
            category: A new income category.
            schedule: How often they are seen, or none.
            every: Every how many periods.
            starts_on: The date the pattern is pinned to.
            weekdays: The days a weekly pattern falls on.
            note: A new note.
            archived: Whether they are archived.

        Returns:
            The client as they now stand.
        """
        token = current_token()
        clients = await clients_of(ctx, token)
        row = clients.own(client)
        accounts = await accounts_of(token)
        categories = await categories_of(token)
        currency = await _currency(token)

        changes: dict[str, Any] = {
            "name_ct": clients.keys.write(name.strip()) if name is not None else None,
            "default_rate_minor": to_minor(rate, currency) if rate is not None else None,
            "default_account_id": as_str(accounts.id(account)),
            "default_category_id": as_str(categories.id(category)),
            "is_archived": archived,
        }
        given = {field: value for field, value in changes.items() if value is not None}
        if note is not None:
            given["note_ct"] = clients.keys.write(note) if note else None
        given.update(schedule_fields(schedule, every, starts_on, weekdays, current=row))

        updated = await hydra().patch(f"/income/clients/{row['id']}", token=token, subject="client", json=given)
        return describe_client(updated, Clients([updated], clients.keys), accounts, categories, currency)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def delete_client(ctx: Context, client: ClientName) -> dict[str, Any]:
        """Delete a client who has no sessions.

        hydra refuses if they have any, because those sessions record work
        done and money taken; archive them with update_client instead. Check
        with the person first.

        Args:
            ctx: The request context, which carries the PIN.
            client: Which client.

        Returns:
            What hydra said about the deletion.
        """
        token = current_token()
        clients = await clients_of(ctx, token)
        row = clients.own(client)
        answer: dict[str, Any] = await hydra().delete(f"/income/clients/{row['id']}", token=token, subject="client")
        return answer

    @mcp.tool(annotations=READ_ONLY)
    async def list_sessions(
        ctx: Context,
        client: Annotated[str | None, Field(description="Only this client's sessions, by name or id.")] = None,
        month: Month = None,
        date_from: Annotated[datetime.date | None, Field(description="The first day to include.")] = None,
        date_to: Annotated[datetime.date | None, Field(description="The last day to include.")] = None,
        status: Annotated[SessionStatus | None, Field(description="Only sessions that went this way.")] = None,
        payment: Annotated[PaymentStatus | None, Field(description="Only sessions in this payment state.")] = None,
        owed_only: Annotated[
            bool, Field(description="Only work actually owed for: attended, not waived, not free, not yet paid.")
        ] = False,
        oldest_first: Annotated[bool, Field(description="Oldest first rather than newest first.")] = False,
        limit: Annotated[int, Field(description="How many to return.", ge=1, le=200)] = 50,
    ) -> dict[str, Any]:
        """List sessions, the diary of who was seen when and whether they paid.

        owed_only is the debtors list: "who still owes me". A session is
        income only once it is paid; until then its fee is a debt.

        Args:
            ctx: The request context, which carries the PIN.
            client: Only this client.
            month: Only this month. Leave out, with no dates, for all of them.
            date_from: The first day.
            date_to: The last day.
            status: Only this status.
            payment: Only this payment state.
            owed_only: Only work that is owed for.
            oldest_first: Sort oldest first.
            limit: How many to return.

        Returns:
            The sessions, how many matched, and what they earned and are owed.
        """
        token = current_token()
        clients = await clients_of(ctx, token)
        currency = await _currency(token)

        payload = await hydra().get(
            "/income/sessions",
            token=token,
            subject="session",
            params={
                "client_id": clients.row(client)["id"] if client else None,
                "month": month,
                "date_from": date_from.isoformat() if date_from else None,
                "date_to": date_to.isoformat() if date_to else None,
                "status": status,
                "payment_status": payment,
                "owed_only": owed_only or None,
                "sort": "date" if oldest_first else "-date",
                "limit": limit,
            },
        )
        return {
            "sessions": [describe_session(row, clients, currency) for row in payload["data"]],
            "count": payload["count"],
            "earned": money(payload["earned_total_minor"], currency),
            "owed": money(payload["outstanding_total_minor"], currency),
        }

    @mcp.tool(annotations=WRITES)
    async def record_session(
        ctx: Context,
        client: ClientName,
        on: Annotated[datetime.date, Field(description="The day of the session.")],
        fee: Annotated[
            str | None, Field(description="What it costs, in major units. Defaults to the client's rate.")
        ] = None,
        status: Annotated[SessionStatus, Field(description="What happened.")] = "scheduled",
        payment: Annotated[PaymentStatus, Field(description="Whether it was paid.")] = "pending",
        paid_on: Annotated[
            datetime.date | None, Field(description="The day the money arrived. Defaults to the session's day.")
        ] = None,
    ) -> dict[str, Any]:
        """Record a session with a client.

        Only a paid session reaches the ledger, as income on the day it was
        paid, into the client's account. An attended, unpaid one is owed.
        Check list_sessions first, because recording one twice doubles it.

        Args:
            ctx: The request context, which carries the PIN.
            client: Which client.
            on: The day of the session.
            fee: What it costs.
            status: What happened.
            payment: Whether it was paid.
            paid_on: When the money arrived.

        Returns:
            The session as recorded.
        """
        token = current_token()
        clients = await clients_of(ctx, token)
        row = clients.row(client)
        currency = await _currency(token)

        if paid_on is not None and payment != "paid":
            raise ToolError("A payment date only goes with payment=paid.")

        body = {
            "client_id": row["id"],
            "occurs_on": on.isoformat(),
            "fee_minor": to_minor(fee, currency) if fee is not None else row["default_rate_minor"],
            "status": status,
            "payment_status": payment,
            "paid_on": (paid_on or on).isoformat() if payment == "paid" else None,
        }
        created = await hydra().post("/income/sessions", token=token, subject="session", json=body)
        return describe_session(created, clients, currency)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def update_session(
        ctx: Context,
        session: SessionId,
        client: Annotated[str | None, Field(description="Move it to another client, by name or id.")] = None,
        on: Annotated[datetime.date | None, Field(description="A new day.")] = None,
        fee: Annotated[str | None, Field(description="A new fee, in major units.")] = None,
        status: Annotated[SessionStatus | None, Field(description="What happened.")] = None,
        payment: Annotated[PaymentStatus | None, Field(description="Whether it was paid.")] = None,
        paid_on: Annotated[
            datetime.date | None, Field(description="The day the money arrived. Defaults to the session's day.")
        ] = None,
    ) -> dict[str, Any]:
        """Change a session: mark it attended, missed, cancelled, paid or waived.

        Marking it paid writes the income to the ledger; taking that back
        removes it again. Only the fields given are changed.

        Args:
            ctx: The request context, which carries the PIN.
            session: Which session.
            client: A different client.
            on: A new day.
            fee: A new fee.
            status: What happened.
            payment: Whether it was paid.
            paid_on: When the money arrived.

        Returns:
            The session as it now stands.
        """
        token = current_token()
        clients = await clients_of(ctx, token)
        currency = await _currency(token)

        changes: dict[str, Any] = {
            "client_id": clients.row(client)["id"] if client else None,
            "occurs_on": on.isoformat() if on else None,
            "fee_minor": to_minor(fee, currency) if fee is not None else None,
            "status": status,
            "payment_status": payment,
            "paid_on": paid_on.isoformat() if paid_on else None,
        }
        given = {field: value for field, value in changes.items() if value is not None}

        updated = await hydra().patch(f"/income/sessions/{_uuid(session)}", token=token, subject="session", json=given)
        return describe_session(updated, clients, currency)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def delete_session(session: SessionId) -> dict[str, Any]:
        """Delete a session, and the income it put in the ledger if it was paid.

        To record that somebody did not come, mark it missed or cancelled with
        update_session instead. Check with the person first.

        Args:
            session: Which session.

        Returns:
            What hydra said about the deletion.
        """
        token = current_token()
        answer: dict[str, Any] = await hydra().delete(
            f"/income/sessions/{_uuid(session)}", token=token, subject="session"
        )
        return answer

    @mcp.tool(annotations=READ_ONLY)
    async def get_clients_summary(month: Month = None) -> dict[str, Any]:
        """Sum up a month of client work, and what is owed across every month.

        earned is what the month's work was worth, received is what arrived
        and is what the other reports count, and owed is the difference. A
        busy month can still leave you short, which is why they are apart.

        Args:
            month: Which month. Defaults to the current one.

        Returns:
            The month's figures, what is owed overall, and the year so far.
        """
        token = current_token()
        s = await hydra().get("/income/summary", token=token, subject="summary", params={"month": month})
        currency = s["currency_code"]

        return {
            "month": s["month"],
            "earned": money(s["earned_minor"], currency),
            "received": money(s["received_minor"], currency),
            "owed_this_month": money(s["outstanding_minor"], currency),
            "owed_overall": money(s["total_outstanding_minor"], currency),
            "oldest_unpaid_on": s.get("oldest_unpaid_on"),
            "attended": s["attended_count"],
            "unpaid": s["unpaid_count"],
            "missed": s["missed_count"],
            "cancelled": s["cancelled_count"],
            "still_scheduled": s["scheduled_count"],
            "still_scheduled_worth": money(s["scheduled_minor"], currency),
            "active_clients": s["active_client_count"],
            "year": s["year"],
            "earned_this_year": money(s["year_earned_minor"], currency),
            "sessions_this_year": s["year_session_count"],
        }

    @mcp.tool(annotations=READ_ONLY)
    async def get_clients_forecast(
        ctx: Context,
        month: Annotated[
            str | None,
            Field(
                description="The month to forecast, as 2026-09. Defaults to next month.",
                pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
            ),
        ] = None,
        months: Annotated[int | None, Field(description="How many complete months to learn from.", ge=2, le=24)] = None,
    ) -> dict[str, Any]:
        """Estimate what a month of client work will bring, with a range.

        Built from complete months only. The likely figure sits inside a band,
        because a freelance month that lands on its average is the exception.
        Also lists each client's attendance and what they still owe.

        Args:
            ctx: The request context, which carries the PIN.
            month: The month to forecast.
            months: How many months of history to use.

        Returns:
            The estimate, its band, the history behind it, and each client.
        """
        token = current_token()
        keys = await keyring(ctx, token)
        f = await hydra().get(
            "/income/forecast", token=token, subject="forecast", params={"month": month, "months": months}
        )
        currency = f["currency_code"]

        def optional(minor: int | None) -> dict[str, object] | None:
            return None if minor is None else money(minor, currency)

        return {
            "month": f["month"],
            "likely": money(f["likely_minor"], currency),
            "low": money(f["low_minor"], currency),
            "high": money(f["high_minor"], currency),
            "confidence": f"{f['confidence_percent']}%",
            "basis": f["basis"],
            "months_used": f["months_used"],
            "earned_so_far": money(f["earned_so_far_minor"], currency),
            "booked": money(f["booked_minor"], currency),
            "booked_sessions": f["booked_session_count"],
            "expected_from_diary": money(f["expected_from_diary_minor"], currency),
            "active_clients": f["active_client_count"],
            "priced_clients": f["priced_client_count"],
            "monthly_churn_rate": f.get("monthly_churn_rate"),
            "client_lifetime_value": optional(f.get("client_lifetime_value_minor")),
            "history": [
                {
                    "month": m["month"],
                    "earned": money(m["earned_minor"], currency),
                    "received": money(m["received_minor"], currency),
                    "owed": signed_money(m["outstanding_minor"], currency),
                    "attended": m["attended_count"],
                    "missed": m["missed_count"],
                    "cancelled": m["cancelled_count"],
                    "clients": m["client_count"],
                }
                for m in f["history"]
            ],
            "clients": [
                {
                    "client": keys.read(c["name_ct"]),
                    "client_id": c["client_id"],
                    "attended": c["attended_count"],
                    "missed": c["missed_count"],
                    "attendance_rate": None if c["attendance_rate"] is None else f"{c['attendance_rate'] * 100:.0f}%",
                    "owes": money(c["outstanding_minor"], currency),
                    "oldest_unpaid_on": c.get("oldest_unpaid_on"),
                    "average_per_month": money(c["average_monthly_minor"], currency),
                    "booked": money(c["booked_minor"], currency),
                    "last_session_on": c.get("last_session_on"),
                    "archived": c["is_archived"],
                }
                for c in f["clients"]
            ],
        }


def _uuid(value: str) -> uuid.UUID:
    """Check a session id before it becomes part of a path.

    Args:
        value: What the caller wrote.

    Returns:
        The id.

    Raises:
        ToolError: If it is not an id.
    """
    try:
        return uuid.UUID(value)
    except ValueError:
        raise ToolError(f"'{value}' is not a session id. Take one from list_sessions.") from None
