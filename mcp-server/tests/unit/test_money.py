import pytest
from mcp.server.mcpserver.exceptions import ToolError

from hydra_mcp.money import display, money, signed_display, to_major, to_minor


class TestToMajor:
    """Tests for rendering a stored amount."""

    @pytest.mark.parametrize(
        ("amount_minor", "currency", "expected"),
        [
            (4250, "EUR", "42.50"),
            (0, "EUR", "0.00"),
            (1, "EUR", "0.01"),
            (100_000_000, "EUR", "1000000.00"),
            # A currency with no minor unit at all. Two decimals here would be
            # a hundredfold error, not a rounding one.
            (4250, "JPY", "4250"),
            (4250, "KWD", "4.250"),
        ],
    )
    def test_renders_with_the_currencys_own_decimals(self, amount_minor: int, currency: str, expected: str) -> None:
        assert to_major(amount_minor, currency) == expected


class TestToMinor:
    """Tests for reading an amount a caller wrote."""

    @pytest.mark.parametrize(
        ("amount", "currency", "expected"),
        [("42.50", "EUR", 4250), ("42.5", "EUR", 4250), ("0", "EUR", 0), (42.50, "EUR", 4250), ("4250", "JPY", 4250)],
    )
    def test_reads_an_amount(self, amount: str | float, currency: str, expected: int) -> None:
        assert to_minor(amount, currency) == expected

    def test_round_trips(self) -> None:
        assert to_minor(to_major(123_456, "EUR"), "EUR") == 123_456

    def test_refuses_more_precision_than_the_currency_has(self) -> None:
        # Rounding this away would hide a mistake until somebody reconciled a
        # statement, which is the worst moment to find it.
        with pytest.raises(ToolError, match="2 decimal places"):
            to_minor("10.005", "EUR")

    def test_refuses_a_decimal_in_a_currency_without_them(self) -> None:
        with pytest.raises(ToolError, match="whole numbers"):
            to_minor("10.5", "JPY")

    def test_refuses_a_negative_amount(self) -> None:
        with pytest.raises(ToolError, match="always positive"):
            to_minor("-10.00", "EUR")

    @pytest.mark.parametrize("amount", ["", "ten euros", "NaN", "Infinity"])
    def test_refuses_something_that_is_not_a_number(self, amount: str) -> None:
        with pytest.raises(ToolError, match="not an amount"):
            to_minor(amount, "EUR")


class TestDisplay:
    """Tests for the string a reader is meant to quote."""

    def test_money_coming_in_carries_no_sign(self) -> None:
        assert display(4250, "EUR") == "€42.50"

    def test_money_going_out_carries_one(self) -> None:
        assert display(4250, "EUR", negative=True) == "-€42.50"

    def test_zero_never_carries_one(self) -> None:
        assert display(0, "EUR", negative=True) == "€0.00"

    def test_an_unknown_currency_is_named_rather_than_guessed(self) -> None:
        assert display(4250, "SEK") == "SEK 42.50"

    def test_a_total_keeps_its_own_sign(self) -> None:
        # Unlike a transaction, a net is genuinely negative in a month that
        # spent more than it earned.
        assert signed_display(-4250, "EUR") == "-€42.50"
        assert signed_display(4250, "EUR") == "€42.50"


class TestMoney:
    """Tests for the shape every amount is reported in."""

    def test_reports_the_amount_three_ways_and_its_currency(self) -> None:
        assert money(4250, "eur", negative=True) == {
            "amount": "42.50",
            "display": "-€42.50",
            "amount_minor": 4250,
            "currency": "EUR",
        }

    def test_the_exact_integer_is_what_arithmetic_should_use(self) -> None:
        assert money(1, "EUR")["amount_minor"] == 1
