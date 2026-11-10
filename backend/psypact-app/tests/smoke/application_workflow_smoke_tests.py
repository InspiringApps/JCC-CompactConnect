"""Walk every caller-driven application workflow edge against a deployed sandbox.

Run from backend/psypact-app:

    python3 tests/smoke/application_workflow_smoke_tests.py

The script reads tests/smoke/smoke_tests_env.json. It creates a provider Cognito
user for a test email, writes that user's provider, license, and authorization
records through the PSYPRO migration schemas, and deletes the user and that
partition at the end. The provider id is the one the migration derives from the
email. A passing run leaves every execution it started in Succeeded, except a
generation an abort scenario stopped. A failed run stops only this run's
still-running executions.

Each scenario creates its own application for that practitioner and fills every
section. Three compact-admin staff users are created for the run and deleted at
the end.

Leave CC_TEST_APPLICATION_EXPIRY_WAIT_SECONDS unset to run the caller-driven
scenarios. Those include reopen after an admin deactivation and after this
script aborts the running execution, with reviews and without them. Those
scenarios need the normal one-year lifetime. Do not deploy
application_workflow_lifetime_seconds while running them.

Set CC_TEST_APPLICATION_EXPIRY_WAIT_SECONDS to run only the expiry scenario.
Deploy that sandbox with "sandbox": true and application_workflow_lifetime_seconds
set to a value shorter than the wait. The wait is the whole scenario budget,
including create, submit, reviewer assignment, and section reviews, so it has to
be longer than the short lifetime plus setup. Also set CC_TEST_APPLICATION_TABLE_NAME
so the scenario can read the application items after reopen. An empty value is
treated as unset.
"""

