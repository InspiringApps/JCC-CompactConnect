"""JCC privilege history shaping for PSYPACT.

Method bodies are the JCC ProviderRecordUtility history helpers. They are attached to
ProviderRecordUtility so the copied privilege history handler can call them without
replacing the Cosmetology provider record utility.
"""
from datetime import UTC, datetime, timedelta

from marshmallow.fields import List, Nested, Raw, String
from marshmallow.validate import ContainsNoneOf

from common_lambdas.config import config
from common_lambdas.data_model.schema.base_record import ForgivingSchema
from common_lambdas.data_model.schema.common import UpdateCategory
from common_lambdas.data_model.schema.fields import Compact, Jurisdiction, UpdateType


class PrivilegeHistoryEventResponseSchema(ForgivingSchema):
    """
    Privilege history event object fields, as seen by the public lookup endpoint.
    Serialization direction:
    Python -> load() -> API
    """

    type = String(required=True, allow_none=False)
    # We specifically prohibit returning investigation updates as a backup protection from accidental
    # disclosure via the API
    updateType = UpdateType(
        required=True,
        allow_none=False,
        validate=ContainsNoneOf((UpdateCategory.INVESTIGATION, UpdateCategory.CLOSING_INVESTIGATION)),
    )
    dateOfUpdate = Raw(required=True, allow_none=False)
    effectiveDate = Raw(required=True, allow_none=False)
    createDate = Raw(required=True, allow_none=False)
    note = String(required=False, allow_none=True)
    # in the case of encumbrance events, we return the list of categories rather than a note
    npdbCategories = List(String(), required=False, allow_none=True)


class PrivilegeHistoryResponseSchema(ForgivingSchema):
    """
    Privilege history object fields, as seen by the public lookup endpoint.
    Serialization direction:
    Python -> load() -> API
    """

    providerId = Raw(required=True, allow_none=False)
    compact = Compact(required=True, allow_none=False)
    jurisdiction = Jurisdiction(required=True, allow_none=False)
    licenseType = String(required=True, allow_none=False)
    privilegeId = String(required=True, allow_none=False)
    events = List(Nested(PrivilegeHistoryEventResponseSchema(), required=False, allow_none=False))


def get_enriched_history_with_synthetic_updates_from_privilege(
    privilege: dict,
    history: list[dict],
) -> list[dict]:
    """
    Enrich the privilege history with 'synthetic updates'.
    Synthetic updates are pieces of history that are not explicitly recorded in the data
    system, because they occur passively, such as when a privilege expires or because they are redundant.
    These 'synthetic updates' do not have a corresponding record in the database, but we can deduce their
    existence based on the privilege's other data. Because these events are
    'synthetic', they have no actual changes in record values associated with them.
    Example issuance event:
    {
        'type': 'privilegeUpdate',
        'updateType': 'issuance',
        'providerId': <provider_id>,
        'compact': <compact>,
        'jurisdiction': <jurisdiction>,
        'licenseType': <license_type>,
        'effectiveDate': <date_effective>,
        'createDate': <create_date>
        'dateOfUpdate': <date_of_update>,
        'previous': {},
        'updatedValues': {},
    }
    :param privilege: The privilege record whose history we intend to construct
    :param history: The raw history records we intend to extrapolate from
    :return: The enriched privilege history
    """

    # We don't ever serve investigation updates via the API - they're only for internal change history tracking
    history_without_investigations = [
        update
        for update in history
        if update['updateType'] not in (UpdateCategory.INVESTIGATION, UpdateCategory.CLOSING_INVESTIGATION)
    ]
    create_date_sorted_original_history = sorted(history_without_investigations, key=lambda x: x['createDate'])

    # Inject issuance event
    enriched_history = [
        {
            'type': 'privilegeUpdate',
            'updateType': UpdateCategory.ISSUANCE,
            'providerId': privilege['providerId'],
            'compact': privilege['compact'],
            'jurisdiction': privilege['jurisdiction'],
            'licenseType': privilege['licenseType'],
            'effectiveDate': privilege['dateOfIssuance'],
            'createDate': privilege['dateOfIssuance'],
            'previous': {},
            'updatedValues': {},
            'dateOfUpdate': privilege['dateOfIssuance'],
        }
    ] + create_date_sorted_original_history

    renewal_updates = list(filter(lambda x: x['updateType'] == UpdateCategory.RENEWAL, enriched_history))

    now = config.current_standard_datetime

    # Inject expiration events that occurred between events
    for update in renewal_updates:
        date_of_expiration = update['previous']['dateOfExpiration']
        day_after_expiration = date_of_expiration + timedelta(days=1)
        datetime_of_expiration_trigger = datetime.combine(
            day_after_expiration, datetime.min.time(), tzinfo=config.expiration_resolution_timezone
        )
        effective_date_time = datetime.combine(
            update['effectiveDate'], datetime.min.time(), tzinfo=config.expiration_resolution_timezone
        )
        if datetime_of_expiration_trigger <= effective_date_time:
            # We have assigned the maximum time in the day at UTC-4:00 because the expiration event happens at the
            # first second of the date of expiration's passing. However, we want the expiration events to display as
            # occurring on their expiration date and also have any events that occurred during that day come before
            # the expiration chronologically. Putting the datetime of expiration as the max time in the day on the
            # date of expiration best achieves those goals
            effective_datetime_of_expiration = datetime.combine(
                date_of_expiration, datetime.max.time(), tzinfo=config.expiration_resolution_timezone
            )
            enriched_history.append(
                {
                    'type': 'privilegeUpdate',
                    'updateType': UpdateCategory.EXPIRATION,
                    'providerId': privilege['providerId'],
                    'compact': privilege['compact'],
                    'jurisdiction': privilege['jurisdiction'],
                    'licenseType': privilege['licenseType'],
                    'effectiveDate': effective_datetime_of_expiration.astimezone(UTC),
                    'createDate': datetime_of_expiration_trigger.astimezone(UTC),
                    'previous': {},
                    'updatedValues': {},
                    'dateOfUpdate': datetime_of_expiration_trigger.astimezone(UTC),
                }
            )
    # Inject expiration event if currently expired
    privilege_date_of_expiration = privilege['dateOfExpiration']

    privilege_day_after_expiration = privilege_date_of_expiration + timedelta(days=1)
    privilege_datetime_of_expiration_trigger = datetime.combine(
        privilege_day_after_expiration, datetime.min.time(), tzinfo=config.expiration_resolution_timezone
    )

    if privilege_datetime_of_expiration_trigger <= now.astimezone(config.expiration_resolution_timezone):
        # We have assigned the maximum time in the day at UTC-4:00 because the expiration event happens at the
        # first second of the date of expiration's passing. However, we want the expiration events to display as
        # occurring on their expiration date and also have any events that occurred during that day come before
        # the expiration chronologically. Putting the datetime of expiration as the max time in the day on the
        # date of expiration best achieves those goals
        effective_datetime_of_expiration = datetime.combine(
            privilege_date_of_expiration, datetime.max.time(), tzinfo=config.expiration_resolution_timezone
        )
        enriched_history.append(
            {
                'type': 'privilegeUpdate',
                'updateType': UpdateCategory.EXPIRATION,
                'providerId': privilege['providerId'],
                'compact': privilege['compact'],
                'jurisdiction': privilege['jurisdiction'],
                'licenseType': privilege['licenseType'],
                'effectiveDate': effective_datetime_of_expiration.astimezone(UTC),
                'createDate': privilege_datetime_of_expiration_trigger.astimezone(UTC),
                'previous': {},
                'updatedValues': {},
                'dateOfUpdate': privilege_datetime_of_expiration_trigger.astimezone(UTC),
            }
        )

    return sorted(enriched_history, key=lambda x: x['effectiveDate'])

