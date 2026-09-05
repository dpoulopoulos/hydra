from app.models.fields import (
    MICRO,
    apportion_minor,
    convert_minor,
    market_value_minor,
    minor_digits,
)


class TestMarketValueMinor:
    """Test valuing a holding from a quantity and a unit price."""

    def test_whole_units_at_a_whole_price(self):
        """Test that ten units at 100.00 are worth 1000.00."""
        # Arrange: Set up ten units and a price of 100.00, which is 10000 cents
        quantity_micro = 10 * MICRO
        price_micro = 10_000 * MICRO

        # Act: Value the holding
        value = market_value_minor(quantity_micro, price_micro)

        # Assert: Verify the holding is worth 1000.00, in cents
        assert value == 100_000

    def test_fractional_units_are_not_lost(self):
        """Test that a fraction of a unit contributes its share of the value."""
        # Arrange: Set up a third of a unit priced at 30.00
        quantity_micro = MICRO // 3
        price_micro = 3_000 * MICRO

        # Act: Value the holding
        value = market_value_minor(quantity_micro, price_micro)

        # Assert: Verify it is worth a third of 30.00, to the nearest cent
        assert value == 1_000

    def test_a_price_below_a_cent_still_counts(self):
        """Test that sub-cent precision in a price survives multiplication.

        A price rounded to whole cents before multiplying would value this
        holding at nothing, which is the error the extra precision exists to
        prevent.
        """
        # Arrange: Set up a million units priced at a hundredth of a cent
        quantity_micro = 1_000_000 * MICRO
        price_micro = MICRO // 100

        # Act: Value the holding
        value = market_value_minor(quantity_micro, price_micro)

        # Assert: Verify the holding is worth 10000 cents rather than zero
        assert value == 10_000

    def test_rounding_is_half_away_from_zero(self):
        """Test that an exact half rounds up rather than to the nearest even."""
        # Arrange: Set up half a unit priced at one cent, which is half a cent
        quantity_micro = MICRO // 2
        price_micro = MICRO

        # Act: Value the holding
        value = market_value_minor(quantity_micro, price_micro)

        # Assert: Verify the half cent rounded up to one
        assert value == 1

    def test_nothing_held_is_worth_nothing(self):
        """Test that an empty position has no value, whatever the price."""
        # Arrange: Set up no units at a real price
        price_micro = 10_000 * MICRO

        # Act: Value the empty holding
        value = market_value_minor(0, price_micro)

        # Assert: Verify it is worth nothing
        assert value == 0


class TestConvertMinor:
    """Test converting an amount at an exchange rate."""

    def test_converts_at_the_rate(self):
        """Test that an amount is scaled by the rate."""
        # Arrange: Set up 100.00 and a rate of 0.92
        amount_minor = 10_000
        rate_micro = 920_000

        # Act: Convert the amount
        converted = convert_minor(amount_minor, rate_micro)

        # Assert: Verify 100.00 became 92.00
        assert converted == 9_200

    def test_the_identity_rate_changes_nothing(self):
        """Test that converting a currency into itself is a no-op."""
        # Arrange: Set up an amount and a rate of one
        amount_minor = 12_345

        # Act: Convert at the identity rate
        converted = convert_minor(amount_minor, MICRO)

        # Assert: Verify the amount is unchanged
        assert converted == amount_minor

    def test_a_negative_amount_keeps_its_sign(self):
        """Test that a loss converts to a loss rather than drifting to zero."""
        # Arrange: Set up a negative amount and a rate of 0.5
        amount_minor = -101
        rate_micro = MICRO // 2

        # Act: Convert the amount
        converted = convert_minor(amount_minor, rate_micro)

        # Assert: Verify the magnitude rounded away from zero, not towards it
        assert converted == -51


class TestApportionMinor:
    """Test taking the share of an amount that belongs to part of a whole."""

    def test_takes_the_proportional_share(self):
        """Test that half of a whole takes half the amount."""
        # Arrange: Set up a cost basis of 100.00 over ten units
        # Act: Take the share belonging to five of them
        share = apportion_minor(10_000, 5, 10)

        # Assert: Verify half the cost basis left with them
        assert share == 5_000

    def test_selling_in_pieces_takes_the_whole_basis(self):
        """Test that repeated shares leave no residue behind.

        Truncating instead of rounding would leave a cost basis stranded on the
        last piece of a position, which shows up as a gain that was never made.
        """
        # Arrange: Set up a basis that does not divide evenly by three
        remaining = 100

        # Act: Sell the position one unit at a time
        for units_left in (3, 2, 1):
            remaining -= apportion_minor(remaining, 1, units_left)

        # Assert: Verify nothing is left behind
        assert remaining == 0

    def test_nothing_held_yields_nothing(self):
        """Test that a share of an empty position is zero rather than an error."""
        # Arrange & Act: Take a share of a position holding nothing
        share = apportion_minor(10_000, 5, 0)

        # Assert: Verify the share is zero
        assert share == 0


class TestMinorDigits:
    """Test how many decimal places a currency uses."""

    def test_the_usual_currency_has_two(self):
        """Test that an unlisted currency is assumed to have two decimals."""
        # Arrange & Act: Ask for a currency that is not an exception
        # Assert: Verify it has the usual two
        assert minor_digits("EUR") == 2
        assert minor_digits("USD") == 2

    def test_a_currency_with_no_decimals(self):
        """Test that a zero-decimal currency is not given cents it has no use for."""
        # Arrange & Act & Assert: Verify the yen has no minor unit
        assert minor_digits("JPY") == 0

    def test_a_currency_with_three_decimals(self):
        """Test that a three-decimal currency is not truncated to two."""
        # Arrange & Act & Assert: Verify the dinar has three
        assert minor_digits("KWD") == 3

    def test_the_code_is_read_without_regard_to_case(self):
        """Test that a lower case code finds the same answer."""
        # Arrange & Act & Assert: Verify case does not change the answer
        assert minor_digits("jpy") == minor_digits("JPY")
