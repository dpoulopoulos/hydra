import datetime
import json
from collections.abc import Callable, Iterator

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.exceptions import (
    BankAuthorizationError,
    BankProviderError,
    BankRateLimitedError,
    BankSessionExpiredError,
    BankSyncNotConfiguredError,
)
from app.services import enable_banking
from app.services.enable_banking import EnableBankingClient, NullBankProvider, Psu

APP_ID = "11111111-2222-3333-4444-555555555555"
BASE_URL = "https://api.example.test"

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(scope="module")
def key_pair() -> tuple[str, rsa.RSAPublicKey]:
    """An RSA key made for these tests, as PEM, with its public half."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    return pem, key.public_key()


@pytest.fixture(autouse=True)
def clear_aspsp_cache() -> Iterator[None]:
    """Keep the bank list one test cached from leaking into the next."""
    enable_banking._aspsp_cache.clear()
    yield
    enable_banking._aspsp_cache.clear()


def make_client(pem: str, handler: Handler) -> EnableBankingClient:
    return EnableBankingClient(
        app_id=APP_ID,
        private_key=pem,
        base_url=BASE_URL,
        timeout_seconds=5,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def answer(payload: object, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=payload)


class TestNullBankProvider:
    """Test the provider used when bank sync is off."""

    def test_is_not_configured(self) -> None:
        """Test that the null provider says it cannot be called."""
        assert NullBankProvider().is_configured is False

    @pytest.mark.parametrize(
        "call",
        [
            lambda p: p.list_aspsps("GR"),
            lambda p: p.start_authorization("Bank", "GR", datetime.datetime.now(datetime.UTC), "s", "https://x"),
            lambda p: p.create_session("code"),
            lambda p: p.delete_session("sid"),
            lambda p: p.transactions("uid", datetime.date(2026, 1, 1), datetime.date(2026, 1, 2)),
        ],
    )
    def test_refuses_every_call(self, call: Callable[[NullBankProvider], object]) -> None:
        """Test that every call says bank sync is not configured."""
        with pytest.raises(BankSyncNotConfiguredError):
            call(NullBankProvider())


class TestSigning:
    """Test the token every request is signed with."""

    def test_token_carries_the_app_id_and_the_expected_claims(self, key_pair: tuple[str, rsa.RSAPublicKey]) -> None:
        """Test that the token is RS256, names the app in kid, and verifies with the public key."""
        pem, public_key = key_pair
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers["Authorization"])
            return answer({"message": "ok"})

        make_client(pem, handler).delete_session("sid")

        token = seen[0].removeprefix("Bearer ")
        assert jwt.get_unverified_header(token) == {"alg": "RS256", "kid": APP_ID, "typ": "JWT"}
        claims = jwt.decode(token, public_key, algorithms=["RS256"], audience="api.enablebanking.com")
        assert claims["iss"] == "enablebanking.com"
        assert claims["exp"] - claims["iat"] == 3600

    def test_token_is_reused_until_it_nears_expiry(
        self, key_pair: tuple[str, rsa.RSAPublicKey], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that one token serves several requests, and a fresh one is minted near the end."""
        pem, _ = key_pair
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers["Authorization"])
            return answer({})

        now = [1_000_000.0]
        monkeypatch.setattr(enable_banking.time, "time", lambda: now[0])
        client = make_client(pem, handler)

        client.delete_session("a")
        client.delete_session("b")
        now[0] += 3600 - 30
        client.delete_session("c")

        assert seen[0] == seen[1]
        assert seen[2] != seen[1]

    def test_is_configured_with_an_id_and_a_key(self, key_pair: tuple[str, rsa.RSAPublicKey]) -> None:
        """Test that a client with an id and a key reports itself configured."""
        assert make_client(key_pair[0], lambda r: answer({})).is_configured is True