def construct_simplified_privilege_history_object(
    privilege_data: list[dict], should_include_encumbrance_details: bool = True
) -> dict:
    """
    Construct a simplified list of history events to be easily consumed by the front end
    :param privilege_data: All of the records associated with the privilege:
    the privilege, updates, and adverse actions
    :param should_include_encumbrance_details: Whether the response should include verbose information on privilege
    encumbrances
    :return: The simplified and enriched privilege history
    """
    privilege = list(filter(lambda x: x['type'] == 'privilege', privilege_data))[0]
    history = list(filter(lambda x: x['type'] == 'privilegeUpdate', privilege_data))

    enriched_history = ProviderRecordUtility.get_enriched_history_with_synthetic_updates_from_privilege(
        privilege, history
    )

    # Collect notes on event types that have notes if user should see those notes
    for event in enriched_history:
        if (
            event['updateType'] == UpdateCategory.ENCUMBRANCE
            and event.get('encumbranceDetails')
            and should_include_encumbrance_details
        ):
            # In the case of encumbrances, we return the list of npdb categories associated with it
            event['npdbCategories'] = event['encumbranceDetails']['clinicalPrivilegeActionCategories']
        elif event['updateType'] == UpdateCategory.DEACTIVATION and event.get('deactivationDetails'):
            event['note'] = event['deactivationDetails']['note']

    unsanitized_history = {
        'providerId': privilege['providerId'],
        'compact': privilege['compact'],
        'jurisdiction': privilege['jurisdiction'],
        'licenseType': privilege['licenseType'],
        'privilegeId': privilege['privilegeId'],
        'events': enriched_history,
    }
    history_schema = PrivilegeHistoryResponseSchema()

def _install_privilege_history_methods() -> None:
    global ProviderRecordUtility
    from common_lambdas.data_model.provider_record_util import ProviderRecordUtility as _ProviderRecordUtility

    ProviderRecordUtility = _ProviderRecordUtility
    ProviderRecordUtility.get_enriched_history_with_synthetic_updates_from_privilege = staticmethod(
        get_enriched_history_with_synthetic_updates_from_privilege
    )
    ProviderRecordUtility.construct_simplified_privilege_history_object = staticmethod(
        construct_simplified_privilege_history_object
    )


_install_privilege_history_methods()
