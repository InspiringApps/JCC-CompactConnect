import os
from copy import deepcopy
from unittest import TestCase

os.environ.setdefault('COMPACTS', '["aslp", "octp", "coun", "psypact"]')
os.environ.setdefault('JURISDICTIONS', '["oh"]')

from cc_common.applicants.schema.api import (  # noqa: E402
    ApplicationResponseSchema,
    AssignReviewersRequestSchema,
    ResponseDocumentSchema,
    SetApplicationStatusRequestSchema,
    TransitionRequestSchema,
    assemble_application_response,
    section_patch_schema,
)
from cc_common.applicants.schema.calculated import (  # noqa: E402
    calculate_applicant_status,
    calculate_review_comparison,
)
from cc_common.applicants.schema.records import (  # noqa: E402
    ApplicationData,
    ApplicationRecordSchema,
    ApplicationRequestRecordSchema,
    ApplicationSectionRecordSchema,
    ApplicationTransitionRecordSchema,
)
from cc_common.applicants.schema.reviews import (  # noqa: E402
    ApplicationReviewSchema,
    ApplicationSectionReviewSchema,
)
from cc_common.applicants.schema.sections import (  # noqa: E402
    HomeStateApplicationTypeSchema,
    LicenseHistorySchema,
    PersonalInformationSchema,
    StoredDocumentSchema,
)
from common_lambdas.data_model.schema.base_record import BaseRecordSchema  # noqa: E402
from marshmallow import ValidationError  # noqa: E402

COMPACT = 'psypact'
APPLICATION_ID = 'app-1'

FULL_APPLICATION = {
    'compact': COMPACT,
    'applicationId': APPLICATION_ID,
    'providerId': 'provider-1',
    'types': ['apit', 'tap'],
    'isRenewal': False,
    'status': 'staff-review',
    'stateName': 'StaffReview',
    'executionArn': 'arn:aws:states:us-east-1:1:execution:app',
    'generation': 1,
    'workflowExpiresAt': '2027-01-01T00:00:00+00:00',
    'scheduleName': 'app-1-expiry',
    'taskToken': 'token',
    'taskTokenHash': 'hash',
    'version': 3,
    'pendingAction': {
        'requestId': 'req-1',
        'action': 'SUBMIT',
        'actorSub': 'applicant-sub',
        'expectedStateName': 'Started',
        'expectedVersion': 2,
        'attempts': 1,
        'createdAt': '2026-01-01T00:00:00+00:00',
        'expectedLastEnteredKey': 'arn#time#Started',
    },
    'lastEnteredKey': 'arn#time#StaffReview',
    'reopenLock': {
        'requestId': 'reopen-1',
        'oldGeneration': 1,
        'oldExecutionArn': 'arn:old',
        'workflowExpiresAt': '2027-11-06T00:00:00+00:00',
    },
    'lastExecutionError': None,
    'deactivationReason': None,
    'created': '2026-01-01T00:00:00+00:00',
    'submitted': '2026-01-02T00:00:00+00:00',
    'completed': None,
    'attestations': ['attestation-1'],
    'paymentCompensated': ['apit'],
    'reviews': [
        {
            'assignmentId': 'assign-1',
            'reviewerType': 'first-reviewer',
            'reviewer': {'id': 'first-sub', 'firstName': 'Ada', 'lastName': 'Lovelace'},
            'assignedDate': '2026-01-03T00:00:00+00:00',
            'reviewCompletionDate': None,
            'notesForApplicant': 'please update',
            'notesForReviewers': 'internal',
            'reviewerSelectedApplicationStatus': 'first-review',
        }
    ],
    'firstReviewerSub': 'first-sub',
    'secondReviewerSub': 'second-sub',
    'finalReviewerSub': 'first-sub',
    'firstReviewerAssignmentId': 'assign-1',
    'secondReviewerAssignmentId': 'assign-2',
    'finalReviewerAssignmentId': 'assign-3',
    'firstReviewerFirstName': 'Ada',
    'firstReviewerLastName': 'Lovelace',
    'secondReviewerFirstName': 'Grace',
    'secondReviewerLastName': 'Hopper',
    'finalReviewerFirstName': 'Ada',
    'finalReviewerLastName': 'Lovelace',
    'actorGSIPK': 'psypact#ACTOR#first-sub',
    'actorGSISK': 'staff-review#app-1',
    'notAField': 'drop me',
}

