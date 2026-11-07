"""Walk every caller-driven application workflow edge against a deployed sandbox.

Run from backend/psypact-app:

    python3 tests/smoke/application_workflow_smoke_tests.py

The script reads tests/smoke/smoke_tests_env.json. Each scenario creates its own
application for the configured test practitioner and fills every section. Three
compact-admin staff users are created for the run and deleted at the end.

Leave CC_TEST_APPLICATION_EXPIRY_WAIT_SECONDS unset to run the five caller-driven
scenarios. Those scenarios need the normal one-year lifetime. Do not deploy
application_workflow_lifetime_seconds while running them.

Set CC_TEST_APPLICATION_EXPIRY_WAIT_SECONDS to run only the expiry scenario.
Deploy that sandbox with "sandbox": true and application_workflow_lifetime_seconds
set to a value shorter than the wait. The wait is the whole scenario budget,
including create, submit, reviewer assignment, and section reviews, so it has to
be longer than the short lifetime plus setup. Also set CC_TEST_APPLICATION_TABLE_NAME
so the scenario can read the application items after reopen. An empty value is
treated as unset.
"""

import os
import time
from uuid import uuid4

import boto3
import requests
from boto3.dynamodb.conditions import Key
from smoke_common import (
    SmokeTestFailureException,
    call_provider_users_me_endpoint,
    create_test_staff_user,
    delete_test_staff_user,
    get_api_base_url,
    get_provider_user_auth_headers_cached,
    get_staff_user_auth_headers,
    load_smoke_test_env,
    logger,
)

SECTIONS = (
    'personalInformation',
    'licenseHistory',
    'education',
    'conductHistory',
    'homeState',
    'acknowledgements',
)
SECTION_BODIES = {
    'personalInformation': {'firstName': 'Smoke', 'lastName': 'Applicant'},
    'licenseHistory': {'licenses': [{'state': 'co', 'licenseNumber': '1', 'status': 'active'}]},
    'education': {'institution': 'Smoke University', 'isCompleted': True},
    'conductHistory': {'notes': 'No conduct history to report'},
    'homeState': {'applicationTypes': [{'applicationType': 'apit', 'state': 'co'}]},
    'acknowledgements': {'signatureName': 'Smoke Applicant', 'attestations': ['acknowledged']},
}
COMPLETE_REVIEW_ACTIONS = frozenset({'ADVANCE', 'APPROVE', 'REJECT'})
POLL_SECONDS = 90


def _env(name: str) -> str | None:
    value = os.environ.get(name, '').strip()
    return value or None


