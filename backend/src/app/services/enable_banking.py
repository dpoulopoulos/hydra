"""Bank data through Enable Banking.

Enable Banking is an aggregator: it holds the licence to read account data
under PSD2 and relays one API to the APIs each bank is required to offer. The
app talks to it alone, and never to a bank directly.

Reading an account takes a login at the bank. The app asks Enable Banking to
start one and gets back a URL; the browser goes there, the account holder logs
in at their bank, and the bank sends the browser back to the app with a code.
That code becomes a session, which is what every read after it is made under.
A session lasts as long as the bank allows, usually 180 days.

Everything here sits behind :class:`BankProvider`, so the services can be
tested without a network and bank sync can be switched off by configuration.
"""

import datetime
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, NoReturn, Protocol

import httpx
import jwt

from app.exceptions import (
    BankAuthorizationError,
    BankProviderError,
    BankRateLimitedError,
    BankSessionExpiredError,
    BankSyncNotConfiguredError,
)

# How long a signed token is used for. Enable Banking accepts up to a day; an
# hour keeps a leaked one short-lived.
_TOKEN_LIFETIME_SECONDS = 3600
# A token is replaced this long before it expires, so a request that starts
# just before the end does not arrive just after it.
_TOKEN_REFRESH_MARGIN_SECONDS = 60

# The list of banks changes rarely, and the connect dialog asks for it each time
# it opens.
_ASPSP_CACHE_SECONDS = 24 * 3600

# Error codes meaning the session is gone and only a new login brings it back.
# An account uid belongs to one session, so an unknown account means the same.
_SESSION_GONE_CODES = frozenset(
    {
        "EXPIRED_SESSION",
        "CLOSED_SESSION",
        "REVOKED_SESSION",
        "SESSION_DOES_NOT_EXIST",
        "ACCOUNT_DOES_NOT_EXIST",
    }
)
_RATE_LIMIT_CODES = frozenset({"ASPSP_RATE_LIMIT_EXCEEDED"})
# Codes /sessions answers with when the code from the redirect is no good.
_AUTHORIZATION_CODES = frozenset({"WRONG_AUTHORIZATION_CODE", "ALREADY_AUTHORIZED", "AUTHORIZATION_NOT_FOUND"})


@dataclass(frozen=True)
class Psu:
    """The account holder, when they are at a browser for this request.

    A bank allows about four pulls a day that nobody is present for. A pull
    made while the account holder is present does not count against that, and
    the bank is told they are present by these two headers.
    """

    ip_address: str
    user_agent: str


@dataclass(frozen=True)
class Aspsp:
    """A bank, or similar institution, that accounts can be read from."""

    name: str
    country: str
    logo: str | None
    # The longest a login at this bank can last. None when it did not say.
    maximum_consent_seconds: int | None


@dataclass(frozen=True)
class Authorization:
    """A login that has been started, and where to send the browser to finish it."""

    url: str
    authorization_id: str


@dataclass(frozen=True)
class SessionAccount:
    """One account a login gave access to."""

    # What the account is called within this session. A new session gives the
    # same account a new uid.
    uid: str
    # What the account is called across sessions, so a reconnect finds the
    # account it had before. Not every bank sends one.
    identification_hash: str | None
    iban: str | None
    name: str | None
    currency: str | None


@dataclass(frozen=True)
class BankSession:
    """A completed login."""

    session_id: str
    valid_until: datetime.datetime | None
    accounts: list[SessionAccount]