SECTION_PAYLOADS = {
    'personalInformation': {
        'firstName': 'Ada',
        'middleName': 'A',
        'lastName': 'Lovelace',
        'suffix': None,
        'phone': '555',
        'altPhone': None,
        'dob': '1815-12-10',
        'ssnLastFour': '1234',
        'npi': '1234567890',
        'gender': 'female',
        'professionalName': 'A. Lovelace',
        'citizenship': 'UK',
        'placeOfBirth': 'London',
        'languages': ['en'],
        'mailingAddress1': '1 Street',
        'mailingAddress2': None,
        'mailingCity': 'London',
        'mailingState': 'LN',
        'mailingZip': '12345',
        'mainingZip': 'typo',
    },
    'licenseHistory': {
        'ePassport': {'mobilityNumber': 'ep-1', 'issueDate': '2020-01-01'},
        'ipc': {'mobilityNumber': 'ipc-1', 'issueDate': '2021-01-01'},
        'licenses': [
            {'state': 'oh', 'issueDate': '2019-01-01', 'licenseNumber': '1', 'status': 'active'},
            {'state': 'ky', 'issueDate': '2022-01-01', 'licenseNumber': '2', 'status': 'inactive'},
        ],
    },
    'education': {
        'nameAtTime': 'Ada',
        'institution': 'State',
        'city': 'London',
        'state': 'LN',
        'degreeType': 'PhD',
        'program': 'Math',
        'department': 'Science',
        'conferredDate': '1840-01-01',
        'isCompleted': True,
        'accreditingBody': 'Board',
        'accreditingYear': '1840',
        'isAccreditedByAuthority': True,
        'isProgramEquivalent': False,
        'accreditingContact': {
            'name': 'Contact',
            'email': 'c@example.com',
            'city': 'London',
            'state': 'LN',
            'zip': '1',
            'phone': '555',
            'attestations': ['seen'],
        },
        'hasResidence': True,
        'transcripts': [{'filename': 't.pdf', 'sizeBytes': 10, 's3Key': 'edu/t.pdf', 'downloadUri': 'https://secret'}],
    },
    'conductHistory': {
        'attestations': ['none'],
        'convictions': [{'charge': 'none', 'location': 'n/a', 'date': '2020-01-01', 'type': 'n/a'}],
        'notes': 'none',
        'documents': [{'filename': 'c.pdf', 'sizeBytes': 4, 's3Key': 'conduct/c.pdf'}],
    },
    'homeState': {
        'applicationTypes': [
            {
                'applicationType': 'tap',
                'state': 'oh',
                'startDate': '2024-01-01',
                'isActiveMilitary': True,
                'militaryDocuments': [{'filename': 'orders.pdf', 'sizeBytes': 8, 's3Key': 'mil/orders.pdf'}],
                'militarydocuments': [{'filename': 'typo.pdf'}],
                'attestations': ['military'],
            }
        ]
    },
    'acknowledgements': {'attestations': ['signed'], 'signatureName': 'Ada Lovelace'},
}


def _round_trip(schema, payload):
    dumped = schema.dump(deepcopy(payload))
    loaded = schema.load(dumped)
    return dumped, loaded, schema.dump(deepcopy(loaded))


