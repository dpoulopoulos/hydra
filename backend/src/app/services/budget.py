import datetime
import uuid
from collections.abc import Sequence

from sqlmodel import Session

from app.exceptions import (
    BudgetCategoryKindError,
    BudgetExistsError,
    BudgetNotFoundError,
    BudgetOverlapError,
    CategoryNotFoundError,
    DuplicateBudgetCategoryError,
)
from app.models import (
    Budget,
    BudgetBulkUpsert,
    BudgetCopyRequest,
    BudgetCreate,
    BudgetPublic,
    BudgetsPublic,
    BudgetUpdate,
    Category,
    CategoryKind,
    HouseholdContext,
    Message,
)
from app.models.fields import month_key_of, month_start
from app.repositories.budget import BudgetRepository
from app.repositories.category import CategoryRepository


class BudgetService:
    """Provide services for monthly category budgets."""

    def __init__(
        self,
        session: Session,
        budget_repository: BudgetRepository,
        category_repository: CategoryRepository,
    ) -> None:
        """Initialize the budget service.

        Args:
            session: The database session.
            budget_repository: The budget repository instance.
            category_repository: The category repository instance.
        """
        self.session = session
        self.budget_repository = budget_repository
        self.category_repository = category_repository

    def create_budget(self, household: HouseholdContext, budget_create: BudgetCreate) -> BudgetPublic:
        """Set the spending limit of a category for a month.

        Args:
            household: The household context.
            budget_create: The category, month and limit.

        Returns:
            The created budget.

        Raises:
            CategoryNotFoundError: If the category does not exist in the household.
            BudgetCategoryKindError: If the category is an income category.
            BudgetExistsError: If that category already has a limit for that month.
            BudgetOverlapError: If a parent or subcategory is already budgeted that month.
        """
        period_month = month_start(budget_create.month)
        category = self._require_expense_category(household=household, category_id=budget_create.category_id)

        if self.budget_repository.get_for_category_month(
            household_id=household.household_id,
            category_id=category.id,
            period_month=period_month,
        ):
            raise BudgetExistsError(identifier=f"{category.name} in {budget_create.month}") from None

        self._check_no_overlap(household=household, category=category, period_month=period_month)

        budget = Budget(
            household_id=household.household_id,
            category_id=category.id,
            period_month=period_month,
            limit_minor=budget_create.limit_minor,
        )
        self.budget_repository.save(budget)
        self.session.commit()

        return self._to_public(budget)

    def list_budgets(self, household: HouseholdContext, month: str) -> BudgetsPublic:
        """List the budgets of the household for one month.

        Args:
            household: The household context.
            month: The month, in "YYYY-MM" form.

        Returns:
            The budgets, and the total of the limits.
        """
        budgets = self.budget_repository.list_for_month(
            household_id=household.household_id, period_month=month_start(month)
        )

        return self._to_collection(budgets)

    def get_budget(self, household: HouseholdContext, budget_id: uuid.UUID) -> BudgetPublic:
        """Get one budget of the household.

        Args:
            household: The household context.
            budget_id: The ID of the budget.

        Returns:
            The budget.

        Raises:
            BudgetNotFoundError: If the budget does not exist in the household.
        """
        return self._to_public(self._require_budget(household=household, budget_id=budget_id))

    def update_budget(
        self, household: HouseholdContext, budget_id: uuid.UUID, budget_update: BudgetUpdate
    ) -> BudgetPublic:
        """Change the limit of a budget.

        The category and month are not changeable: a budget is identified by
        them, so moving it is setting a different budget.

        Args:
            household: The household context.
            budget_id: The ID of the budget to change.
            budget_update: The new limit.

        Returns:
            The updated budget.

        Raises:
            BudgetNotFoundError: If the budget does not exist in the household.
        """
        budget = self._require_budget(household=household, budget_id=budget_id)
        budget.sqlmodel_update(budget_update.model_dump(exclude_unset=True))
        self.budget_repository.save(budget)
        self.session.commit()

        return self._to_public(budget)

    def delete_budget(self, household: HouseholdContext, budget_id: uuid.UUID) -> Message:
        """Remove a budget.

        Args:
            household: The household context.
            budget_id: The ID of the budget to remove.

        Returns:
            A confirmation message.

        Raises:
            BudgetNotFoundError: If the budget does not exist in the household.
        """
        budget = self._require_budget(household=household, budget_id=budget_id)
        self.budget_repository.delete(budget)
        self.session.commit()

        return Message(message="Budget removed.")

    def bulk_upsert(self, household: HouseholdContext, bulk: BudgetBulkUpsert) -> BudgetsPublic:
        """Replace the whole set of budgets for one month.

        This is what a month-at-a-time editing screen saves, so it is one
        request rather than one per category. A category left out of the set
        has its limit removed.

        Args:
            household: The household context.
            bulk: The month and the complete set of limits.

        Returns:
            The budgets now set for that month.

        Raises:
            DuplicateBudgetCategoryError: If a category appears twice.
            CategoryNotFoundError: If a category does not exist in the household.
            BudgetCategoryKindError: If a category is an income category.
            BudgetOverlapError: If the set budgets both a parent and its subcategory.
        """
        period_month = month_start(bulk.month)
        category_ids = [entry.category_id for entry in bulk.entries]

        if len(category_ids) != len(set(category_ids)):
            raise DuplicateBudgetCategoryError from None

        categories = self._require_expense_categories(household=household, category_ids=category_ids)
        self._check_set_has_no_overlap(categories=list(categories.values()))

        existing = {
            budget.category_id: budget
            for budget in self.budget_repository.list_for_month(
                household_id=household.household_id, period_month=period_month
            )
        }

        for entry in bulk.entries:
            budget = existing.pop(entry.category_id, None)

            if budget:
                budget.limit_minor = entry.limit_minor
            else:
                budget = Budget(
                    household_id=household.household_id,
                    category_id=entry.category_id,
                    period_month=period_month,
                    limit_minor=entry.limit_minor,
                )

            self.budget_repository.add(budget)

        # Whatever the caller did not send is no longer budgeted this month.
        for budget in existing.values():
            self.budget_repository.delete(budget)

        self.budget_repository.flush()
        self.session.commit()

        return self.list_budgets(household=household, month=bulk.month)

    def copy_month(self, household: HouseholdContext, copy_request: BudgetCopyRequest) -> BudgetsPublic:
        """Copy the budgets of one month onto another.

        Budgets do not roll over, so "same as last month" would otherwise mean
        retyping every limit. Overwriting makes the target month a copy of the
        source: a limit the source does not set is removed rather than left in
        place, which would otherwise leave a parent and its child budgeted
        together.

        Args:
            household: The household context.
            copy_request: The source month, the target month, and whether to
                replace limits already set on the target.

        Returns:
            The budgets now set for the target month.

        Raises:
            BudgetExistsError: If the target month already has budgets and
                overwrite was not requested.
        """
        source_month = month_start(copy_request.from_month)
        target_month = month_start(copy_request.to_month)

        source = self.budget_repository.list_for_month(household_id=household.household_id, period_month=source_month)
        existing = {
            budget.category_id: budget
            for budget in self.budget_repository.list_for_month(
                household_id=household.household_id, period_month=target_month
            )
        }

        if existing and not copy_request.overwrite:
            raise BudgetExistsError(identifier=copy_request.to_month) from None

        for budget in source:
            target = existing.pop(budget.category_id, None)

            if target:
                target.limit_minor = budget.limit_minor
                self.budget_repository.add(target)
            else:
                self.budget_repository.add(
                    Budget(
                        household_id=household.household_id,
                        category_id=budget.category_id,
                        period_month=target_month,
                        limit_minor=budget.limit_minor,
                    )
                )

        # What the source does not budget is no longer budgeted on the target.
        for budget in existing.values():
            self.budget_repository.delete(budget)

        self.budget_repository.flush()
        self.session.commit()

        return self.list_budgets(household=household, month=copy_request.to_month)

    def _check_no_overlap(self, household: HouseholdContext, category: Category, period_month: datetime.date) -> None:
        """Check that neither the category's parent nor its children are budgeted.

        A limit on a parent already covers everything filed under it, so
        budgeting both would count the same spending twice.

        Args:
            household: The household context.
            category: The category being budgeted.
            period_month: The first day of the month.

        Raises:
            BudgetOverlapError: If a parent or subcategory is already budgeted.
        """
        related_ids: list[uuid.UUID] = []

        if category.parent_id is not None:
            related_ids.append(category.parent_id)
        else:
            related_ids.extend(
                child.id
                for child in self.category_repository.list_for_household(
                    household_id=household.household_id, include_archived=True, parent_id=category.id
                )
            )

        clashes = self.budget_repository.get_for_categories_month(
            household_id=household.household_id, category_ids=related_ids, period_month=period_month
        )

        if not clashes:
            return

        other = self.category_repository.get_for_household(
            entity_id=clashes[0].category_id, household_id=household.household_id
        )
        other_name = other.name if other else "another category"

        if category.parent_id is not None:
            raise BudgetOverlapError(parent_name=other_name, child_name=category.name) from None

        raise BudgetOverlapError(parent_name=category.name, child_name=other_name) from None

    def _check_set_has_no_overlap(self, categories: Sequence[Category]) -> None:
        """Check that a set of categories contains no parent and child pair.

        Args:
            categories: The categories being budgeted together.

        Raises:
            BudgetOverlapError: If the set contains both a parent and its subcategory.
        """
        by_id = {category.id: category for category in categories}

        for category in categories:
            parent = by_id.get(category.parent_id) if category.parent_id else None

            if parent:
                raise BudgetOverlapError(parent_name=parent.name, child_name=category.name) from None

    def _require_expense_category(self, household: HouseholdContext, category_id: uuid.UUID) -> Category:
        """Load an expense category of the household.

        Args:
            household: The household context.
            category_id: The ID of the category.

        Returns:
            The category.

        Raises:
            CategoryNotFoundError: If the category does not exist in the household.
            BudgetCategoryKindError: If the category is an income category.
        """
        category = self.category_repository.get_for_household(
            entity_id=category_id, household_id=household.household_id
        )

        if not category:
            raise CategoryNotFoundError from None

        if category.kind is not CategoryKind.EXPENSE:
            raise BudgetCategoryKindError(name=category.name) from None

        return category

    def _require_expense_categories(
        self, household: HouseholdContext, category_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, Category]:
        """Load several expense categories of the household in one query.

        Args:
            household: The household context.
            category_ids: The IDs of the categories.

        Returns:
            The categories, keyed by ID.

        Raises:
            CategoryNotFoundError: If any category does not exist in the household.
            BudgetCategoryKindError: If any category is an income category.
        """
        categories = self.category_repository.get_many_for_household(
            category_ids=category_ids, household_id=household.household_id
        )
        found = {category.id: category for category in categories}

        if len(found) != len(set(category_ids)):
            raise CategoryNotFoundError from None

        for category in found.values():
            if category.kind is not CategoryKind.EXPENSE:
                raise BudgetCategoryKindError(name=category.name) from None

        return found

    def _require_budget(self, household: HouseholdContext, budget_id: uuid.UUID) -> Budget:
        """Load a budget of the household.

        Args:
            household: The household context.
            budget_id: The ID of the budget.

        Returns:
            The budget.

        Raises:
            BudgetNotFoundError: If the budget does not exist in the household.
        """
        budget = self.budget_repository.get_for_household(entity_id=budget_id, household_id=household.household_id)

        if not budget:
            raise BudgetNotFoundError from None

        return budget

    def _to_public(self, budget: Budget) -> BudgetPublic:
        """Build the public representation of a budget.

        Args:
            budget: The budget.

        Returns:
            The public budget, with the month rendered as "YYYY-MM".
        """
        return BudgetPublic.model_validate(budget, update={"month": month_key_of(budget.period_month)})

    def _to_collection(self, budgets: Sequence[Budget]) -> BudgetsPublic:
        """Build the public representation of a set of budgets.

        Args:
            budgets: The budgets.

        Returns:
            The public budgets, and the total of the limits.
        """
        data = [self._to_public(budget) for budget in budgets]

        return BudgetsPublic(
            data=data,
            count=len(data),
            total_limit_minor=sum(budget.limit_minor for budget in data),
        )
