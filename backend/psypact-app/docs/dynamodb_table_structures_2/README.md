# DynamoDB Table Structures

This package documents the structure of 37 DynamoDB tables. Each table's schema was derived from its live key definition plus a sample of up to 50 items per table — **no actual record values are included anywhere in this package**, only field names and inferred data types.

## What's included

- **One JSON file per table** (e.g. `Examination.json`) — structure for that table only.
- **`all_tables.json`** — every table's structure combined into a single document, useful for programmatic loading, diffing, or validation.
- **`_index.json`** — a flat manifest listing every table, its file name, partition/sort key, and attribute count.
- **This README** — naming conventions and general notes.

## File format

Each per-table file looks like:

```json
{
  "tableName": "Examination",
  "description": "...",
  "partitionKey": "userId",
  "sortKey": null,
  "attributes": {
    "userId": "Number",
    "examList": "String"
  },
  "sampleItemShape": {
    "userId": 12345,
    "examList": "example-string"
  },
  "sampleItemDynamoDBFormat": {
    "userId": { "N": "12345" },
    "examList": { "S": "example-string" }
  },
  "notes": "..."
}
```

- **`partitionKey`** / **`sortKey`** — the DynamoDB key schema. `sortKey` is `null` for tables with a simple (partition-key-only) primary key.
- **`attributes`** — every field name observed across the sampled items, with its DynamoDB type (`String`, `Number`, `Boolean`, `Binary`, `Map`, `List`, `StringSet`, `NumberSet`, `Null`).
- **`sampleItemShape`** — a plain-JSON placeholder item using generic example values, showing the shape without any real data.
- **`sampleItemDynamoDBFormat`** — the same placeholder item in DynamoDB's native wire format (`{"S": "..."}`, `{"N": "..."}`, etc.) — the exact shape returned by DynamoDB's API (`GetItem`/`Query`/`Scan`), useful if the receiving org is writing code that parses DynamoDB responses directly.

⚠️ **DynamoDB is schemaless outside of key attributes.** The `attributes` list reflects what was observed in a sample of up to 50 items and may not capture every field that exists across the full table — some records may have additional or missing optional fields.

## Naming conventions across tables

- **`userId` (Number)** is the near-universal partition key — nearly every table is keyed by the individual it belongs to.
- **`entryId` (Number)** or **`activityId` (Number)** commonly serve as the sort key on tables that hold multiple records per user (e.g. `Courses`, `Education`, `Licensures`, `Internship`).
- A handful of tables use a different partition key tied to their own entity rather than the user:
  - `Attestation` → `attestationId`
  - `Attester` → `attesterEmail`
  - `DisciplinaryEntry` → `disciplinaryEntryId`
- **`_v2` suffix** — several tables (`Acknowledgements.*_v2`, `Renewal*_v2`) are newer versions of an existing table, generally distinguished by adding an `activityId` sort key where the original had only `userId`.
- **`AttestationType` / `attestationDate` / `legalAgree` / `validated`** — recurring fields across many acknowledgement/attestation-style tables, indicating a shared attestation pattern.
- **`UpdatedAt`** — a common last-modified timestamp field (stored as a String, not a native DynamoDB timestamp type).
- Some tables were empty in both UAT and Prod at sampling time (`Acknowledgements`, `HomeStateDeclaration`, `Questionnaire`), so their structure could only be inferred from the key schema, not sampled fields — these may be deprecated or superseded by their `_v2` counterparts.

## Suggested ways to consume this package

- **Reviewing individually or splitting across teams** → use the per-table `.json` files.
- **Loading into a script, validator, or schema-diff tool** → use `all_tables.json`.
- **Writing code that parses live DynamoDB responses** → use each table's `sampleItemDynamoDBFormat` as a parsing reference.
- **Getting oriented quickly** → start with `_index.json` and this README.