class TestRecordSchemas(TestCase):
    def test_registered_record_types(self):
        self.assertIsInstance(BaseRecordSchema.get_schema_by_type('application'), ApplicationRecordSchema)
        self.assertIsInstance(BaseRecordSchema.get_schema_by_type('applicationSection'), ApplicationSectionRecordSchema)
        self.assertIsInstance(
            BaseRecordSchema.get_schema_by_type('applicationTransition'),
            ApplicationTransitionRecordSchema,
        )
        self.assertIsInstance(BaseRecordSchema.get_schema_by_type('applicationRequest'), ApplicationRequestRecordSchema)

    def test_application_record_empty_and_full_round_trip(self):
        schema = ApplicationRecordSchema()
        empty_dump, empty_loaded, _empty_again = _round_trip(schema, {})
        self.assertEqual('application', empty_loaded['type'])
        self.assertIn('dateOfUpdate', empty_loaded)
        self.assertNotIn('pk', empty_loaded)
        self.assertNotIn('status', empty_dump)

        dumped, loaded, _again = _round_trip(schema, FULL_APPLICATION)
        self.assertEqual(f'{COMPACT}#APPLICATION#{APPLICATION_ID}', dumped['pk'])
        self.assertEqual('APPLICATION', dumped['sk'])
        self.assertEqual(f'{COMPACT}#STATUS#staff-review', dumped['statusGSIPK'])
        self.assertTrue(dumped['statusGSISK'].endswith(f'#{APPLICATION_ID}'))
        self.assertEqual(f'{COMPACT}#PROVIDER#provider-1', dumped['applicantGSIPK'])
        self.assertEqual(APPLICATION_ID, dumped['applicantGSISK'])
        self.assertEqual('psypact#ACTOR#first-sub', dumped['actorGSIPK'])
        self.assertNotIn('pk', loaded)
        self.assertNotIn('sk', loaded)
        self.assertNotIn('notAField', loaded)
        self.assertEqual('staff-review', loaded['status'])
        self.assertEqual('token', loaded['taskToken'])
        self.assertEqual(FULL_APPLICATION['reviews'], loaded['reviews'])
        self.assertEqual(FULL_APPLICATION['pendingAction'], loaded['pendingAction'])
        self.assertEqual(FULL_APPLICATION['reopenLock'], loaded['reopenLock'])

        record = ApplicationData.create_new({'compact': COMPACT, 'applicationId': APPLICATION_ID, 'status': 'started'})
        self.assertEqual(APPLICATION_ID, record.applicationId)
        self.assertEqual('started', record.status)
        stored = record.serialize_to_database_record()
        self.assertEqual('APPLICATION', stored['sk'])
        self.assertNotIn('pk', record.to_dict())

    def test_section_records_round_trip_and_drop_typos(self):
        schema = ApplicationSectionRecordSchema()
        empty_dump, empty_loaded, _empty_again = _round_trip(schema, {})
        self.assertEqual('applicationSection', empty_loaded['type'])
        self.assertNotIn('pk', empty_dump)

        for section_name, data in SECTION_PAYLOADS.items():
            with self.subTest(section_name=section_name):
                dumped, loaded, _again = _round_trip(
                    schema,
                    {
                        'compact': COMPACT,
                        'applicationId': APPLICATION_ID,
                        'sectionName': section_name,
                        'data': data,
                        'updated': '2026-01-01T00:00:00+00:00',
                        'reviews': [
                            {
                                'assignmentId': 'assign-1',
                                'reviewerType': 'second-reviewer',
                                'reviewerSelectedApplicationSectionStatus': 'approved',
                            }
                        ],
                    },
                )
                self.assertEqual(f'SECTION#{section_name}', dumped['sk'])
                self.assertNotIn('mainingZip', loaded['data'])
                self.assertNotIn('militarydocuments', str(loaded['data']))
                self.assertNotIn('pk', loaded)

        personal = schema.load(
            schema.dump(
                {
                    'compact': COMPACT,
                    'applicationId': APPLICATION_ID,
                    'sectionName': 'personalInformation',
                    'data': SECTION_PAYLOADS['personalInformation'],
                }
            )
        )
        self.assertEqual('12345', personal['data']['mailingZip'])
        licenses = schema.load(
            schema.dump(
                {
                    'compact': COMPACT,
                    'applicationId': APPLICATION_ID,
                    'sectionName': 'licenseHistory',
                    'data': SECTION_PAYLOADS['licenseHistory'],
                }
            )
        )
        self.assertEqual(2, len(licenses['data']['licenses']))
        education = schema.load(
            schema.dump(
                {
                    'compact': COMPACT,
                    'applicationId': APPLICATION_ID,
                    'sectionName': 'education',
                    'data': SECTION_PAYLOADS['education'],
                }
            )
        )
        self.assertEqual('edu/t.pdf', education['data']['transcripts'][0]['s3Key'])
        self.assertNotIn('downloadUri', education['data']['transcripts'][0])
        home = schema.load(
            schema.dump(
                {
                    'compact': COMPACT,
                    'applicationId': APPLICATION_ID,
                    'sectionName': 'homeState',
                    'data': SECTION_PAYLOADS['homeState'],
                }
            )
        )
        self.assertEqual('mil/orders.pdf', home['data']['applicationTypes'][0]['militaryDocuments'][0]['s3Key'])

    def test_transition_and_request_records(self):
        transition_schema = ApplicationTransitionRecordSchema()
        _empty_dump, empty_loaded, _empty_again = _round_trip(transition_schema, {})
        self.assertEqual('applicationTransition', empty_loaded['type'])

        transition = {
            'compact': COMPACT,
            'applicationId': APPLICATION_ID,
            'fromState': 'Started',
            'toState': 'StaffReview',
            'action': 'SUBMIT',
            'actorSub': 'applicant-sub',
            'requestId': 'req-1',
            'enteredTime': '2026-01-02T00:00:00+00:00',
            'executionArn': 'arn:aws:states:us-east-1:1:execution:app',
        }
        dumped, loaded, _again = _round_trip(transition_schema, transition)
        self.assertEqual('TRANSITION#2026-01-02T00:00:00+00:00#StaffReview', dumped['sk'])
        self.assertEqual('StaffReview', loaded['toState'])
        self.assertNotIn('pk', loaded)

        request_schema = ApplicationRequestRecordSchema()
        _empty_request_dump, empty_request, _empty_request_again = _round_trip(request_schema, {})
        self.assertEqual('applicationRequest', empty_request['type'])
        request = {
            'compact': COMPACT,
            'applicationId': APPLICATION_ID,
            'requestId': 'req-1',
            'action': 'ADMIN_OVERRIDE',
            'actorSub': 'admin-sub',
            'result': {'status': 'deactivated'},
            'createdAt': '2026-01-02T00:00:00+00:00',
            'ttl': 1700000000,
        }
        dumped, loaded, _again = _round_trip(request_schema, request)
        self.assertEqual('REQUEST#req-1', dumped['sk'])
        self.assertEqual({'status': 'deactivated'}, loaded['result'])
        self.assertEqual('admin-sub', loaded['actorSub'])
        self.assertEqual(1700000000, loaded['ttl'])

    def test_corrected_field_names(self):
        self.assertIn('mailingZip', PersonalInformationSchema().fields)
        self.assertNotIn('mainingZip', PersonalInformationSchema().fields)
        self.assertIn('militaryDocuments', HomeStateApplicationTypeSchema().fields)
        self.assertNotIn('militarydocuments', HomeStateApplicationTypeSchema().fields)
        self.assertIn('licenses', LicenseHistorySchema().fields)
        self.assertIn('s3Key', StoredDocumentSchema().fields)
        self.assertNotIn('downloadUri', StoredDocumentSchema().fields)
        self.assertIn('downloadUri', ResponseDocumentSchema().fields)
        self.assertNotIn('s3Key', ResponseDocumentSchema().fields)
        self.assertIn('reviewCompletionDate', ApplicationReviewSchema().fields)
        self.assertIn('reviewerSelectedApplicationSectionStatus', ApplicationSectionReviewSchema().fields)

    def test_unknown_request_field_is_rejected_and_section_patch_strips_text(self):
        with self.assertRaises(ValidationError):
            TransitionRequestSchema().load({'action': 'SUBMIT', 'extra': True})
        loaded = TransitionRequestSchema().load({'action': ' SUBMIT ', 'requestId': '  req-1  '})
        self.assertEqual({'action': 'SUBMIT', 'requestId': 'req-1'}, loaded)
        with self.assertRaises(ValidationError):
            TransitionRequestSchema().load({'requestId': 'req-1'})
        with self.assertRaises(ValidationError):
            TransitionRequestSchema().load({'action': 'SUBMIT', 'requestId': None})
        status = SetApplicationStatusRequestSchema().load(
            {'targetState': 'Started', 'requestId': 'req-1', 'reason': None}
        )
        self.assertEqual({'targetState': 'Started', 'requestId': 'req-1', 'reason': None}, status)
        with self.assertRaises(ValidationError):
            SetApplicationStatusRequestSchema().load({'targetState': None, 'requestId': 'req-1'})
        with self.assertRaises(ValidationError):
            SetApplicationStatusRequestSchema().load({'reason': 'because'})
        assigned = AssignReviewersRequestSchema().load({'firstReviewerSub': 'sub-1'})
        self.assertEqual({'firstReviewerSub': 'sub-1'}, assigned)
        patched = section_patch_schema('personalInformation').load({'firstName': '  Ada  ', 'mainingZip': 'nope'})
        self.assertEqual({'firstName': 'Ada'}, patched)