class TestListAspsps:
    """Test listing the banks in a country."""

    def test_parses_banks_and_asks_for_personal_logins(self, key_pair: tuple[str, rsa.RSAPublicKey]) -> None:
        """Test that the list is parsed, and unusable entries are dropped."""
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return answer(
                {
                    "aspsps": [
                        {
                            "name": "Alpha Bank",
                            "country": "GR",
                            "logo": "https://l/a.png",
                            "maximum_consent_validity": 15552000,
                        },
                        {"name": "Eurobank", "country": "GR", "maximum_consent_validity": True},
                        {"country": "GR"},
                        "junk",
                    ]
                }
            )

        aspsps = make_client(key_pair[0], handler).list_aspsps("gr")

        assert [a.name for a in aspsps] == ["Alpha Bank", "Eurobank"]
        assert aspsps[0].maximum_consent_seconds == 15552000
        assert aspsps[0].logo == "https://l/a.png"
        assert aspsps[1].maximum_consent_seconds is None
        assert requests[0].url.params["country"] == "GR"
        assert requests[0].url.params["psu_type"] == "personal"

    def test_list_is_cached(self, key_pair: tuple[str, rsa.RSAPublicKey]) -> None:
        """Test that a second request for the same country does not reach the provider."""
        calls: list[int] = []

        def handler(_request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return answer({"aspsps": [{"name": "Mock ASPSP", "country": "GR"}]})

        client = make_client(key_pair[0], handler)
        client.list_aspsps("GR")
        client.list_aspsps("GR")

        assert len(calls) == 1


class TestStartAuthorization:
    """Test starting a login."""

    def test_sends_the_request_and_the_psu_headers(self, key_pair: tuple[str, rsa.RSAPublicKey]) -> None:
        """Test that the body names the bank, state and redirect, and the PSU is passed on."""
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return answer({"url": "https://bank.test/login", "authorization_id": "auth-1"})

        valid_until = datetime.datetime(2027, 4, 1, tzinfo=datetime.UTC)
        result = make_client(key_pair[0], handler).start_authorization(
            "Mock ASPSP", "GR", valid_until, "state-1", "https://app/cb", Psu("203.0.113.9", "Firefox")
        )

        assert result.url == "https://bank.test/login"
        assert result.authorization_id == "auth-1"
        body = json.loads(requests[0].content)
        assert body == {
            "access": {"valid_until": "2027-04-01T00:00:00+00:00"},
            "aspsp": {"name": "Mock ASPSP", "country": "GR"},
            "state": "state-1",
            "redirect_url": "https://app/cb",
            "psu_type": "personal",
        }
        assert requests[0].headers["Psu-Ip-Address"] == "203.0.113.9"
        assert requests[0].headers["Psu-User-Agent"] == "Firefox"

    def test_no_psu_sends_no_psu_headers(self, key_pair: tuple[str, rsa.RSAPublicKey]) -> None:
        """Test that a background call does not claim the account holder is present."""
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return answer({"url": "https://bank.test/login"})

        make_client(key_pair[0], handler).start_authorization(
            "Mock ASPSP", "GR", datetime.datetime(2027, 1, 1, tzinfo=datetime.UTC), "s", "https://app/cb"
        )

        assert "Psu-Ip-Address" not in requests[0].headers

    def test_an_answer_without_a_url_is_an_error(self, key_pair: tuple[str, rsa.RSAPublicKey]) -> None:
        """Test that a missing login URL is reported rather than handed to the browser."""
        client = make_client(key_pair[0], lambda r: answer({"authorization_id": "a"}))

        with pytest.raises(BankProviderError, match="where to log in"):
            client.start_authorization("B", "GR", datetime.datetime(2027, 1, 1, tzinfo=datetime.UTC), "s", "u")


class TestCreateSession:
    """Test completing a login."""

    def test_parses_the_session_and_its_accounts(self, key_pair: tuple[str, rsa.RSAPublicKey]) -> None:
        """Test that the session id, expiry and accounts are read."""
        payload = {
            "session_id": "sess-1",
            "access": {"valid_until": "2027-04-01T00:00:00+00:00"},
            "accounts": [
                {
                    "uid": "uid-1",
                    "identification_hash": "hash-1",
                    "account_id": {"iban": "GR1601101250000000012300695"},
                    "name": "Current",
                    "currency": "EUR",
                },
                {"uid": "uid-2", "account_id": {"other": {"identification": "x"}}},
                {"name": "no uid"},
            ],
        }
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return answer(payload)

        session = make_client(key_pair[0], handler).create_session("code-1")

        assert json.loads(requests[0].content) == {"code": "code-1"}
        assert session.session_id == "sess-1"
        assert session.valid_until == datetime.datetime(2027, 4, 1, tzinfo=datetime.UTC)
        assert [a.uid for a in session.accounts] == ["uid-1", "uid-2"]
        assert session.accounts[0].iban == "GR1601101250000000012300695"
        assert session.accounts[0].identification_hash == "hash-1"
        assert session.accounts[1].iban is None
        assert session.accounts[1].currency is None

    def test_an_account_is_named_by_what_it_is_not_who_holds_it(self, key_pair: tuple[str, rsa.RSAPublicKey]) -> None:
        """Test that the description wins over the holder's name, and the name is the last resort."""
        client = make_client(
            key_pair[0],
            lambda r: answer(
                {
                    "session_id": "s",
                    "accounts": [
                        {"uid": "1", "name": "Ida Jensen", "details": "Danske Konto        "},
                        {"uid": "2", "name": "Ida Jensen", "details": " ", "product": "Savings"},
                        {"uid": "3", "name": "Ida Jensen"},
                    ],
                }
            ),
        )

        names = [a.name for a in client.create_session("c").accounts]

        assert names == ["Danske Konto", "Savings", "Ida Jensen"]

    def test_a_naive_expiry_is_read_as_utc(self, key_pair: tuple[str, rsa.RSAPublicKey]) -> None:
        """Test that an expiry without a zone is not compared against aware times as naive."""
        client = make_client(
            key_pair[0], lambda r: answer({"session_id": "s", "access": {"valid_until": "2027-04-01T00:00:00"}})
        )

        assert client.create_session("c").valid_until == datetime.datetime(2027, 4, 1, tzinfo=datetime.UTC)

    def test_an_unreadable_expiry_is_none(self, key_pair: tuple[str, rsa.RSAPublicKey]) -> None:
        """Test that an expiry that does not parse is left unknown."""
        client = make_client(key_pair[0], lambda r: answer({"session_id": "s", "access": {"valid_until": "soon"}}))

        assert client.create_session("c").valid_until is None

    def test_an_answer_without_a_session_is_an_error(self, key_pair: tuple[str, rsa.RSAPublicKey]) -> None:
        """Test that a missing session id is reported."""
        client = make_client(key_pair[0], lambda r: answer({"accounts": []}))

        with pytest.raises(BankProviderError, match="did not return a session"):
            client.create_session("c")

    def test_a_wrong_code_is_an_authorization_error(self, key_pair: tuple[str, rsa.RSAPublicKey]) -> None:
        """Test that a refused code is told apart from the provider failing."""
        client = make_client(
            key_pair[0],
            lambda r: answer(
                {"code": 422, "message": "Wrong authorization code provided", "error": "WRONG_AUTHORIZATION_CODE"}, 422
            ),
        )

        with pytest.raises(BankAuthorizationError, match="Wrong authorization code provided"):
            client.create_session("bogus")


class TestTransactions:
    """Test fetching transactions."""

    def test_follows_continuation_keys_across_pages(self, key_pair: tuple[str, rsa.RSAPublicKey]) -> None:
        """Test that every page is fetched, with the dates on each request."""
        requests: list[httpx.Request] = []
        pages = {
            None: {"transactions": [{"entry_reference": "1"}, {"entry_reference": "2"}], "continuation_key": "k2"},
            "k2": {"transactions": [{"entry_reference": "3"}, "junk"], "continuation_key": None},
        }

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return answer(pages[request.url.params.get("continuation_key")])

        rows = list(
            make_client(key_pair[0], handler).transactions(
                "uid-1", datetime.date(2026, 9, 1), datetime.date(2026, 10, 9), Psu("203.0.113.9", "Firefox")
            )
        )

        assert [r["entry_reference"] for r in rows] == ["1", "2", "3"]
        assert len(requests) == 2
        assert requests[0].url.path == "/accounts/uid-1/transactions"
        assert requests[1].url.params["date_from"] == "2026-09-01"
        assert requests[1].url.params["date_to"] == "2026-10-09"
        assert requests[1].headers["Psu-Ip-Address"] == "203.0.113.9"


class TestErrors:
    """Test how the provider's errors are told apart."""

    @pytest.mark.parametrize(
        "code", ["EXPIRED_SESSION", "CLOSED_SESSION", "SESSION_DOES_NOT_EXIST", "ACCOUNT_DOES_NOT_EXIST"]
    )
    def test_a_gone_session_asks_for_a_new_login(self, key_pair: tuple[str, rsa.RSAPublicKey], code: str) -> None:
        """Test that every code meaning the session is gone raises the same error."""
        client = make_client(key_pair[0], lambda r: answer({"error": code, "message": "gone"}, 401))

        with pytest.raises(BankSessionExpiredError) as caught:
            list(client.transactions("uid", datetime.date(2026, 1, 1), datetime.date(2026, 1, 2)))

        assert caught.value.code == code

    @pytest.mark.parametrize(
        ("status_code", "payload"),
        [(429, {"error": "ASPSP_RATE_LIMIT_EXCEEDED", "message": "slow down"}), (429, {})],
    )
    def test_a_spent_daily_limit_is_a_rate_limit(
        self, key_pair: tuple[str, rsa.RSAPublicKey], status_code: int, payload: dict[str, str]
    ) -> None:
        """Test that the bank's daily limit is recognised by code or by status."""
        client = make_client(key_pair[0], lambda r: answer(payload, status_code))

        with pytest.raises(BankRateLimitedError):
            list(client.transactions("uid", datetime.date(2026, 1, 1), datetime.date(2026, 1, 2)))

    def test_a_refused_application_points_at_the_settings(self, key_pair: tuple[str, rsa.RSAPublicKey]) -> None:
        """Test that a 403 without a code is reported as a configuration problem."""
        client = make_client(key_pair[0], lambda r: answer({"code": 403, "message": "Application does not exist"}, 403))

        with pytest.raises(BankProviderError, match="ENABLE_BANKING_APP_ID"):
            client.delete_session("s")

    def test_other_errors_carry_the_providers_message_and_code(self, key_pair: tuple[str, rsa.RSAPublicKey]) -> None:
        """Test that an unrecognised error passes on what the provider said."""
        client = make_client(key_pair[0], lambda r: answer({"error": "ASPSP_ERROR", "message": "Bank is down"}, 500))

        with pytest.raises(BankProviderError, match="Bank is down") as caught:
            client.delete_session("s")

        assert caught.value.code == "ASPSP_ERROR"

    def test_a_body_that_is_not_json_reports_the_status(self, key_pair: tuple[str, rsa.RSAPublicKey]) -> None:
        """Test that an error page instead of JSON still gives a useful message."""
        client = make_client(key_pair[0], lambda r: httpx.Response(502, text="<html>Bad gateway</html>"))

        with pytest.raises(BankProviderError, match="answered 502"):
            client.delete_session("s")

    def test_a_success_that_is_not_json_is_an_error(self, key_pair: tuple[str, rsa.RSAPublicKey]) -> None:
        """Test that a 200 with a body that does not decode is reported."""
        client = make_client(key_pair[0], lambda r: httpx.Response(200, text="<html>"))

        with pytest.raises(BankProviderError, match="other than JSON"):
            client.delete_session("s")

    def test_a_timeout_says_so(self, key_pair: tuple[str, rsa.RSAPublicKey]) -> None:
        """Test that a slow bank is reported as a timeout."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        with pytest.raises(BankProviderError, match="did not answer in time"):
            make_client(key_pair[0], handler).delete_session("s")

    def test_the_signed_token_never_reaches_the_error_message(self, key_pair: tuple[str, rsa.RSAPublicKey]) -> None:
        """Test that a transport error quoting the request does not leak the token."""
        tokens: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            tokens.append(request.headers["Authorization"])
            raise httpx.ConnectError(f"failed with headers {request.headers['Authorization']}", request=request)

        with pytest.raises(BankProviderError) as caught:
            make_client(key_pair[0], handler).delete_session("s")

        assert tokens[0].removeprefix("Bearer ") not in str(caught.value)
        assert caught.value.__cause__ is None