class BankProvider(Protocol):
    """A source of bank account data."""

    @property
    def is_configured(self) -> bool:
        """Whether this provider can actually be called.

        Returns:
            True when the provider has everything it needs to answer.
        """
        ...

    def list_aspsps(self, country: str) -> list[Aspsp]:
        """List the banks that can be connected in a country.

        Args:
            country: The ISO 3166 two-letter country code.

        Returns:
            The banks, in the order the provider gave them.
        """
        ...

    def start_authorization(
        self,
        aspsp_name: str,
        aspsp_country: str,
        valid_until: datetime.datetime,
        state: str,
        redirect_url: str,
        psu: Psu | None = None,
    ) -> Authorization:
        """Start a login at a bank.

        Args:
            aspsp_name: The bank's name, as listed.
            aspsp_country: The bank's country, as listed.
            valid_until: When the access being asked for should end.
            state: An unguessable token the bank hands back with the code, so
                the callback can be tied to the request that started it.
            redirect_url: Where the bank sends the browser afterwards.
            psu: The account holder, when they are at a browser.

        Returns:
            Where to send the browser.
        """
        ...

    def create_session(self, code: str) -> BankSession:
        """Turn the code from the bank's redirect into a session.

        Args:
            code: The code the bank put in the redirect.

        Returns:
            The session and the accounts it reaches.
        """
        ...

    def delete_session(self, session_id: str) -> None:
        """End a session, withdrawing the app's access.

        Args:
            session_id: The session to end.
        """
        ...

    def transactions(
        self,
        account_uid: str,
        date_from: datetime.date,
        date_to: datetime.date,
        psu: Psu | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Fetch the transactions on an account between two dates, both included.

        Args:
            account_uid: The account's uid in the current session.
            date_from: The first day to fetch.
            date_to: The last day to fetch.
            psu: The account holder, when they are at a browser.

        Returns:
            Each transaction as the provider sent it, across every page.
        """
        ...


class NullBankProvider:
    """The provider used when bank sync is switched off. It refuses every call."""

    @property
    def is_configured(self) -> bool:
        """Whether this provider can actually be called.

        Returns:
            False, always.
        """
        return False

    def list_aspsps(self, country: str) -> list[Aspsp]:
        """Refuse to list banks.

        Args:
            country: Ignored.

        Raises:
            BankSyncNotConfiguredError: Always.
        """
        raise BankSyncNotConfiguredError from None

    def start_authorization(
        self,
        aspsp_name: str,
        aspsp_country: str,
        valid_until: datetime.datetime,
        state: str,
        redirect_url: str,
        psu: Psu | None = None,
    ) -> Authorization:
        """Refuse to start a login.

        Args:
            aspsp_name: Ignored.
            aspsp_country: Ignored.
            valid_until: Ignored.
            state: Ignored.
            redirect_url: Ignored.
            psu: Ignored.

        Raises:
            BankSyncNotConfiguredError: Always.
        """
        raise BankSyncNotConfiguredError from None

    def create_session(self, code: str) -> BankSession:
        """Refuse to complete a login.

        Args:
            code: Ignored.

        Raises:
            BankSyncNotConfiguredError: Always.
        """
        raise BankSyncNotConfiguredError from None

    def delete_session(self, session_id: str) -> None:
        """Refuse to end a session.

        Args:
            session_id: Ignored.

        Raises:
            BankSyncNotConfiguredError: Always.
        """
        raise BankSyncNotConfiguredError from None

    def transactions(
        self,
        account_uid: str,
        date_from: datetime.date,
        date_to: datetime.date,
        psu: Psu | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Refuse to fetch transactions.

        Args:
            account_uid: Ignored.
            date_from: Ignored.
            date_to: Ignored.
            psu: Ignored.

        Raises:
            BankSyncNotConfiguredError: Always.
        """
        raise BankSyncNotConfiguredError from None


# Shared across instances, because a provider is built for each request.
_aspsp_cache: dict[tuple[str, str, str], tuple[float, list[Aspsp]]] = {}
_aspsp_cache_lock = threading.Lock()


class EnableBankingClient:
    """Bank data from Enable Banking, signed with the application's key."""

    def __init__(
        self,
        app_id: str,
        private_key: str,
        base_url: str,
        timeout_seconds: float,
        http_client: httpx.Client | None = None,
    ) -> None:
        """Initialize the Enable Banking client.

        Args:
            app_id: The application id from the control panel.
            private_key: The application's RSA private key, as PEM.
            base_url: The root of the API, without a trailing slash.
            timeout_seconds: How long to wait for one request.
            http_client: The HTTP client to send requests with. Tests pass one
                with a mock transport; otherwise one is made for each request.
        """
        self.app_id = app_id
        self._private_key = private_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client
        self._token: str | None = None
        self._token_expires_at = 0.0

    @property
    def is_configured(self) -> bool:
        """Whether this provider can actually be called.

        Returns:
            True when an app id and a key are set.
        """
        return bool(self.app_id and self._private_key)

    def _bearer_token(self) -> str:
        """Get a signed token for the Authorization header, minting one when needed.

        Returns:
            The token.
        """
        now = time.time()
        if self._token is None or now >= self._token_expires_at - _TOKEN_REFRESH_MARGIN_SECONDS:
            issued_at = int(now)
            self._token = jwt.encode(
                {
                    "iss": "enablebanking.com",
                    "aud": "api.enablebanking.com",
                    "iat": issued_at,
                    "exp": issued_at + _TOKEN_LIFETIME_SECONDS,
                },
                self._private_key,
                algorithm="RS256",
                headers={"kid": self.app_id},
            )
            self._token_expires_at = issued_at + _TOKEN_LIFETIME_SECONDS
        return self._token

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        psu: Psu | None = None,
    ) -> Any:
        """Make one signed request and decode the answer.

        Args:
            method: The HTTP method.
            path: The path under the base URL.
            params: Query parameters.
            json: The JSON body.
            psu: The account holder, when they are at a browser.

        Returns:
            The decoded JSON body.

        Raises:
            BankSessionExpiredError: If the session behind the request has ended.
            BankRateLimitedError: If the bank refused because of its daily limit.
            BankAuthorizationError: If the code from a redirect was refused.
            BankProviderError: If the request failed for any other reason.
        """
        headers = {"Authorization": f"Bearer {self._bearer_token()}"}
        if psu is not None:
            headers["Psu-Ip-Address"] = psu.ip_address
            headers["Psu-User-Agent"] = psu.user_agent

        try:
            if self._http_client is not None:
                response = self._http_client.request(
                    method, f"{self.base_url}{path}", params=params, json=json, headers=headers
                )
            else:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.request(
                        method, f"{self.base_url}{path}", params=params, json=json, headers=headers
                    )
        except httpx.TimeoutException:
            raise BankProviderError("it did not answer in time. Try again in a minute.") from None
        except httpx.HTTPError:
            # The library's own wording is dropped: it can quote the request,
            # and the request carries the signed token.
            raise BankProviderError("the request failed.") from None

        if response.is_success:
            try:
                return response.json()
            except ValueError:
                raise BankProviderError("it answered with something other than JSON.") from None

        _raise_for_error(response)

    def list_aspsps(self, country: str) -> list[Aspsp]:
        """List the banks that can be connected in a country.

        Args:
            country: The ISO 3166 two-letter country code.

        Returns:
            The banks that accept personal logins, in the order the provider gave them.
        """
        country = country.upper()
        key = (self.base_url, self.app_id, country)
        with _aspsp_cache_lock:
            cached = _aspsp_cache.get(key)
        if cached is not None and time.monotonic() - cached[0] < _ASPSP_CACHE_SECONDS:
            return cached[1]

        payload = self._request("GET", "/aspsps", params={"country": country, "psu_type": "personal"})
        aspsps = [
            Aspsp(
                name=item["name"],
                country=item["country"],
                logo=item.get("logo"),
                maximum_consent_seconds=_int_or_none(item.get("maximum_consent_validity")),
            )
            for item in _list(payload, "aspsps")
            if isinstance(item, dict) and item.get("name") and item.get("country")
        ]
        with _aspsp_cache_lock:
            _aspsp_cache[key] = (time.monotonic(), aspsps)
        return aspsps

    def start_authorization(
        self,
        aspsp_name: str,
        aspsp_country: str,
        valid_until: datetime.datetime,
        state: str,
        redirect_url: str,
        psu: Psu | None = None,
    ) -> Authorization:
        """Start a login at a bank.

        Args:
            aspsp_name: The bank's name, as listed.
            aspsp_country: The bank's country, as listed.
            valid_until: When the access being asked for should end.
            state: An unguessable token the bank hands back with the code.
            redirect_url: Where the bank sends the browser afterwards.
            psu: The account holder, when they are at a browser.

        Returns:
            Where to send the browser.

        Raises:
            BankProviderError: If the answer has no URL to send the browser to.
        """
        payload = self._request(
            "POST",
            "/auth",
            json={
                "access": {"valid_until": valid_until.isoformat()},
                "aspsp": {"name": aspsp_name, "country": aspsp_country},
                "state": state,
                "redirect_url": redirect_url,
                "psu_type": "personal",
            },
            psu=psu,
        )
        url = payload.get("url") if isinstance(payload, dict) else None
        if not isinstance(url, str) or not url:
            raise BankProviderError("it did not say where to log in.")
        return Authorization(url=url, authorization_id=str(payload.get("authorization_id") or ""))

    def create_session(self, code: str) -> BankSession:
        """Turn the code from the bank's redirect into a session.

        Args:
            code: The code the bank put in the redirect.

        Returns:
            The session and the accounts it reaches.

        Raises:
            BankProviderError: If the answer has no session id.
        """
        payload = self._request("POST", "/sessions", json={"code": code})
        session_id = payload.get("session_id") if isinstance(payload, dict) else None
        if not isinstance(session_id, str) or not session_id:
            raise BankProviderError("it did not return a session.")

        access = payload.get("access")
        valid_until = _datetime_or_none(access.get("valid_until") if isinstance(access, dict) else None)

        accounts = []
        for item in _list(payload, "accounts"):
            if not isinstance(item, dict) or not item.get("uid"):
                continue
            account_id = item.get("account_id")
            iban = account_id.get("iban") if isinstance(account_id, dict) else None
            accounts.append(
                SessionAccount(
                    uid=str(item["uid"]),
                    identification_hash=_str_or_none(item.get("identification_hash")),
                    iban=_str_or_none(iban),
                    name=_account_name(item),
                    currency=_str_or_none(item.get("currency")),
                )
            )
        return BankSession(session_id=session_id, valid_until=valid_until, accounts=accounts)

    def delete_session(self, session_id: str) -> None:
        """End a session, withdrawing the app's access.

        Args:
            session_id: The session to end.
        """
        self._request("DELETE", f"/sessions/{session_id}")

    def transactions(
        self,
        account_uid: str,
        date_from: datetime.date,
        date_to: datetime.date,
        psu: Psu | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Fetch the transactions on an account between two dates, both included.

        Args:
            account_uid: The account's uid in the current session.
            date_from: The first day to fetch.
            date_to: The last day to fetch.
            psu: The account holder, when they are at a browser.

        Yields:
            Each transaction as the provider sent it, across every page.
        """
        params = {"date_from": date_from.isoformat(), "date_to": date_to.isoformat()}
        while True:
            payload = self._request("GET", f"/accounts/{account_uid}/transactions", params=params, psu=psu)
            for item in _list(payload, "transactions"):
                if isinstance(item, dict):
                    yield item
            continuation_key = payload.get("continuation_key") if isinstance(payload, dict) else None
            if not continuation_key:
                return
            params = {**params, "continuation_key": str(continuation_key)}


def _raise_for_error(response: httpx.Response) -> NoReturn:
    """Raise the error an unsuccessful answer means.

    Args:
        response: The answer, which was not a success.

    Raises:
        BankSessionExpiredError: If the session has ended.
        BankRateLimitedError: If the bank's daily limit is spent.
        BankAuthorizationError: If the code from a redirect was refused.
        BankProviderError: For anything else.
    """
    code: str | None = None
    message: str | None = None
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        code = _str_or_none(body.get("error"))
        message = _str_or_none(body.get("message"))

    if code in _SESSION_GONE_CODES:
        raise BankSessionExpiredError(code)
    if code in _RATE_LIMIT_CODES or response.status_code == httpx.codes.TOO_MANY_REQUESTS:
        raise BankRateLimitedError(code)
    if code in _AUTHORIZATION_CODES:
        raise BankAuthorizationError(message or "the bank did not accept the code it sent back.")
    if response.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN) and code is None:
        raise BankProviderError("it refused the application. Check ENABLE_BANKING_APP_ID and the key.")
    raise BankProviderError(message or f"it answered {response.status_code}.", code)


def _account_name(item: dict[str, Any]) -> str | None:
    """Pick what to call an account.

    Banks put the account holder's name in `name` and what the account is in
    `details` or `product`, so two accounts of one person would otherwise
    both be called after them.

    Args:
        item: The account as a session listed it.

    Returns:
        The account's description, else its product, else the name it was given.
    """
    for key in ("details", "product", "name"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:255]
    return None


def _list(payload: Any, key: str) -> list[Any]:
    value = payload.get(key) if isinstance(payload, dict) else None
    return value if isinstance(value, list) else []


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _datetime_or_none(value: Any) -> datetime.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=datetime.UTC)
