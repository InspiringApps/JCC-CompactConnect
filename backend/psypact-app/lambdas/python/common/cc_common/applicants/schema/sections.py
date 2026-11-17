# ruff: noqa: N801, N815  invalid-name
"""Stored section documents as they are written on a SECTION item.

These schemas describe the DynamoDB ``data`` map. A presigned download URL is not
stored. The TypeScript names ``mainingZip`` and ``militarydocuments`` are
``mailingZip`` and ``militaryDocuments``. ``licenses`` is a list.
"""

from common_lambdas.data_model.schema.base_record import ForgivingSchema
from common_lambdas.data_model.schema.common import CCRequestSchema
from marshmallow import EXCLUDE
from marshmallow.fields import Boolean, Integer, List, Nested, String
from marshmallow.validate import OneOf

from cc_common.applicants.application_state import ApplicationLicenseStatus, ApplicationType, SectionName


class ApplicationValueSchema(CCRequestSchema, ForgivingSchema):
    """Optional application value. Unknown keys are dropped and strings are trimmed."""

    class Meta:
        unknown = EXCLUDE


def _str(**kwargs) -> String:
    kwargs.setdefault('required', False)
    kwargs.setdefault('allow_none', True)
    return String(**kwargs)


def _bool() -> Boolean:
    return Boolean(required=False, allow_none=True)


def _strings() -> List:
    return List(String(required=False, allow_none=True), required=False, allow_none=True)


class StoredDocumentSchema(ApplicationValueSchema):
    """File metadata kept on the section item. The download URL is not stored."""

    filename = _str()
    sizeBytes = Integer(required=False, allow_none=True)
    s3Key = _str()


class PersonalInformationSchema(ApplicationValueSchema):
    firstName = _str()
    middleName = _str()
    lastName = _str()
    suffix = _str()
    phone = _str()
    altPhone = _str()
    dob = _str()
    ssnLastFour = _str()
    npi = _str()
    gender = _str()
    professionalName = _str()
    citizenship = _str()
    placeOfBirth = _str()
    languages = _strings()
    mailingAddress1 = _str()
    mailingAddress2 = _str()
    mailingCity = _str()
    mailingState = _str()
    mailingZip = _str()


class MobilityCredentialSchema(ApplicationValueSchema):
    mobilityNumber = _str()
    issueDate = _str()


class LicenseHistoryEntrySchema(ApplicationValueSchema):
    state = _str()
    issueDate = _str()
    licenseNumber = _str()
    status = _str(validate=OneOf([status.value for status in ApplicationLicenseStatus]))


class LicenseHistorySchema(ApplicationValueSchema):
    ePassport = Nested(MobilityCredentialSchema, required=False, allow_none=True)
    ipc = Nested(MobilityCredentialSchema, required=False, allow_none=True)
    licenses = List(Nested(LicenseHistoryEntrySchema), required=False, allow_none=True)


class AccreditingContactSchema(ApplicationValueSchema):
    name = _str()
    email = _str()
    city = _str()
    state = _str()
    zip = _str()
    phone = _str()
    attestations = _strings()


class EducationSchema(ApplicationValueSchema):
    nameAtTime = _str()
    institution = _str()
    city = _str()
    state = _str()
    degreeType = _str()
    program = _str()
    department = _str()
    conferredDate = _str()
    isCompleted = _bool()
    accreditingBody = _str()
    accreditingYear = _str()
    isAccreditedByAuthority = _bool()
    isProgramEquivalent = _bool()
    accreditingContact = Nested(AccreditingContactSchema, required=False, allow_none=True)
    hasResidence = _bool()
    transcripts = List(Nested(StoredDocumentSchema), required=False, allow_none=True)


class ConvictionSchema(ApplicationValueSchema):
    charge = _str()
    location = _str()
    date = _str()
    type = _str()


class ConductHistorySchema(ApplicationValueSchema):
    attestations = _strings()
    convictions = List(Nested(ConvictionSchema), required=False, allow_none=True)
    notes = _str()
    documents = List(Nested(StoredDocumentSchema), required=False, allow_none=True)


class HomeStateApplicationTypeSchema(ApplicationValueSchema):
    applicationType = String(
        required=False,
        allow_none=True,
        validate=OneOf([application_type.value for application_type in ApplicationType]),
    )
    state = _str()
    startDate = _str()
    isActiveMilitary = _bool()
    militaryDocuments = List(Nested(StoredDocumentSchema), required=False, allow_none=True)
    attestations = _strings()


class HomeStateSchema(ApplicationValueSchema):
    applicationTypes = List(Nested(HomeStateApplicationTypeSchema), required=False, allow_none=True)


class AcknowledgementsSchema(ApplicationValueSchema):
    attestations = _strings()
    signatureName = _str()


SECTION_DATA_SCHEMAS = {
    SectionName.PERSONAL_INFORMATION.value: PersonalInformationSchema,
    SectionName.LICENSE_HISTORY.value: LicenseHistorySchema,
    SectionName.EDUCATION.value: EducationSchema,
    SectionName.CONDUCT_HISTORY.value: ConductHistorySchema,
    SectionName.HOME_STATE.value: HomeStateSchema,
    SectionName.ACKNOWLEDGEMENTS.value: AcknowledgementsSchema,
}


def section_data_schema(section_name: str) -> ApplicationValueSchema:
    """Return the stored field schema for one section."""
    return SECTION_DATA_SCHEMAS[section_name]()
