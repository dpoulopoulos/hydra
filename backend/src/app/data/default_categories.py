from typing import Final, NamedTuple

# The parent that holds the fallback category. It is created as a system
# category, so a transaction always has somewhere to live even if the user
# archives everything else.
SYSTEM_CATEGORY_NAME: Final = "Other"


class DefaultCategory(NamedTuple):
    """One entry of the category tree a new household starts with."""

    name: str
    children: tuple[str, ...] = ()
    icon: str | None = None
    is_income: bool = False
    is_system: bool = False


# Plain data, with no imports from the models, so the tree can be reviewed and
# tested on its own. The service turns it into rows.
DEFAULT_CATEGORIES: Final[tuple[DefaultCategory, ...]] = (
    DefaultCategory(
        name="Housing",
        icon="home",
        children=("Rent / Mortgage", "Utilities", "Internet & Phone", "Home Maintenance", "Home Insurance"),
    ),
    DefaultCategory(
        name="Food & Drink",
        icon="utensils",
        children=("Groceries", "Restaurants", "Cafes", "Takeaway & Delivery"),
    ),
    DefaultCategory(
        name="Transport",
        icon="bus",
        children=(
            "Fuel",
            "Public Transport",
            "Taxi & Rideshare",
            "Parking & Tolls",
            "Car Maintenance",
            "Car Insurance",
        ),
    ),
    DefaultCategory(
        name="Shopping",
        icon="shopping-bag",
        children=("Clothing", "Electronics", "Household Goods", "Gifts"),
    ),
    DefaultCategory(
        name="Health",
        icon="heart-pulse",
        children=("Pharmacy", "Doctor & Dentist", "Health Insurance", "Fitness"),
    ),
    DefaultCategory(
        name="Entertainment",
        icon="tv",
        children=("Subscriptions", "Events & Cinema", "Books", "Games", "Hobbies"),
    ),
    DefaultCategory(
        name="Travel",
        icon="plane",
        children=("Flights", "Accommodation", "Activities"),
    ),
    DefaultCategory(
        name="Personal Care",
        icon="scissors",
        children=("Hair & Beauty", "Cosmetics"),
    ),
    DefaultCategory(
        name="Education",
        icon="graduation-cap",
        children=("Courses & Tuition", "Books & Materials"),
    ),
    DefaultCategory(
        name="Financial",
        icon="landmark",
        children=("Bank Fees", "Loan Interest", "Taxes", "Savings & Investments"),
    ),
    DefaultCategory(
        name="Family & Pets",
        icon="baby",
        children=("Childcare", "School", "Pet Food", "Vet"),
    ),
    DefaultCategory(
        name="Income",
        icon="wallet",
        is_income=True,
        children=("Salary", "Bonus", "Freelance", "Investment Income", "Refunds", "Gifts Received"),
    ),
    DefaultCategory(
        name=SYSTEM_CATEGORY_NAME,
        icon="circle-dashed",
        is_system=True,
        children=("Uncategorized",),
    ),
)
