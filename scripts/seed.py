# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "httpx>=0.28.1,<1.0.0",
#     "argon2-cffi>=25.1.0,<26.0.0",
#     "cryptography>=46.0.0,<47.0.0",
# ]
# ///
"""Fill a fresh local instance with demo data covering every feature.

Run it against a running stack (`make dev`), on an empty database:

    make seed

It signs in as FIRST_SUPERUSER from .env and fills that user's household. It
goes through the HTTP API rather than the database, so every row passes the
same validation the web app's would, and a change to the API that breaks the
seed is caught the next time somebody runs it.

What it creates:

- the household's name, locale and session label, and a second member who
  joins through a real signup, verification and invitation, read back out of
  the mail catcher, plus one invitation left pending;
- accounts of every type, one of them archived;
- a few custom categories, and one archived;
- about six months of transactions: expenses, income and transfers;
- budgets for the last few months, this one and the next;
- savings goals sharing the savings account, filled by tagged transfers,
  one on track, one behind, and one already reached;
- recurring rules: monthly, weekly and yearly, one paused, one ended, and one
  blocked by its archived account;
- instruments, trades through the brokerage account and typed prices, so the
  portfolio is valued without a market data key;
- a practice for each member, with Clients turned on: a PIN, clients on
  every kind of schedule, one archived, and sessions attended, missed, cancelled, paid,
  owed, waived and still ahead;
- API tokens, one of them revoked, and the secret of a read/write one for
  trying the MCP server.

Client names are encrypted here exactly as the browser does it, so the PINs
printed at the end unlock them on the Clients page.

Every date is relative to today, so the data looks current whenever it is
seeded. It is not idempotent: it refuses a household that already has
accounts. Start again from an empty database with `make clean && make dev`.
"""

import argparse
import base64
import calendar
import datetime
import os
import random
import re
import secrets
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

REPO_ROOT = Path(__file__).resolve().parent.parent
TODAY = datetime.date.today()

PARTNER_PASSWORD = "demo-partner-password"
PARTNER_NAME = "Alex Demo"
PENDING_INVITE_EMAIL = "friend@example.com"
OWNER_PIN = "123456"
PARTNER_PIN = "654321"

# The same numbers the browser uses for a new vault, in src/lib/income-vault.ts.
KDF_MEMORY_KIB = 65536
KDF_ITERATIONS = 3
KDF_PARALLELISM = 1

# Fixed, so two runs produce the same story and a bug seen once can be seen again.
rng = random.Random(42)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def minor(amount: float) -> int:
    """Euros to cents."""
    return round(amount * 100)


def micro(amount: float) -> int:
    """A unit count to millionths."""
    return round(amount * 1_000_000)


def price_micro(amount: float) -> int:
    """A price in major units to millionths of a minor unit, which is how the API stores one."""
    return round(amount * 100 * 1_000_000)


def month_start(months_back: int) -> datetime.date:
    """The first day of the month `months_back` months before this one."""
    index = TODAY.year * 12 + TODAY.month - 1 - months_back
    return datetime.date(index // 12, index % 12 + 1, 1)


def on_day(month: datetime.date, day: int) -> datetime.date:
    """That day of the month, pulled back to its last day if it is short."""
    return month.replace(day=min(day, calendar.monthrange(month.year, month.month)[1]))


def month_key(month: datetime.date) -> str:
    return month.strftime("%Y-%m")


def days(start: datetime.date, end: datetime.date) -> Iterator[datetime.date]:
    """Every day from start to end, both included."""
    day = start
    while day <= end:
        yield day
        day += datetime.timedelta(days=1)


def log(message: str) -> None:
    print(f"  {message}", flush=True)


def step(title: str) -> None:
    print(f"\n{title}", flush=True)


def read_env() -> dict[str, str]:
    """The repository's .env, as plain key and value pairs."""
    path = REPO_ROOT / ".env"
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


# --------------------------------------------------------------------------- #
# The income vault, the way the browser builds it
# --------------------------------------------------------------------------- #


class Vault:
    """A data key wrapped under a PIN, matching src/lib/income-vault.ts."""

    def __init__(self, pin: str) -> None:
        self.salt = secrets.token_bytes(16)
        self.dek = secrets.token_bytes(32)
        kek = hash_secret_raw(
            secret=pin.encode(),
            salt=self.salt,
            time_cost=KDF_ITERATIONS,
            memory_cost=KDF_MEMORY_KIB,
            parallelism=KDF_PARALLELISM,
            hash_len=32,
            type=Type.ID,
        )
        self.wrapped_dek = self._seal(kek, self.dek)

    @staticmethod
    def _seal(key: bytes, plaintext: bytes) -> str:
        # nonce || ciphertext || tag, base64 encoded, as the browser packs it.
        nonce = secrets.token_bytes(12)
        return base64.b64encode(nonce + AESGCM(key).encrypt(nonce, plaintext, None)).decode()

    def encrypt(self, text: str) -> str:
        return self._seal(self.dek, text.encode())

    def upsert_payload(self) -> dict[str, Any]:
        return {
            "kdf": "argon2id",
            "kdf_salt": base64.b64encode(self.salt).decode(),
            "kdf_memory_kib": KDF_MEMORY_KIB,
            "kdf_iterations": KDF_ITERATIONS,
            "kdf_parallelism": KDF_PARALLELISM,
            "wrapped_dek": self.wrapped_dek,
        }


# --------------------------------------------------------------------------- #
# The API
# --------------------------------------------------------------------------- #


class SeedError(Exception):
    pass


class Api:
    """One signed in user's view of the API."""

    def __init__(self, base_url: str, email: str, password: str) -> None:
        self.client = httpx.Client(base_url=f"{base_url.rstrip('/')}/api/v1", timeout=30)
        response = self.client.post("/login/access-token", data={"username": email, "password": password})
        self._check(response, "POST", "/login/access-token")
        self.client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"

    @staticmethod
    def _check(response: httpx.Response, method: str, path: str) -> None:
        if response.is_success:
            return
        raise SeedError(f"{method} {path} answered {response.status_code}: {response.text}")

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.client.request(method, path, **kwargs)
        self._check(response, method, path)
        return response.json()

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self.request("POST", path, json=body)

    def put(self, path: str, body: dict[str, Any]) -> Any:
        return self.request("PUT", path, json=body)

    def patch(self, path: str, body: dict[str, Any]) -> Any:
        return self.request("PATCH", path, json=body)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)