class ApplicationWalk:
    """One practitioner application and the staff users who review it."""

    def __init__(self, compact: str, staff: dict[str, dict]):
        self.compact = compact
        self.staff = staff
        self.base = f'{get_api_base_url()}/v1/compacts/{compact}/applications'
        self.application_id = None

    def create(self) -> str:
        body = self._call('POST', '', 'applicant', {'types': ['apit'], 'isRenewal': False})
        self.application_id = body['id']
        self._wait_for_status('started')
        for section in SECTIONS:
            self._call('PATCH', f'/{self.application_id}/sections/{section}', 'applicant', SECTION_BODIES[section])
        logger.info('Created application %s', self.application_id)
        return self.application_id

    def submit(self):
        self._transition('SUBMIT', 'applicant', 'staff-review')

    def assign(self, roles: tuple[str, ...], expected_status: str):
        body = {f'{role}ReviewerSub': self.staff[role]['sub'] for role in roles}
        self._call('PUT', f'/{self.application_id}/reviewers', 'admin', body)
        self._wait_for_status(expected_status)

    def approve_sections(self, role: str):
        for section in SECTIONS:
            self._call(
                'PUT',
                f'/{self.application_id}/sections/{section}/review',
                role,
                {'sectionStatus': 'approved'},
            )

    def transition(self, action: str, role: str, expected_status: str, expected_state: str | None = None):
        if action in COMPLETE_REVIEW_ACTIONS:
            self.approve_sections(role)
        self._transition(action, role, expected_status)
        if expected_state:
            self._wait_for_state(expected_status, expected_state)

    def override(self, target_state: str, expected_status: str, expected_state: str | None = None):
        self._call(
            'POST',
            f'/{self.application_id}/admin/status',
            'admin',
            {'targetState': target_state, 'reason': 'Smoke override', 'requestId': str(uuid4())},
        )
        self._wait_for_status(expected_status)
        if expected_state:
            self._wait_for_state(expected_status, expected_state)

    def deactivate(self):
        self._transition('ADMIN_DEACTIVATE', 'admin', 'deactivated')

    def reopen(self):
        self._call(
            'POST',
            f'/{self.application_id}/reopen',
            'admin',
            {'requestId': str(uuid4()), 'reason': 'Smoke reopen'},
        )
        self._wait_for_status('staff-review')

    def current_status(self) -> str | None:
        body = self._call('GET', f'/{self.application_id}', 'applicant')
        return body.get('status')

    def _transition(self, action: str, role: str, expected_status: str):
        self._call(
            'POST',
            f'/{self.application_id}/transition',
            role,
            {'action': action, 'requestId': str(uuid4())},
        )
        self._wait_for_status(expected_status)

    def _headers(self, role: str) -> dict:
        if role == 'applicant':
            return get_provider_user_auth_headers_cached()
        staff_role = 'first' if role == 'admin' else role
        return get_staff_user_auth_headers(self.staff[staff_role]['email'])

    def _call(self, method: str, suffix: str, role: str, body: dict | None = None, params: dict | None = None) -> dict:
        response = requests.request(
            method,
            self.base + suffix,
            headers={**self._headers(role), 'Content-Type': 'application/json'},
            json=body,
            params=params,
            timeout=30,
        )
        if response.status_code == 409:
            logger.info('Retrying %s %s after a conflict', method, suffix)
            time.sleep(2)
            response = requests.request(
                method,
                self.base + suffix,
                headers={**self._headers(role), 'Content-Type': 'application/json'},
                json=body,
                params=params,
                timeout=30,
            )
        if response.status_code not in (200, 202):
            raise SmokeTestFailureException(f'{method} {suffix} returned {response.status_code}: {response.text}')
        if not response.content:
            return {}
        return response.json()

    def _wait_for_status(self, expected_status: str):
        deadline = time.monotonic() + POLL_SECONDS
        last_status = None
        while time.monotonic() < deadline:
            body = self._call('GET', f'/{self.application_id}', 'applicant')
            last_status = body.get('status')
            if last_status == expected_status:
                logger.info('Application %s status is %s', self.application_id, expected_status)
                return
            time.sleep(2)
        raise SmokeTestFailureException(
            f'Application {self.application_id} status stayed {last_status}, expected {expected_status}'
        )

    def _wait_for_state(self, status: str, expected_state: str):
        deadline = time.monotonic() + POLL_SECONDS
        last_key = None
        while time.monotonic() < deadline:
            params = {'status': status, 'pageSize': '100'}
            if last_key:
                params['lastKey'] = last_key
            page = self._call('GET', '', 'admin', params=params)
            for item in page.get('items') or []:
                if item.get('id') == self.application_id and item.get('stateName') == expected_state:
                    logger.info('Application %s state is %s', self.application_id, expected_state)
                    return
            last_key = (page.get('pagination') or {}).get('lastKey')
            if not last_key:
                time.sleep(2)
        raise SmokeTestFailureException(
            f'Application {self.application_id} did not show state {expected_state} on the {status} list'
        )


def _new_walk(compact: str, staff: dict[str, dict]) -> ApplicationWalk:
    walk = ApplicationWalk(compact, staff)
    walk.create()
    return walk


def _reach_second_review(walk: ApplicationWalk):
    walk.submit()
    walk.assign(('first', 'second', 'final'), 'first-review')
    walk.transition('ADVANCE', 'first', 'second-review')


def _reach_final_review(walk: ApplicationWalk):
    _reach_second_review(walk)
    walk.transition('ADVANCE', 'second', 'final-review')


def first_review_loops_then_approve(compact: str, staff: dict[str, dict]):
    """First-review return and changes loops, then approve through final review."""
    walk = _new_walk(compact, staff)
    walk.submit()
    walk.assign(('first', 'second', 'final'), 'first-review')
    walk.transition('REQUEST_CHANGES', 'first', 'awaiting-applicant')
    walk.transition('RESUBMIT', 'applicant', 'first-review')
    walk.transition('SEND_TO_COMMITTEE', 'first', 'committee-review')
    walk.transition('RETURN_TO_REVIEW', 'first', 'first-review')
    walk.transition('SEND_TO_COMMITTEE', 'first', 'committee-review')
    walk.transition('ADVANCE', 'first', 'second-review')
    walk.transition('ADVANCE', 'second', 'final-review')
    walk.transition('APPROVE', 'final', 'approved')


