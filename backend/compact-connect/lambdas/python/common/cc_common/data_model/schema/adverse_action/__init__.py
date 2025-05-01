from datetime import date, datetime
from uuid import UUID

from cc_common.data_model.schema.adverse_action.record import AdverseActionRecordSchema
from cc_common.data_model.schema.common import AdverseActionAgainstEnum, CCDataClass, ClinicalPrivilegeActionCategory


class AdverseActionData(CCDataClass):
    """
    Class representing an Adverse Action with getters and setters for all properties.
    Takes a dict as an argument to the constructor to avoid primitive obsession.
    """

    # Define record schema at the class level
    _record_schema = AdverseActionRecordSchema()

    # Can use setters to set field data
    _requires_data_at_construction = False

    @property
    def compact(self) -> str:
        return self._data['compact']

    @compact.setter
    def compact(self, value: str) -> None:
        self._data['compact'] = value

    @property
    def provider_id(self) -> UUID:
        return self._data['providerId']

    @provider_id.setter
    def provider_id(self, value: UUID) -> None:
        self._data['providerId'] = value

    @property
    def jurisdiction(self) -> str:
        return self._data['jurisdiction']

    @jurisdiction.setter
    def jurisdiction(self, value: str) -> None:
        self._data['jurisdiction'] = value

    @property
    def license_type_abbreviation(self) -> str:
        return self._data['licenseTypeAbbreviation']

    @license_type_abbreviation.setter
    def license_type_abbreviation(self, value: str) -> None:
        self._data['licenseTypeAbbreviation'] = value

    @property
    def license_type(self) -> str:
        return self._data['licenseType']

    @license_type.setter
    def license_type(self, value: str) -> None:
        self._data['licenseType'] = value

    @property
    def action_against(self) -> str:
        return self._data['actionAgainst']

    @action_against.setter
    def action_against(self, action_against_enum: AdverseActionAgainstEnum) -> None:
        self._data['actionAgainst'] = action_against_enum.value

    @property
    def blocks_future_privileges(self) -> bool:
        return self._data['blocksFuturePrivileges']

    @blocks_future_privileges.setter
    def blocks_future_privileges(self, value: bool) -> None:
        self._data['blocksFuturePrivileges'] = value

    @property
    def clinical_privilege_action_category(self) -> str:
        return self._data['clinicalPrivilegeActionCategory']

    @clinical_privilege_action_category.setter
    def clinical_privilege_action_category(
        self, clinical_privilege_action_category_enum: ClinicalPrivilegeActionCategory
    ) -> None:
        self._data['clinicalPrivilegeActionCategory'] = clinical_privilege_action_category_enum.value

    @property
    def creation_effective_date(self) -> date:
        return self._data['creationEffectiveDate']

    @creation_effective_date.setter
    def creation_effective_date(self, value: date) -> None:
        self._data['creationEffectiveDate'] = value

    @property
    def submitting_user(self) -> UUID:
        return self._data['submittingUser']

    @submitting_user.setter
    def submitting_user(self, value: UUID) -> None:
        self._data['submittingUser'] = value

    @property
    def creation_date(self) -> datetime:
        return self._data['creationDate']

    @creation_date.setter
    def creation_date(self, value: datetime) -> None:
        self._data['creationDate'] = value

    @property
    def adverse_action_id(self) -> UUID:
        return self._data['adverseActionId']

    @property
    def effective_lift_date(self) -> date | None:
        return self._data.get('effectiveLiftDate')

    @effective_lift_date.setter
    def effective_lift_date(self, value: date) -> None:
        self._data['effectiveLiftDate'] = value

    @property
    def lifting_user(self) -> UUID | None:
        return self._data.get('liftingUser')

    @lifting_user.setter
    def lifting_user(self, value: UUID) -> None:
        self._data['liftingUser'] = value