class MailCatcher:
    """Reads the tokens the backend mails out, so flows behind a link can be finished."""

    def __init__(self, base_url: str) -> None:
        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=10)

    def is_up(self) -> bool:
        try:
            return self.client.get("/messages").is_success
        except httpx.HTTPError:
            return False

    def token(self, recipient: str, link_path: str, after_id: int) -> str:
        """The token in the newest mail to `recipient` linking to `link_path`."""
        pattern = re.compile(rf"{re.escape(link_path)}\?token=([^\"'&<\s]+)")

        for _ in range(20):
            messages = self.client.get("/messages").json()
            for message in sorted(messages, key=lambda m: m["id"], reverse=True):
                if message["id"] <= after_id or f"<{recipient}>" not in message["recipients"]:
                    continue
                match = pattern.search(self.client.get(f"/messages/{message['id']}.html").text)
                if match:
                    return match.group(1)
            time.sleep(0.5)

        raise SeedError(f"No mail to {recipient} with a {link_path} link arrived in the mail catcher.")

    def last_id(self) -> int:
        return max((m["id"] for m in self.client.get("/messages").json()), default=0)


# --------------------------------------------------------------------------- #
# The seed, feature by feature
# --------------------------------------------------------------------------- #


class Seeder:
    def __init__(self, owner: Api, api_url: str, mail: MailCatcher, partner_email: str) -> None:
        self.owner = owner
        self.partner_email = partner_email
        self.api_url = api_url
        self.mail = mail
        self.partner: Api | None = None
        self.accounts: dict[str, str] = {}
        self.categories: dict[str, str] = {}
        self.read_write_secret: str | None = None
        # What has gone on the credit card each month, so the card can be paid
        # off by exactly that much the month after.
        self.card_spend: dict[str, int] = {}

    # --- household --------------------------------------------------------- #

    def household(self) -> None:
        step("Household")
        self.owner.patch("/users/me", {"full_name": "Sam Demo"})
        self.owner.patch(
            "/households/me",
            {"name": "Demo Household", "locale": "en-GB", "session_merchant_label": "Therapy session"},
        )
        log("Named the household and the owner, set the locale and the session label")

    def members(self) -> None:
        step("Members")
        if not self.mail.is_up():
            log("The mail catcher is not reachable: skipping the second member and the pending invitation")
            return

        before = self.mail.last_id()
        self.owner.request(
            "POST",
            "/users/signup",
            json={"email": self.partner_email, "password": PARTNER_PASSWORD, "full_name": PARTNER_NAME},
        )
        token = self.mail.token(self.partner_email, "/verify-email", after_id=before)
        self.owner.post("/email-verification/verify", {"token": token})
        log(f"Signed up and verified {self.partner_email}")

        before = self.mail.last_id()
        self.owner.post("/households/me/invites", {"email": self.partner_email, "role": "member"})
        token = self.mail.token(self.partner_email, "/join-household", after_id=before)
        self.partner = Api(self.api_url, self.partner_email, PARTNER_PASSWORD)
        self.partner.post("/households/invites/accept", {"token": token})
        log(f"{self.partner_email} accepted an invitation and joined")

        self.owner.post("/households/me/invites", {"email": PENDING_INVITE_EMAIL, "role": "member"})
        log(f"Left an invitation to {PENDING_INVITE_EMAIL} pending")

    # --- categories -------------------------------------------------------- #

    def load_categories(self) -> None:
        for category in self.owner.get("/categories/", include_archived=True)["data"]:
            self.categories[category["name"]] = category["id"]

    def custom_categories(self) -> None:
        step("Categories")
        self.load_categories()

        side = self.owner.post(
            "/categories/", {"name": "Side Projects", "kind": "expense", "icon": "code", "color": "#7c3aed"}
        )
        self.owner.post("/categories/", {"name": "Domains & Hosting", "kind": "expense", "parent_id": side["id"]})
        self.owner.post(
            "/categories/", {"name": "Coffee Beans", "kind": "expense", "parent_id": self.categories["Food & Drink"]}
        )
        self.owner.post(
            "/categories/", {"name": "Rental Income", "kind": "income", "parent_id": self.categories["Income"]}
        )
        self.owner.patch(f"/categories/{self.categories['Games']}", {"is_archived": True})
        self.load_categories()
        log("Added Side Projects with a child, Coffee Beans and Rental Income; archived Games")

    # --- accounts ---------------------------------------------------------- #

    def create_accounts(self) -> None:
        step("Accounts")
        opened = month_start(6)
        specs = [
            ("Everyday", "current", "Northwind Bank", "DE89370400440532013000", 2400),
            ("Savings", "savings", "Northwind Bank", "GB82WEST12345698765432", 8500),
            ("Wallet", "cash", None, None, 80),
            ("Visa Card", "credit_card", "Northwind Bank", None, -350),
            ("Broker", "brokerage", "Contoso Invest", None, 2000),
            ("Old Bank", "current", "Fabrikam Savings", "GR1601101250000000012300695", 120),
        ]
        for name, kind, institution, iban, opening in specs:
            account = self.owner.post(
                "/accounts/",
                {
                    "name": name,
                    "type": kind,
                    "institution": institution,
                    "iban": iban,
                    "opening_balance_minor": minor(opening),
                    "opening_balance_date": opened.isoformat(),
                },
            )
            self.accounts[name] = account["id"]
        log(f"Created {len(specs)} accounts, opened on {opened}")

    def archive_old_bank(self) -> None:
        """Empty the old account into the new one, leave a rule on it, then archive it."""
        old = self.accounts["Old Bank"]
        self.owner.post(
            "/recurring-rules/",
            {
                "name": "Old Bank account fee",
                "frequency": "monthly",
                "start_date": on_day(month_start(6), 28).isoformat(),
                "day_of_month": 28,
                "kind": "expense",
                "amount_minor": minor(2.5),
                "merchant": "Fabrikam Savings",
                "account_id": old,
                "category_id": self.categories["Bank Fees"],
            },
        )
        self.owner.post("/recurring-rules/run")
        balance = self.owner.get(f"/accounts/{old}")["current_balance_minor"]
        self.owner.post(
            "/transactions/",
            {
                "kind": "transfer",
                "amount_minor": balance,
                "occurred_on": (month_start(5) + datetime.timedelta(days=2)).isoformat(),
                "account_id": old,
                "counter_account_id": self.accounts["Everyday"],
                "note": "Closing the old account",
            },
        )
        self.owner.patch(f"/accounts/{old}", {"is_archived": True})
        log("Emptied and archived Old Bank; its fee rule is now blocked")

    # --- recurring --------------------------------------------------------- #

    def recurring_rules(self) -> None:
        step("Recurring rules")
        start = month_start(6)
        everyday, card = self.accounts["Everyday"], self.accounts["Visa Card"]

        def monthly(name: str, day: int, amount: float, **extra: Any) -> dict[str, Any]:
            return {
                "name": name,
                "frequency": "monthly",
                "start_date": on_day(start, day).isoformat(),
                "day_of_month": day,
                "amount_minor": minor(amount),
                **extra,
            }

        rules = [
            monthly(
                "Rent",
                1,
                1150,
                merchant="City Lettings",
                account_id=everyday,
                category_id=self.categories["Rent / Mortgage"],
            ),
            monthly(
                "Internet",
                5,
                39.9,
                merchant="FibreNet",
                account_id=everyday,
                category_id=self.categories["Internet & Phone"],
            ),
            monthly(
                "Streaming",
                12,
                13.99,
                merchant="StreamFlix",
                account_id=card,
                category_id=self.categories["Subscriptions"],
            ),
            monthly(
                "Music", 20, 10.99, merchant="Tunely", account_id=card, category_id=self.categories["Subscriptions"]
            ),
            monthly("Gym", 3, 45, merchant="Iron Gym", account_id=everyday, category_id=self.categories["Fitness"]),
            monthly(
                "Salary",
                25,
                3200,
                kind="income",
                merchant="Acme Ltd",
                account_id=everyday,
                category_id=self.categories["Salary"],
            ),
            monthly(
                "Flat share rent",
                2,
                450,
                kind="income",
                merchant="Lodger",
                account_id=everyday,
                category_id=self.categories["Rental Income"],
            ),
            monthly(
                "Into savings",
                26,
                500,
                kind="transfer",
                account_id=everyday,
                counter_account_id=self.accounts["Savings"],
            ),
            monthly(
                "Into the broker",
                27,
                300,
                kind="transfer",
                account_id=everyday,
                counter_account_id=self.accounts["Broker"],
            ),
            {
                "name": "Pocket money",
                "frequency": "weekly",
                "start_date": (start + datetime.timedelta(days=(4 - start.weekday()) % 7)).isoformat(),
                "kind": "transfer",
                "amount_minor": minor(20),
                "account_id": everyday,
                "counter_account_id": self.accounts["Wallet"],
            },
            {
                "name": "Home insurance",
                "frequency": "yearly",
                "start_date": on_day(month_start(4), 15).isoformat(),
                "day_of_month": 15,
                "amount_minor": minor(240),
                "merchant": "SafeHome",
                "account_id": everyday,
                "category_id": self.categories["Home Insurance"],
            },
            monthly(
                "Car loan",
                10,
                220,
                merchant="AutoFinance",
                account_id=everyday,
                category_id=self.categories["Loan Interest"],
                end_date=on_day(month_start(2), 10).isoformat(),
            ),
            monthly(
                "Magazine",
                8,
                6.5,
                merchant="Weekly Reader",
                account_id=card,
                category_id=self.categories["Books"],
                is_active=False,
            ),
            monthly(
                "Hosting", 14, 5, merchant="CloudBox", account_id=card, category_id=self.categories["Domains & Hosting"]
            ),
        ]
        for rule in rules:
            self.owner.post("/recurring-rules/", rule)

        result = self.owner.post("/recurring-rules/run")
        log(f"Created {len(rules)} rules (one paused, one ended); recorded {result['created_count']} occurrences")

    # --- transactions ------------------------------------------------------ #

    def transactions(self) -> None:
        step("Transactions")
        everyday, card, wallet = self.accounts["Everyday"], self.accounts["Visa Card"], self.accounts["Wallet"]
        c = self.categories
        start = month_start(6)
        count = 0

        def expense(
            day: datetime.date,
            amount: float,
            category: str,
            merchant: str,
            account: str,
            api: Api | None = None,
            note: str | None = None,
        ) -> None:
            nonlocal count
            (api or self.owner).post(
                "/transactions/",
                {
                    "kind": "expense",
                    "amount_minor": minor(amount),
                    "occurred_on": day.isoformat(),
                    "merchant": merchant,
                    "note": note,
                    "account_id": account,
                    "category_id": c[category],
                },
            )
            if account == card:
                key = month_key(day)
                self.card_spend[key] = self.card_spend.get(key, 0) + minor(amount)
            count += 1

        for day in days(start, TODAY):
            weekday = day.weekday()
            if weekday in (1, 5) or rng.random() < 0.08:
                expense(
                    day,
                    rng.uniform(25, 110),
                    "Groceries",
                    rng.choice(["FreshMart", "Lidl", "Farmers Market"]),
                    everyday,
                )
            if weekday < 5 and rng.random() < 0.45:
                expense(day, rng.uniform(2.4, 5.8), "Cafes", rng.choice(["Bean There", "Corner Café"]), wallet)
            if weekday in (4, 5) and rng.random() < 0.55:
                expense(
                    day,
                    rng.uniform(28, 95),
                    "Restaurants",
                    rng.choice(["Trattoria Roma", "Sushi Go", "The Local"]),
                    card,
                )
            if rng.random() < 0.09:
                expense(day, rng.uniform(45, 80), "Fuel", "Shell", card)
            if weekday < 5 and rng.random() < 0.12:
                expense(day, 1.6, "Public Transport", "Metro", wallet)
            if rng.random() < 0.05:
                expense(day, rng.uniform(15, 40), "Takeaway & Delivery", "QuickEats", card)
            if rng.random() < 0.04:
                expense(day, rng.uniform(8, 30), "Pharmacy", "City Pharmacy", everyday)
            if rng.random() < 0.03:
                expense(day, rng.uniform(25, 120), "Clothing", rng.choice(["Threads", "Urban Outfit"]), card)
            if rng.random() < 0.02:
                expense(day, rng.uniform(10, 25), "Events & Cinema", "Cineplex", card)
            if rng.random() < 0.02:
                expense(day, rng.uniform(9, 30), "Books & Materials", "Page Turner", card)
            if rng.random() < 0.015:
                expense(day, rng.uniform(15, 35), "Coffee Beans", "Roastery", everyday)
            if self.partner and rng.random() < 0.06:
                expense(
                    day,
                    rng.uniform(12, 60),
                    rng.choice(["Household Goods", "Hair & Beauty", "Gifts"]),
                    rng.choice(["HomeStore", "Salon Bella", "Gift Box"]),
                    everyday,
                    api=self.partner,
                )

        for months_back in range(6, -1, -1):
            month = month_start(months_back)
            bill_day = on_day(month, 18)
            if bill_day <= TODAY:
                expense(bill_day, rng.uniform(55, 140), "Utilities", "PowerCo", everyday, note="Electricity")
            if months_back == 3:
                expense(on_day(month, 9), 899, "Electronics", "TechWorld", card, note="New laptop")
            if months_back == 4:
                expense(on_day(month, 21), 340, "Car Maintenance", "QuickFix Garage", everyday)
            if months_back == 2:
                expense(on_day(month, 6), 180, "Flights", "SkyHop", card)
                expense(on_day(month, 6), 420, "Accommodation", "StayWell", card)
            if months_back == 1:
                refund_day = on_day(month, 11)
                self.owner.post(
                    "/transactions/",
                    {
                        "kind": "income",
                        "amount_minor": minor(49.99),
                        "occurred_on": refund_day.isoformat(),
                        "merchant": "Threads",
                        "note": "Returned a jacket",
                        "account_id": card,
                        "category_id": c["Refunds"],
                    },
                )
                count += 1
            if months_back == 0 and TODAY.day >= 2:
                expense(
                    TODAY - datetime.timedelta(days=1),
                    rng.uniform(50, 90),
                    "Doctor & Dentist",
                    "Smile Dental",
                    everyday,
                )

        # The card is paid off on the 3rd for whatever went on it the month before.
        for months_back in range(5, -1, -1):
            month = month_start(months_back)
            pay_day = on_day(month, 3)
            owed = self.card_spend.get(month_key(month_start(months_back + 1)), 0)
            if pay_day <= TODAY and owed:
                self.owner.post(
                    "/transactions/",
                    {
                        "kind": "transfer",
                        "amount_minor": owed,
                        "occurred_on": pay_day.isoformat(),
                        "account_id": everyday,
                        "counter_account_id": card,
                        "note": "Card repayment",
                    },
                )
                count += 1

        if self.partner:
            for months_back in range(6, -1, -1):
                pay_day = on_day(month_start(months_back), 28)
                if pay_day <= TODAY:
                    self.partner.post(
                        "/transactions/",
                        {
                            "kind": "income",
                            "amount_minor": minor(2100),
                            "occurred_on": pay_day.isoformat(),
                            "merchant": "Globex",
                            "account_id": everyday,
                            "category_id": c["Salary"],
                        },
                    )
                    count += 1
            self.partner.post(
                "/transactions/",
                {
                    "kind": "income",
                    "amount_minor": minor(600),
                    "occurred_on": on_day(month_start(2), 15).isoformat(),
                    "merchant": "Globex",
                    "note": "Half year bonus",
                    "account_id": everyday,
                    "category_id": c["Bonus"],
                },
            )
            count += 1

        log(f"Recorded {count} transactions by hand, from {start} to {TODAY}")

    # --- budgets ----------------------------------------------------------- #

    def budgets(self) -> None:
        step("Budgets")
        limits = {
            "Groceries": 450,
            "Restaurants": 220,
            "Cafes": 60,
            "Takeaway & Delivery": 60,
            "Transport": 260,
            "Utilities": 120,
            "Entertainment": 80,
            "Shopping": 150,
            "Health": 120,
            "Side Projects": 15,
        }
        first = month_start(3)
        self.owner.put(
            "/budgets/bulk",
            {
                "month": month_key(first),
                "entries": [{"category_id": self.categories[n], "limit_minor": minor(v)} for n, v in limits.items()],
            },
        )
        for months_back in (2, 1, 0, -1):
            self.owner.post(
                "/budgets/copy",
                {"from_month": month_key(first), "to_month": month_key(month_start(months_back))},
            )

        # Tighten restaurants this month, so one category is over its limit.
        this_month = self.owner.get("/budgets/", month=month_key(TODAY))["data"]
        restaurants = next(b for b in this_month if b["category_id"] == self.categories["Restaurants"])
        self.owner.patch(f"/budgets/{restaurants['id']}", {"limit_minor": minor(90)})
        self.owner.post(
            "/budgets/",
            {"category_id": self.categories["Travel"], "month": month_key(month_start(-1)), "limit_minor": minor(600)},
        )
        log(f"Set {len(limits)} limits from {month_key(first)} through next month, with a tight one this month")

    # --- goals ------------------------------------------------------------- #

    def goals(self) -> None:
        step("Goals")
        everyday = self.accounts["Everyday"]
        savings = self.accounts["Savings"]

        def goal(name: str, target: float, months_ahead: int | None) -> str:
            due = on_day(month_start(-months_ahead), 28) if months_ahead is not None else None
            created = self.owner.post(
                "/goals/",
                {
                    "name": name,
                    "account_id": savings,
                    "target_minor": minor(target),
                    "target_date": due.isoformat() if due else None,
                },
            )
            return str(created["id"])

        car = goal("New car", 20_000, 18)
        holiday = goal("Summer holiday", 3_500, 5)
        laptop = goal("Laptop", 1_200, None)

        # Monthly top ups. The car gets enough to stay on track; the holiday
        # falls short of what its date needs, so the page has one of each.
        # The opening balance and the recurring "Into savings" transfer stay
        # untagged, which is what the account's unassigned share is for.
        count = 0
        for months_back in range(5, -1, -1):
            for goal_id, amount in ((car, 1_100), (holiday, 250)):
                day = on_day(month_start(months_back), 2)
                if day <= TODAY:
                    self.owner.post(
                        "/transactions/",
                        {
                            "kind": "transfer",
                            "amount_minor": minor(amount),
                            "occurred_on": day.isoformat(),
                            "account_id": everyday,
                            "counter_account_id": savings,
                            "goal_id": goal_id,
                            "note": "Goal top up",
                        },
                    )
                    count += 1

        # Saved up, then spent out of the account, and marked as reached.
        for months_back, source, destination, note in (
            (4, everyday, savings, "Laptop fund"),
            (1, savings, everyday, "Bought the laptop"),
        ):
            self.owner.post(
                "/transactions/",
                {
                    "kind": "transfer",
                    "amount_minor": minor(1_200),
                    "occurred_on": on_day(month_start(months_back), 10).isoformat(),
                    "account_id": source,
                    "counter_account_id": destination,
                    "goal_id": laptop,
                    "note": note,
                },
            )
            count += 1
        self.owner.patch(f"/goals/{laptop}", {"is_achieved": True})

        log(f"Set 3 goals on the savings account, and tagged {count} transfers to them")

    # --- investments ------------------------------------------------------- #

    def investments(self) -> None:
        step("Investments")
        broker = self.accounts["Broker"]
        specs = [
            ("VWCE.XETRA", "Vanguard FTSE All-World", "etf", "XETRA", "EUR", 128.40),
            ("EUNL.XETRA", "iShares Core MSCI World", "etf", "XETRA", "EUR", 102.15),
            ("AAPL.US", "Apple Inc.", "stock", "US", "USD", 231.70),
            ("IBGS.AS", "iShares Euro Govt Bond 1-3yr", "bond", "AS", "EUR", 141.05),
            ("MSFT.US", "Microsoft Corp.", "stock", "US", "USD", 452.30),
        ]
        ids: dict[str, str] = {}
        for symbol, name, kind, exchange, currency, _ in specs:
            instrument = self.owner.post(
                "/investments/instruments",
                {"symbol": symbol, "name": name, "kind": kind, "exchange": exchange, "currency_code": currency},
            )
            ids[symbol] = instrument["id"]

        trades = [
            (6, "VWCE.XETRA", "buy", 8, 112.30, 1.5, None),
            (5, "AAPL.US", "buy", 3, 198.20, 1.0, 560.40),
            (5, "IBGS.AS", "buy", 4, 139.80, 1.0, None),
            (4, "VWCE.XETRA", "buy", 4, 116.90, 1.5, None),
            (3, "EUNL.XETRA", "buy", 6, 96.40, 1.5, None),
            (2, "AAPL.US", "sell", 1, 224.10, 1.0, 205.15),
            (1, "VWCE.XETRA", "buy", 3, 124.75, 1.5, None),
            (0, "EUNL.XETRA", "buy", 2, 101.20, 1.5, None),
        ]
        for months_back, symbol, side, quantity, price, fee, cash in trades:
            traded_on = on_day(month_start(months_back), 8)
            if traded_on > TODAY:
                traded_on = TODAY
            self.owner.post(
                "/investments/trades",
                {
                    "instrument_id": ids[symbol],
                    "side": side,
                    "traded_on": traded_on.isoformat(),
                    "quantity_micro": micro(quantity),
                    "price_micro": price_micro(price),
                    "fee_minor": minor(fee),
                    "brokerage_account_id": broker,
                    # A US listing is converted at the bank's rate on the day,
                    # which is the figure a broker's statement shows.
                    "cash_amount_minor": minor(cash) if cash else None,
                },
            )

        # Typed prices, so the portfolio is valued without a market data key.
        for symbol, *_, price in specs:
            self.owner.put(f"/investments/instruments/{ids[symbol]}/price", {"price_micro": price_micro(price)})
        log(f"Tracked {len(specs)} instruments (one with no trades), recorded {len(trades)} trades, typed prices")

        # The typed prices are fresh, so a refresh spends no market data calls
        # and only fetches the exchange rate the US listings are valued at.
        try:
            result = self.owner.post("/investments/prices/refresh")
            failed = ", ".join(f["symbol"] for f in result["failures"])
            log(f"Fetched exchange rates{f' (failed: {failed})' if failed else ''}")
        except SeedError as error:
            log(f"Could not fetch exchange rates, so the US listings are unvalued: {error}")

    # --- clients ----------------------------------------------------------- #

    def income(self) -> None:
        step("Clients")
        # The screen is off until each person turns it on, and both demo users
        # bill clients of their own.
        self.owner.patch("/users/me", {"clients_enabled": True})
        owner_vault = Vault(OWNER_PIN)
        self.owner.put("/income/vault", owner_vault.upsert_payload())
        anchor = month_start(4)

        def first_on(weekday: int) -> datetime.date:
            return anchor + datetime.timedelta(days=(weekday - anchor.weekday()) % 7)

        clients = [
            # name, rate, cadence (frequency, interval, anchor, weekdays), archived after
            ("Maria Kostas", 70, ("weekly", 1, first_on(0), []), None),
            ("Nikos Pappas", 60, ("weekly", 2, first_on(2), []), None),
            ("Eleni Sideri", 65, ("weekly", 1, first_on(0), [0, 3]), None),
            ("Giorgos Tsakalos", 80, ("monthly", 1, on_day(anchor, 15), []), None),
            ("Sofia Lambrou", 75, None, None),
            ("Dimitra Alexiou", 70, ("weekly", 1, first_on(1), []), month_start(1)),
        ]
        sessions = 0
        for name, rate, cadence, left_on in clients:
            body: dict[str, Any] = {
                "name_ct": owner_vault.encrypt(name),
                "note_ct": owner_vault.encrypt(f"Referred in {anchor:%B}."),
                "default_rate_minor": minor(rate),
                "default_account_id": self.accounts["Everyday"],
                "default_category_id": self.categories["Freelance"],
            }
            if cadence:
                frequency, interval, anchor_on, weekdays = cadence
                body |= {
                    "cadence_frequency": frequency,
                    "cadence_interval": interval,
                    "cadence_anchor_on": anchor_on.isoformat(),
                    "cadence_weekdays": weekdays,
                }
            client = self.owner.post("/income/clients", body)
            dates = self._session_dates(cadence, until=(left_on or TODAY + datetime.timedelta(days=21)))
            # Nikos is slow to pay, which is what the debtors list is for.
            sessions += self._sessions(
                self.owner, owner_vault, client["id"], dates, minor(rate), slow_payer=name == "Nikos Pappas"
            )
            if left_on:
                self.owner.patch(f"/income/clients/{client['id']}", {"is_archived": True})

        # A free first meeting with somebody new.
        intake = self.owner.post(
            "/income/clients",
            {
                "name_ct": owner_vault.encrypt("Petros Ioannou"),
                "default_rate_minor": minor(70),
                "default_account_id": self.accounts["Everyday"],
                "default_category_id": self.categories["Freelance"],
            },
        )
        self.owner.post(
            "/income/sessions",
            {
                "client_id": intake["id"],
                "occurs_on": (TODAY - datetime.timedelta(days=3)).isoformat(),
                "fee_minor": 0,
                "status": "attended",
                "payment_status": "waived",
                "note_ct": owner_vault.encrypt("Free intake"),
            },
        )
        sessions += 1
        log(f"PIN {OWNER_PIN}: {len(clients) + 1} clients (one archived), {sessions} sessions")

        if self.partner:
            self.partner.patch("/users/me", {"clients_enabled": True})
            partner_vault = Vault(PARTNER_PIN)
            self.partner.put("/income/vault", partner_vault.upsert_payload())
            client = self.partner.post(
                "/income/clients",
                {
                    "name_ct": partner_vault.encrypt("Leo (maths tutoring)"),
                    "cadence_frequency": "weekly",
                    "cadence_interval": 1,
                    "cadence_anchor_on": first_on(5).isoformat(),
                    "default_rate_minor": minor(35),
                    "default_account_id": self.accounts["Everyday"],
                    "default_category_id": self.categories["Freelance"],
                },
            )
            dates = self._session_dates(("weekly", 1, first_on(5), []), until=TODAY + datetime.timedelta(days=14))
            count = self._sessions(self.partner, partner_vault, client["id"], dates, minor(35), slow_payer=False)
            log(f"PIN {PARTNER_PIN} for {self.partner_email}: 1 client, {count} sessions; the owner sees dots")

    @staticmethod
    def _session_dates(
        cadence: tuple[str, int, datetime.date, list[int]] | None, until: datetime.date
    ) -> list[datetime.date]:
        """Roughly the appointments a schedule holds, from its anchor to `until`."""
        if cadence is None:
            # Seen as and when: a handful of dates with no pattern.
            return sorted({TODAY - datetime.timedelta(days=rng.randint(1, 110)) for _ in range(6)})

        frequency, interval, anchor_on, weekdays = cadence
        if frequency == "monthly":
            index = anchor_on.year * 12 + anchor_on.month - 1
            dates = []
            while True:
                month = datetime.date(index // 12, index % 12 + 1, 1)
                day = on_day(month, anchor_on.day)
                if day > until:
                    return dates
                dates.append(day)
                index += interval

        named = set(weekdays) or {anchor_on.weekday()}
        week_of_anchor = anchor_on - datetime.timedelta(days=anchor_on.weekday())
        return [
            day
            for day in days(anchor_on, until)
            if day.weekday() in named and ((day - week_of_anchor).days // 7) % interval == 0
        ]

    @staticmethod
    def _sessions(
        api: Api, vault: Vault, client_id: str, dates: list[datetime.date], fee: int, slow_payer: bool
    ) -> int:
        for occurs_on in dates:
            body: dict[str, Any] = {"client_id": client_id, "occurs_on": occurs_on.isoformat(), "fee_minor": fee}

            if occurs_on >= TODAY:
                body |= {"status": "scheduled", "payment_status": "pending"}
            else:
                roll = rng.random()
                if roll < 0.08:
                    # Called off in good time: never charged.
                    body |= {"status": "cancelled", "payment_status": "waived"}
                elif roll < 0.13:
                    # A no-show, charged, and not paid yet.
                    body |= {"status": "missed", "payment_status": "pending"}
                else:
                    age = (TODAY - occurs_on).days
                    unpaid = (slow_payer and rng.random() < 0.5) or age < 7 and rng.random() < 0.4
                    if unpaid:
                        body |= {"status": "attended", "payment_status": "pending"}
                    else:
                        paid_on = min(occurs_on + datetime.timedelta(days=rng.choice([0, 0, 0, 2, 7])), TODAY)
                        body |= {"status": "attended", "payment_status": "paid", "paid_on": paid_on.isoformat()}
                if rng.random() < 0.15:
                    body["note_ct"] = vault.encrypt(
                        rng.choice(["Good progress.", "Ran ten minutes late.", "Homework set for next time."])
                    )
            api.post("/income/sessions", body)
        return len(dates)

    # --- API tokens -------------------------------------------------------- #

    def api_tokens(self) -> None:
        step("API tokens")
        self.owner.post("/api-tokens/", {"name": "Claude Desktop", "scope": "read", "expires_in_days": 90})
        created = self.owner.post(
            "/api-tokens/", {"name": "Local MCP (read/write)", "scope": "read_write", "expires_in_days": None}
        )
        self.read_write_secret = created["secret"]
        old = self.owner.post("/api-tokens/", {"name": "Old laptop", "scope": "read", "expires_in_days": 30})
        self.owner.delete(f"/api-tokens/{old['token']['id']}")
        log("Minted a read token, a read/write token, and a revoked one")

    # --- all of it --------------------------------------------------------- #

    def run(self) -> None:
        if self.owner.get("/accounts/", include_archived=True)["count"]:
            raise SeedError(
                "This household already has accounts, so it has been seeded or used. "
                "Start from an empty database with: make clean && make dev"
            )

        self.household()
        self.custom_categories()
        self.create_accounts()
        self.archive_old_bank()
        self.members()
        self.recurring_rules()
        self.transactions()
        self.budgets()
        self.goals()
        self.investments()
        self.income()
        self.api_tokens()


def main() -> None:
    env = read_env()
    parser = argparse.ArgumentParser(description="Fill a fresh local instance with demo data.")
    parser.add_argument("--api-url", default=os.environ.get("SEED_API_URL", "http://localhost:8000"))
    parser.add_argument("--mail-url", default=os.environ.get("SEED_MAIL_URL", "http://localhost:1080"))
    parser.add_argument("--email", default=env.get("FIRST_SUPERUSER"), help="Defaults to FIRST_SUPERUSER in .env")
    parser.add_argument(
        "--password", default=env.get("FIRST_SUPERUSER_PASSWORD"), help="Defaults to FIRST_SUPERUSER_PASSWORD in .env"
    )
    parser.add_argument(
        "--partner-email",
        default="partner@example.com",
        help="The second member, who joins the household. Must not have an account yet.",
    )
    args = parser.parse_args()

    if not args.email or not args.password:
        sys.exit("No account to sign in with. Set FIRST_SUPERUSER in .env, or pass --email and --password.")

    print(f"Seeding {args.api_url} as {args.email}")
    try:
        seeder = Seeder(
            Api(args.api_url, args.email, args.password), args.api_url, MailCatcher(args.mail_url), args.partner_email
        )
        seeder.run()
    except httpx.ConnectError:
        sys.exit(f"\nCannot reach the API at {args.api_url}. Is the stack running? Start it with: make dev")
    except SeedError as error:
        sys.exit(f"\nSeeding stopped: {error}")

    print("\nDone. Sign in at http://localhost:5173")
    print(f"  Owner:   {args.email} (Clients PIN {OWNER_PIN})")
    if seeder.partner:
        print(f"  Partner: {args.partner_email} / {PARTNER_PASSWORD} (Clients PIN {PARTNER_PIN})")
    if seeder.read_write_secret:
        print(f"  Read/write API token for the MCP server: {seeder.read_write_secret}")


if __name__ == "__main__":
    main()