def second_review_loops_then_reject(compact: str, staff: dict[str, dict]):
    """Second-review loops. Resubmit returns to second review, then the committee advances."""
    walk = _new_walk(compact, staff)
    _reach_second_review(walk)
    walk.transition('REQUEST_CHANGES', 'second', 'awaiting-applicant')
    walk.transition('RESUBMIT', 'applicant', 'second-review')
    walk.transition('SEND_TO_COMMITTEE', 'second', 'committee-review')
    walk.transition('RETURN_TO_REVIEW', 'second', 'second-review')
    walk.transition('SEND_TO_COMMITTEE', 'second', 'committee-review')
    walk.transition('REQUEST_CHANGES', 'second', 'awaiting-applicant')
    walk.transition('RESUBMIT', 'applicant', 'second-review')
    # The resubmit above leaves second review. Send it back so committee advance can skip the return.
    walk.transition('SEND_TO_COMMITTEE', 'second', 'committee-review')
    walk.transition('ADVANCE', 'second', 'final-review')
    walk.transition('REJECT', 'final', 'rejected')


def final_review_loops_then_approve_from_committee(compact: str, staff: dict[str, dict]):
    """Final-review loops. Resubmit returns to final review, then the committee approves."""
    walk = _new_walk(compact, staff)
    _reach_final_review(walk)
    walk.transition('REQUEST_CHANGES', 'final', 'awaiting-applicant')
    walk.transition('RESUBMIT', 'applicant', 'final-review')
    walk.transition('SEND_TO_COMMITTEE', 'final', 'committee-review')
    walk.transition('RETURN_TO_REVIEW', 'final', 'final-review')
    walk.transition('SEND_TO_COMMITTEE', 'final', 'committee-review')
    walk.transition('REQUEST_CHANGES', 'final', 'awaiting-applicant')
    walk.transition('RESUBMIT', 'applicant', 'final-review')
    walk.transition('SEND_TO_COMMITTEE', 'final', 'committee-review')
    walk.transition('APPROVE', 'final', 'approved')


def committee_changes_then_final_committee_reject(compact: str, staff: dict[str, dict]):
    """A first-committee changes request returns to first review. The final committee rejects."""
    walk = _new_walk(compact, staff)
    walk.submit()
    walk.assign(('first', 'second', 'final'), 'first-review')
    walk.transition('SEND_TO_COMMITTEE', 'first', 'committee-review')
    walk.transition('REQUEST_CHANGES', 'first', 'awaiting-applicant')
    walk.transition('RESUBMIT', 'applicant', 'first-review')
    walk.transition('ADVANCE', 'first', 'second-review')
    walk.transition('ADVANCE', 'second', 'final-review')
    walk.transition('SEND_TO_COMMITTEE', 'final', 'committee-review')
    walk.transition('REJECT', 'final', 'rejected')


def admin_override_and_deactivate(compact: str, staff: dict[str, dict]):
    """One application per admin outcome, so an earlier terminal state cannot hide the next edge."""
    final_review = _new_walk(compact, staff)
    final_review.submit()
    final_review.assign(('final',), 'staff-review')
    final_review.override('FinalReview', 'final-review')

    committee = _new_walk(compact, staff)
    committee.submit()
    committee.assign(('first', 'second', 'final'), 'first-review')
    committee.override('CommitteeFromSecond', 'committee-review', 'CommitteeFromSecond')

    approved = _new_walk(compact, staff)
    _reach_second_review(approved)
    approved.override('Approved', 'approved')

    rejected = _new_walk(compact, staff)
    _reach_final_review(rejected)
    rejected.override('Rejected', 'rejected')

    overridden = _new_walk(compact, staff)
    overridden.submit()
    overridden.override('Deactivated', 'deactivated')

    deactivated = _new_walk(compact, staff)
    deactivated.submit()
    deactivated.assign(('first', 'second', 'final'), 'first-review')
    deactivated.deactivate()