import importlib.util
import os
import time
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import boto3
import requests
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from smoke_common import (
    SmokeTestFailureException,
    cleanup_test_provider_records,
    config,
    create_test_staff_user,
    delete_test_staff_user,
    get_api_base_url,
    get_staff_user_auth_headers,
    get_user_tokens,
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
_PROVIDER_PASSWORD = 'TestPass123!'  # noqa: S105 test credential for the provider created by this run


class _ProviderLogin:
    """Tokens for the provider user this run creates."""

    def __init__(self):
        self.email: str | None = None
        self.token: str | None = None

    def start(self, email: str) -> None:
        self.email = email
        self.token = None

    def clear(self) -> None:
        self.email = None
        self.token = None

    def headers(self) -> dict:
        if self.token is None:
            if not self.email:
                raise SmokeTestFailureException('Provider login was not started')
            tokens = get_user_tokens(self.email, _PROVIDER_PASSWORD, is_staff=False)
            self.token = tokens['IdToken']
        return {'Authorization': 'Bearer ' + self.token}


_PROVIDER = _ProviderLogin()


class _OwnedExecutions:
    """Executions this process started, and which generation an abort scenario stopped."""

    def __init__(self):
        self.application_ids: list[str] = []
        self.reopened: set[str] = set()
        self.aborted_generation_one: set[str] = set()

    def reset(self):
        self.application_ids.clear()
        self.reopened.clear()
        self.aborted_generation_one.clear()

    def note_created(self, application_id: str):
        self.application_ids.append(application_id)

    def note_reopened(self, application_id: str):
        self.reopened.add(application_id)

    def note_aborted(self, application_id: str):
        self.aborted_generation_one.add(application_id)


_OWNED = _OwnedExecutions()


def _env(name: str) -> str | None:
    value = os.environ.get(name, '').strip()
    return value or None


class ApplicationWalk:
    """One practitioner application and the staff users who review it."""

    def __init__(self, compact: str, staff: dict[str, dict]):
        self.compact = compact
        self.staff = staff
        self.base = f'{get_api_base_url()}/v1/compacts/{compact}/applications'
        self.staff_base = f'{get_api_base_url()}/v1/compacts/{compact}/staff-users/applications'
        self.application_id = None

    def create(self) -> str:
        body = self._call('POST', '', 'applicant', {'types': ['apit'], 'isRenewal': False})
        self.application_id = body['id']
        _OWNED.note_created(self.application_id)
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

    def transition(
        self,
        action: str,
        role: str,
        expected_status: str,
        expected_state: str | None = None,
        notes_for_reviewers: str | None = None,
        complete_reviews: bool | None = None,
    ):
        should_complete = action in COMPLETE_REVIEW_ACTIONS if complete_reviews is None else complete_reviews
        if should_complete:
            self.approve_sections(role)
        self._transition(action, role, expected_status, notes_for_reviewers=notes_for_reviewers)
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
        _OWNED.note_reopened(self.application_id)

    def abort_running_execution(self):
        """Stop this application's running execution and wait until it is recorded."""
        client = boto3.client('stepfunctions')
        execution_arn = _wait_for_running_execution(client, self.application_id)
        client.stop_execution(executionArn=execution_arn, error='SmokeAbort', cause='Smoke test abort')
        _wait_for_execution_status(client, execution_arn, 'ABORTED')
        _OWNED.note_aborted(self.application_id)
        logger.info('Aborted execution %s', execution_arn)
        self._wait_for_status('internal-error')

    def fetch(self) -> dict:
        return self._call('GET', f'/{self.application_id}', 'applicant')

    def fetch_staff(self) -> dict:
        return self._call('GET', f'/{self.application_id}', 'admin')

    def save_section_review(self, role: str, section: str, status: str, note: str | None = None):
        body = {'sectionStatus': status}
        if note is not None:
            body['notesForReviewers'] = note
        self._call('PUT', f'/{self.application_id}/sections/{section}/review', role, body)

    def current_status(self) -> str | None:
        body = self._call('GET', f'/{self.application_id}', 'applicant')
        return body.get('status')

    def _transition(self, action: str, role: str, expected_status: str, notes_for_reviewers: str | None = None):
        request_id = str(uuid4())
        if role == 'applicant' and action == 'SUBMIT':
            self._call('POST', f'/{self.application_id}/submit', role, {'requestId': request_id})
        elif role == 'applicant' and action == 'RESUBMIT':
            self._call('POST', f'/{self.application_id}/resubmit', role, {'requestId': request_id})
        else:
            body = {'action': action, 'requestId': request_id}
            if notes_for_reviewers is not None:
                body['notesForReviewers'] = notes_for_reviewers
            self._call('POST', f'/{self.application_id}/transition', role, body)
        self._wait_for_status(expected_status)

    def _headers(self, role: str) -> dict:
        if role == 'applicant':
            return _PROVIDER.headers()
        staff_role = 'first' if role == 'admin' else role
        email = self.staff[staff_role]['email']
        for attempt in range(3):
            try:
                return get_staff_user_auth_headers(email)
            except ClientError as error:
                code = error.response.get('Error', {}).get('Code')
                if code != 'UnexpectedLambdaException' or attempt == 2:
                    raise
                time.sleep(2)

    def _request(self, method: str, suffix: str, role: str, body: dict | None, params: dict | None):
        base = self.base if role == 'applicant' else self.staff_base
        return requests.request(
            method,
            base + suffix,
            headers={**self._headers(role), 'Content-Type': 'application/json'},
            json=body,
            params=params,
            timeout=30,
        )

    def _call(self, method: str, suffix: str, role: str, body: dict | None = None, params: dict | None = None) -> dict:
        response = self._request(method, suffix, role, body, params)
        if response.status_code in (401, 403) and role == 'applicant':
            _PROVIDER.token = None
        if response.status_code in (401, 403, 409, 504):
            logger.info('Retrying %s %s after %s', method, suffix, response.status_code)
            time.sleep(2)
            response = self._request(method, suffix, role, body, params)
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
    final_review.deactivate()

    committee = _new_walk(compact, staff)
    committee.submit()
    committee.assign(('first', 'second', 'final'), 'first-review')
    committee.override('CommitteeFromSecond', 'committee-review', 'CommitteeFromSecond')
    committee.deactivate()

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


def reopen_preserves_reviews(compact: str, staff: dict[str, dict]):
    """Reopen after admin deactivation and after an aborted execution.

    Each stop is exercised once before any reviews exist and once after the
    first and second reviewers have saved section reviews. The reviewers then
    edit those same reviews on the new generation.
    """
    for stop in ('deactivated', 'aborted'):
        _reopen_without_reviews(compact, staff, stop)
        _reopen_with_reviews(compact, staff, stop)


def _reopen_without_reviews(compact: str, staff: dict[str, dict], stop: str):
    """Assignment after reopen creates the only reviews, and later edits update them."""
    walk = _new_walk(compact, staff)
    walk.submit()
    _assert_no_reviews(walk.fetch_staff())
    _stop_for_reopen(walk, stop)
    walk.reopen()
    _assert_no_reviews(walk.fetch_staff())
    walk.assign(('first', 'second', 'final'), 'first-review')
    _edit_existing_reviews(walk, staff, walk.fetch_staff())
    walk.deactivate()
    logger.info('Reopen without reviews passed after %s for %s', stop, walk.application_id)


def _reopen_with_reviews(compact: str, staff: dict[str, dict], stop: str):
    """Reviews saved before the stop stay, and the same reviewers update them after reopen."""
    walk = _new_walk(compact, staff)
    walk.submit()
    walk.assign(('first', 'second', 'final'), 'first-review')
    walk.approve_sections('first')
    walk.transition('ADVANCE', 'first', 'second-review')
    walk.approve_sections('second')
    before = walk.fetch_staff()
    _stop_for_reopen(walk, stop)
    walk.reopen()
    _assert_same_review_identities(before, walk.fetch_staff())
    walk.assign(('first', 'second', 'final'), 'first-review')
    _edit_existing_reviews(walk, staff, before)
    walk.deactivate()
    logger.info('Reopen with reviews passed after %s for %s', stop, walk.application_id)


def _stop_for_reopen(walk: ApplicationWalk, stop: str):
    if stop == 'deactivated':
        walk.deactivate()
        return
    if stop == 'aborted':
        walk.abort_running_execution()
        return
    raise SmokeTestFailureException(f'Unknown reopen stop {stop}')


def _edit_existing_reviews(walk: ApplicationWalk, staff: dict[str, dict], before: dict):
    """Change the first and second reviews, then require the original review objects."""
    _assert_assigned_reviews(before, staff)
    walk.approve_sections('first')
    walk.save_section_review('first', 'personalInformation', 'rejected', 'reopened-first')
    walk.transition(
        'ADVANCE',
        'first',
        'second-review',
        notes_for_reviewers='reopened-application',
        complete_reviews=False,
    )
    walk.save_section_review('second', 'personalInformation', 'approved', 'reopened-second')
    after = walk.fetch_staff()
    _assert_same_review_identities(before, after)
    _assert_section_review(
        after,
        'personalInformation',
        staff['first']['sub'],
        status='rejected',
        note='reopened-first',
    )
    _assert_section_review(
        after,
        'personalInformation',
        staff['second']['sub'],
        status='approved',
        note='reopened-second',
    )
    _assert_application_review(after, staff['first']['sub'], note='reopened-application')


def _assert_assigned_reviews(body: dict, staff: dict[str, dict]):
    expected = [staff[role]['sub'] for role in ('first', 'second', 'final')]
    _assert_reviewer_subs(_reviews(body), expected, 'application', body.get('id'))
    for section in SECTIONS:
        _assert_reviewer_subs(_reviews(body, section), expected, section, body.get('id'))


def _assert_reviewer_subs(reviews: list, expected_subs: list[str], label: str, application_id):
    subs = [(review.get('reviewer') or {}).get('id') for review in reviews]
    if sorted(subs) != sorted(expected_subs):
        raise SmokeTestFailureException(
            f'{label} reviews on {application_id} were {subs}, expected one each for {expected_subs}'
        )


def _assert_no_reviews(body: dict):
    if _reviews(body):
        raise SmokeTestFailureException(f'Application {body.get("id")} already has application reviews')
    for section in SECTIONS:
        if _reviews(body, section):
            raise SmokeTestFailureException(f'Application {body.get("id")} already has {section} reviews')


def _assert_same_review_identities(before: dict, after: dict):
    _assert_identity_list(_reviews(before), _reviews(after), 'application', before.get('id'))
    for section in SECTIONS:
        _assert_identity_list(
            _reviews(before, section),
            _reviews(after, section),
            section,
            before.get('id'),
        )


def _assert_identity_list(before_reviews: list, after_reviews: list, label: str, application_id):
    before_ids = [_review_identity(review) for review in before_reviews]
    after_ids = [_review_identity(review) for review in after_reviews]
    if before_ids != after_ids:
        raise SmokeTestFailureException(
            f'{label} reviews changed on {application_id}: before {before_ids}, after {after_ids}'
        )


def _assert_section_review(body: dict, section: str, reviewer_sub: str, *, status: str, note: str):
    review = _review_for_sub(_reviews(body, section), reviewer_sub, section)
    if review.get('reviewerSelectedApplicationSectionStatus') != status or review.get('notesForReviewers') != note:
        raise SmokeTestFailureException(
            f'{section} review for {reviewer_sub} was not updated on {body.get("id")}: {review}'
        )


def _assert_application_review(body: dict, reviewer_sub: str, *, note: str):
    review = _review_for_sub(_reviews(body), reviewer_sub, 'application')
    if review.get('notesForReviewers') != note:
        raise SmokeTestFailureException(
            f'Application review for {reviewer_sub} was not updated on {body.get("id")}: {review}'
        )


def _review_for_sub(reviews: list, reviewer_sub: str, label: str) -> dict:
    matches = [review for review in reviews if (review.get('reviewer') or {}).get('id') == reviewer_sub]
    if len(matches) != 1:
        raise SmokeTestFailureException(f'Expected one {label} review for {reviewer_sub}, found {len(matches)}')
    return matches[0]


def _reviews(body: dict, section: str | None = None) -> list:
    if section is None:
        return list(body.get('reviews') or [])
    return list((body.get(section) or {}).get('reviews') or [])


def _review_identity(review: dict) -> tuple:
    reviewer = review.get('reviewer') or {}
    return (review.get('assignmentId'), review.get('reviewerType'), reviewer.get('id'))


def _wait_for_running_execution(client, application_id: str) -> str:
    deadline = time.monotonic() + POLL_SECONDS
    prefix = f'{application_id}-g'
    while time.monotonic() < deadline:
        for state_machine_arn in _application_workflow_state_machines(client):
            paginator = client.get_paginator('list_executions')
            for page in paginator.paginate(stateMachineArn=state_machine_arn, statusFilter='RUNNING'):
                for execution in page.get('executions', []):
                    if str(execution.get('name', '')).startswith(prefix):
                        return execution['executionArn']
        time.sleep(2)
    raise SmokeTestFailureException(f'Application {application_id} has no running execution to abort')


def _wait_for_execution_status(client, execution_arn: str, expected_status: str):
    deadline = time.monotonic() + POLL_SECONDS
    last_status = None
    while time.monotonic() < deadline:
        last_status = client.describe_execution(executionArn=execution_arn).get('status')
        if last_status == expected_status:
            return
        time.sleep(2)
    raise SmokeTestFailureException(f'Execution {execution_arn} stayed {last_status}, expected {expected_status}')


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
    walk.deactivate()


def _load_migrate():
    """The migration module is the only place that dumps provider-table items."""
    module_path = Path(__file__).resolve().parents[2] / 'lambdas' / 'python' / 'psypro-source-query' / 'migrate.py'
    spec = importlib.util.spec_from_file_location('psypro_source_migrate', module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _migrated_provider_items(email: str) -> list[dict]:
    """One approved practitioner, dumped by the same schemas the migration writes."""
    migrate = _load_migrate()
    expiration = (date.today() + timedelta(days=365)).isoformat()
    result = migrate.plan_migration(
        approval_rows=[
            {
                'UserId': 1,
                'authorizationType': 'APIT',
                'ApprovalDate': '2026-01-01',
                'dateOfExpiration': expiration,
                'renewalStatus': 0,
            }
        ],
        home_rows=[{'UserId': 1, 'Abbreviation': 'CO'}],
        demographics={
            1: {
                'firstName': 'Smoke',
                'lastName': 'Provider',
                'birthDate': '1980-01-02',
                'ssn': '1234',
                'mailingAddress1': '1 Main St',
                'mailingCity': 'Denver',
                'mailingState': 'CO',
                'mailingZip': '80202',
            }
        },
        emails={1: email},
        licenses=[
            {
                'userId': 1,
                'jurisdiction': 'CO',
                'licenseType': 'Psychologist',
                'licensureNumber': 'SMOKE-1',
                'issueDate': '2019-05-01',
                'status': 'Active',
            }
        ],
        home_declarations=[
            {
                'userId': 1,
                'StateAbbreviation': 'CO',
                'validated': True,
                'UpdatedAt': '2026-01-01T00:00:00+00:00',
            }
        ],
    )
    missing = {'provider', 'license', 'authorization'} - {item['type'] for item in result['items']}
    if missing:
        raise SmokeTestFailureException(
            'Migration schemas did not produce '
            + ', '.join(sorted(missing))
            + f' records (skippedProviders={result["skippedProviders"]}, skippedLicenses={result["skippedLicenses"]})'
        )
    provider_id = migrate.provider_id_for_email(email)
    if any(item.get('providerId') != provider_id for item in result['items']):
        raise SmokeTestFailureException(f'Migration did not use the email-derived provider id for {email}')
    return result['items']


def _provider_id(items: list[dict]) -> str:
    provider = next(item for item in items if item.get('type') == 'provider')
    return provider['providerId']


def _require_empty_provider_partition(provider_id: str, compact: str) -> None:
    partition_key = f'{compact}#PROVIDER#{provider_id}'
    existing = config.provider_user_dynamodb_table.query(KeyConditionExpression=Key('pk').eq(partition_key), Limit=1)
    if existing.get('Items'):
        raise SmokeTestFailureException(
            f'Provider {provider_id} already has records. Refusing to replace them for this run.'
        )


def _create_provider_user(email: str, provider_id: str, compact: str) -> None:
    """Create the Cognito user whose token carries the email-derived provider id."""
    config.cognito_client.admin_create_user(
        UserPoolId=config.cognito_provider_user_pool_id,
        Username=email,
        UserAttributes=[
            {'Name': 'email', 'Value': email},
            {'Name': 'email_verified', 'Value': 'true'},
            {'Name': 'custom:compact', 'Value': compact},
            {'Name': 'custom:providerId', 'Value': provider_id},
        ],
        MessageAction='SUPPRESS',
    )
    config.cognito_client.admin_set_user_password(
        UserPoolId=config.cognito_provider_user_pool_id,
        Username=email,
        Password=_PROVIDER_PASSWORD,
        Permanent=True,
    )
    logger.info('Created provider user %s', email)


def _delete_provider_user(email: str) -> None:
    config.cognito_client.admin_delete_user(UserPoolId=config.cognito_provider_user_pool_id, Username=email)
    logger.info('Deleted provider user %s', email)


def _put_provider_records(items: list[dict]) -> None:
    with config.provider_user_dynamodb_table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)
    logger.info('Wrote %s migrated provider records', len(items))


def _call_provider_me() -> dict:
    """A cold start can take longer than the shared helper's 10 second timeout."""
    url = config.api_base_url + '/v1/provider-users/me'
    response = requests.get(url, headers=_PROVIDER.headers(), timeout=60)
    if response.status_code in (401, 403):
        _PROVIDER.token = None
        response = requests.get(url, headers=_PROVIDER.headers(), timeout=60)
    if response.status_code != 200:
        raise SmokeTestFailureException(f'Failed to GET provider data. Response: {response.json()}')
    return response.json()


def _application_workflow_state_machines(client) -> list[str]:
    arns = []
    paginator = client.get_paginator('list_state_machines')
    for page in paginator.paginate():
        for machine in page.get('stateMachines', []):
            if 'ApplicationWorkflowApplicationStateMachine' in machine['name']:
                arns.append(machine['stateMachineArn'])
    return arns


def _assert_owned_executions_finished() -> None:
    """Require every execution this run started to be finished.

    An abort scenario's first generation is ABORTED. Every other generation is SUCCEEDED.
    """
    client = boto3.client('stepfunctions')
    checked = 0
    for application_id in _OWNED.application_ids:
        generations = [1]
        if application_id in _OWNED.reopened:
            generations.append(2)
        for generation in generations:
            expected = 'ABORTED' if generation == 1 and application_id in _OWNED.aborted_generation_one else 'SUCCEEDED'
            execution_arn = _execution_arn(client, application_id, generation)
            _wait_for_execution_status(client, execution_arn, expected)
            checked += 1
    logger.info('Checked %s application executions finished', checked)


def _execution_arn(client, application_id: str, generation: int) -> str:
    name = f'{application_id}-g{generation}'
    state_machine_arns = _application_workflow_state_machines(client)
    if not state_machine_arns:
        raise SmokeTestFailureException('Application workflow state machine was not found')
    for state_machine_arn in state_machine_arns:
        execution_arn = state_machine_arn.replace(':stateMachine:', ':execution:', 1) + f':{name}'
        try:
            client.describe_execution(executionArn=execution_arn)
        except ClientError as error:
            code = error.response.get('Error', {}).get('Code')
            if code == 'ExecutionDoesNotExist':
                continue
            raise
        return execution_arn
    raise SmokeTestFailureException(f'Execution {name} was not found')


def _stop_owned_running_executions() -> None:
    """Stop waits this run left behind. Other executions stay running."""
    if not _OWNED.application_ids:
        return
    client = boto3.client('stepfunctions')
    prefixes = tuple(f'{application_id}-g' for application_id in _OWNED.application_ids)
    stopped = 0
    for state_machine_arn in _application_workflow_state_machines(client):
        paginator = client.get_paginator('list_executions')
        for page in paginator.paginate(stateMachineArn=state_machine_arn, statusFilter='RUNNING'):
            for execution in page.get('executions', []):
                if not str(execution.get('name', '')).startswith(prefixes):
                    continue
                execution_arn = execution['executionArn']
                try:
                    client.stop_execution(executionArn=execution_arn, cause='Smoke test cleanup')
                    stopped += 1
                except ClientError as error:
                    code = error.response.get('Error', {}).get('Code')
                    logger.warning('Could not stop %s: %s', execution_arn, code)
    logger.info('Stopped %s running executions from this run', stopped)


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
    _OWNED.reset()
    provider_email = f'application-provider-{uuid4().hex[:8]}@example.com'
    created = []
    provider_id = None
    compact = 'psypact'
    created_provider_user = False
    wrote_provider_records = False
    passed = False
    try:
        items = _migrated_provider_items(provider_email)
        provider_id = _provider_id(items)
        _require_empty_provider_partition(provider_id, compact)
        _create_provider_user(provider_email, provider_id, compact)
        created_provider_user = True
        _PROVIDER.start(provider_email)
        _put_provider_records(items)
        wrote_provider_records = True
        provider = _call_provider_me()
        compact = provider['compact']
        if provider.get('providerId') != provider_id:
            raise SmokeTestFailureException(
                f'Signed-in provider id {provider.get("providerId")} does not match {provider_id}'
            )
        created = _create_staff(compact)
        staff = {role: {'email': email, 'sub': sub} for role, email, sub in created}
        expiry_wait = _env('CC_TEST_APPLICATION_EXPIRY_WAIT_SECONDS')
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
            reopen_preserves_reviews(compact, staff)
        _assert_owned_executions_finished()
        passed = True
        logger.info('Application workflow smoke tests passed')
    finally:
        for role, email, sub in created:
            delete_test_staff_user(email, sub, compact)
            logger.info('Deleted %s reviewer %s', role, email)
        if wrote_provider_records and provider_id:
            cleanup_test_provider_records(provider_id, compact)
        if created_provider_user:
            _delete_provider_user(provider_email)
        _PROVIDER.clear()
        if not passed:
            _stop_owned_running_executions()


if __name__ == '__main__':
    main()
