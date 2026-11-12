"""Turn a marshmallow schema into a JSON Schema object.

API Gateway models are built from this dict. Field lists stay on the marshmallow
classes. ``Meta.exclude`` is honored because the walker reads the resolved fields.
"""

from marshmallow import Schema
from marshmallow.fields import Boolean, Dict, Float, Integer, List, Nested, Raw, String
from marshmallow.validate import Length, OneOf

_SECTION_RESPONSE_DESCRIPTION = (
    'Response for one {section}. Properties from every section are included because this path '
    'uses one model. The application response lists each section separately. The handler validates '
    'a PATCH body with the stored section schema for the path section.'
)


def marshmallow_json_schema(schema_cls: type[Schema]) -> dict:
    """Return a JSON Schema object for one marshmallow schema."""
    schema = schema_cls()
    properties = {}
    required = []
    for name, field in schema.fields.items():
        properties[name] = _field_schema(field)
        if field.required and not field.allow_none:
            required.append(name)
    document = {
        'type': 'object',
        'additionalProperties': False,
        'properties': properties,
    }
    if required:
        document['required'] = required
    return document


def merged_section_response_schema(*schema_classes: type[Schema]) -> dict:
    """One object schema for the shared ``{section}`` response."""
    properties = {}
    for schema_cls in schema_classes:
        properties.update(marshmallow_json_schema(schema_cls)['properties'])
    return {
        'type': 'object',
        'additionalProperties': False,
        'description': _SECTION_RESPONSE_DESCRIPTION,
        'properties': properties,
    }


def _field_schema(field) -> dict:
    if isinstance(field, Nested):
        nested = field.nested
        schema_cls = nested if isinstance(nested, type) else type(field.schema)
        return marshmallow_json_schema(schema_cls)
    if isinstance(field, List):
        document = {'type': 'array', 'items': _field_schema(field.inner)}
        minimum = _length_minimum(field)
        if minimum is not None:
            document['minItems'] = minimum
        _copy_description(field, document)
        return document
    if isinstance(field, Boolean):
        document = {'type': 'boolean'}
    elif isinstance(field, Integer):
        document = {'type': 'integer'}
    elif isinstance(field, Float):
        document = {'type': 'number'}
    elif isinstance(field, (Dict, Raw)):
        document = {'type': 'object'}
    elif isinstance(field, String):
        document = {'type': 'string'}
        choices = _one_of_choices(field)
        if choices:
            document['enum'] = choices
    else:
        document = {'type': 'string'}
    _copy_description(field, document)
    return document


def _one_of_choices(field) -> list | None:
    for validator in field.validators:
        if isinstance(validator, OneOf):
            return [str(choice) for choice in validator.choices]
    return None


def _length_minimum(field) -> int | None:
    for validator in field.validators:
        if isinstance(validator, Length) and validator.min is not None:
            return validator.min
    return None


def _copy_description(field, document: dict) -> None:
    description = field.metadata.get('description')
    if description:
        document['description'] = description