def _application_items(compact: str, application_id: str) -> list[dict]:
    table_name = _env('CC_TEST_APPLICATION_TABLE_NAME')
    if not table_name:
        raise SmokeTestFailureException('CC_TEST_APPLICATION_TABLE_NAME is required for the expiry scenario')
    table = boto3.resource('dynamodb').Table(table_name)
    items = []
    last_key = None
    while True:
        query = {
            'KeyConditionExpression': Key('pk').eq(f'{compact}#APPLICATION#{application_id}'),
            'ConsistentRead': True,
        }
        if last_key:
            query['ExclusiveStartKey'] = last_key
        page = table.query(**query)
        items.extend(page.get('Items') or [])
        last_key = page.get('LastEvaluatedKey')
        if not last_key:
            return items


def _assert_preserved(compact: str, application_id: str, staff: dict[str, dict]):
    items = _application_items(compact, application_id)
    application = next((item for item in items if item.get('sk') == 'APPLICATION'), None)
    if application is None:
        raise SmokeTestFailureException(f'Application {application_id} has no APPLICATION item after reopen')
    for role in ('first', 'second', 'final'):
        field_name = f'{role}ReviewerSub'
        if application.get(field_name) != staff[role]['sub']:
            raise SmokeTestFailureException(f'{field_name} was not preserved on {application_id}')
    section_items = [item for item in items if str(item.get('sk', '')).startswith('SECTION#')]
    if len(section_items) != len(SECTIONS):
        raise SmokeTestFailureException(f'Application {application_id} is missing section items after reopen')
    preserved = [
        review
        for item in section_items
        for review in item.get('reviews') or []
        if (review.get('reviewer') or {}).get('id') == staff['first']['sub']
    ]
    if len(preserved) != len(SECTIONS):
        raise SmokeTestFailureException(f'Section reviews were not preserved on {application_id}')


def expiry_then_reopen(compact: str, staff: dict[str, dict]):
    """Wait for the sandbox expiry schedule, reopen, and continue the new generation."""
    wait_seconds = int(_env('CC_TEST_APPLICATION_EXPIRY_WAIT_SECONDS') or '0')
    deadline = time.monotonic() + wait_seconds
    walk = _new_walk(compact, staff)
    walk.submit()
    walk.assign(('first', 'second', 'final'), 'first-review')
    walk.approve_sections('first')
    while time.monotonic() < deadline:
        if walk.current_status() == 'deactivated':
            break
        time.sleep(5)
    else:
        raise SmokeTestFailureException(
            f'Application {walk.application_id} did not deactivate within {wait_seconds} seconds. '
            'Deploy the sandbox with a shorter application_workflow_lifetime_seconds.'
        )
    logger.info('Application %s deactivated by expiry', walk.application_id)
    walk.reopen()
    _assert_preserved(compact, walk.application_id, staff)
    walk.transition('REVIEWERS_ASSIGNED', 'admin', 'first-review')


def _create_staff(compact: str) -> list[tuple[str, str, str]]:
    created = []
    permissions = {'actions': {'admin'}, 'jurisdictions': {}}
    for role in ('first', 'second', 'final'):
        email = f'application-{role}-{uuid4().hex[:8]}@example.com'
        sub = create_test_staff_user(email=email, compact=compact, jurisdiction='co', permissions=permissions)
        created.append((role, email, sub))
    return created


def main():
    load_smoke_test_env()
    provider = call_provider_users_me_endpoint()
    compact = provider['compact']
    created = _create_staff(compact)
    staff = {role: {'email': email, 'sub': sub} for role, email, sub in created}
    expiry_wait = _env('CC_TEST_APPLICATION_EXPIRY_WAIT_SECONDS')
    try:
        if expiry_wait:
            logger.info('Running the expiry scenario only')
            expiry_then_reopen(compact, staff)
        else:
            logger.info('Expiry scenario skipped. Set CC_TEST_APPLICATION_EXPIRY_WAIT_SECONDS to run it alone.')
            first_review_loops_then_approve(compact, staff)
            second_review_loops_then_reject(compact, staff)
            final_review_loops_then_approve_from_committee(compact, staff)
            committee_changes_then_final_committee_reject(compact, staff)
            admin_override_and_deactivate(compact, staff)
        logger.info('Application workflow smoke tests passed')
    finally:
        for role, email, sub in created:
            delete_test_staff_user(email, sub, compact)
            logger.info('Deleted %s reviewer %s', role, email)


if __name__ == '__main__':
    main()