class TestResponseAndCalculatedStatus(TestCase):
    def test_response_omits_workflow_internals_and_storage_keys(self):
        response = assemble_application_response(
            {
                **FULL_APPLICATION,
                'status': 'awaiting-applicant',
                'isRenewal': True,
            },
            [
                {
                    'sectionName': 'personalInformation',
                    'data': {'firstName': 'Ada', 'mailingZip': '12345', 's3Key': 'should-not-leak'},
                    'reviews': [
                        {
                            'assignmentId': 'assign-1',
                            'reviewerType': 'first-reviewer',
                            'reviewerSelectedApplicationSectionStatus': 'rejected',
                        },
                        {
                            'assignmentId': 'old-assignment',
                            'reviewerType': 'first-reviewer',
                            'reviewerSelectedApplicationSectionStatus': 'approved',
                        },
                    ],
                },
                {
                    'sectionName': 'education',
                    'data': SECTION_PAYLOADS['education'],
                    'reviews': [],
                },
            ],
        )
        hidden = {
            'taskToken',
            'taskTokenHash',
            'executionArn',
            'pendingAction',
            'reopenLock',
            'stateName',
            'scheduleName',
            'version',
            'generation',
            'workflowExpiresAt',
            'pk',
            'sk',
        }
        self.assertTrue(hidden.isdisjoint(response))
        self.assertEqual(APPLICATION_ID, response['id'])
        self.assertEqual('awaiting-applicant', response['status'])
        self.assertEqual('needs-attention', response['personalInformation']['calculatedSectionStatusForApplicant'])
        self.assertIsNone(response['personalInformation']['calculatedSectionStatusForReviewComparison'])
        self.assertEqual('12345', response['personalInformation']['mailingZip'])
        self.assertNotIn('s3Key', response['personalInformation'])
        transcript = response['education']['transcripts'][0]
        self.assertEqual('https://secret', transcript['downloadUri'])
        self.assertNotIn('s3Key', transcript)
        self.assertIn('licenseHistory', response)
        self.assertEqual('incomplete', response['licenseHistory']['calculatedSectionStatusForApplicant'])
        loaded = ApplicationResponseSchema().load({**response, 'taskToken': 'secret', 'executionArn': 'arn'})
        self.assertNotIn('taskToken', loaded)
        self.assertNotIn('executionArn', loaded)

    def test_calculated_statuses(self):
        rejected = {'reviewerSelectedApplicationSectionStatus': 'rejected'}
        approved = {'reviewerSelectedApplicationSectionStatus': 'approved'}
        pending = {'reviewerSelectedApplicationSectionStatus': 'pending'}

        self.assertEqual('incomplete', calculate_applicant_status(None, 'started', [], False))
        self.assertEqual('incomplete', calculate_applicant_status({}, 'started', [], None))
        self.assertEqual('incomplete', calculate_applicant_status({'firstName': '   '}, 'started', [], False))
        self.assertEqual('incomplete', calculate_applicant_status({'languages': []}, 'started', [], True))
        self.assertEqual('complete', calculate_applicant_status({'firstName': 'Ada'}, 'started', [], False))
        self.assertEqual('complete', calculate_applicant_status({'isCompleted': False}, 'first-review', [], True))
        self.assertEqual(
            'needs-attention',
            calculate_applicant_status({'firstName': 'Ada'}, 'awaiting-applicant', [rejected], False),
        )
        self.assertEqual(
            'complete',
            calculate_applicant_status({'firstName': 'Ada'}, 'first-review', [rejected], False),
        )
        self.assertEqual('incomplete', calculate_applicant_status({}, 'awaiting-applicant', [approved], True))
        self.assertNotEqual('confirm-details', calculate_applicant_status({}, 'started', [], True))

        self.assertEqual('both-approve', calculate_review_comparison(approved, approved))
        self.assertEqual('reviewers-differ', calculate_review_comparison(approved, rejected))
        self.assertEqual('reviewers-differ', calculate_review_comparison(rejected, approved))
        self.assertIsNone(calculate_review_comparison(rejected, rejected))
        self.assertIsNone(calculate_review_comparison(approved, pending))
        self.assertIsNone(calculate_review_comparison(approved, None))
        self.assertIsNone(calculate_review_comparison(None, None))
