"""Shared fixtures for the CIPHOS LPG semantic-map unit tests."""

from __future__ import annotations

from typing import Any

SOURCE_URI = "neo4j+s://reader:secret@ops.example.com/"
SOURCE_DATABASE = "neo4j"
STORE_URI = "neo4j+s://semantic.example.com"
STORE_DATABASE = "neo4j"

SCHEMA_METADATA: dict[str, list[dict[str, Any]]] = {
    "labels": [
        {"label": "Archived"},
        {"label": "CiphosEntity"},
        {"label": "Document"},
        {"label": "Tag"},
        {"label": "Unconnected"},
        {"label": "Vulnerability"},
    ],
    "relationship_types": [
        {"relationshipType": "HAS_VULNERABILITY"},
        {"relationshipType": "REFERENCED_IN"},
    ],
    "node_properties": [
        {
            "nodeType": ":`Archived`:`Tag`",
            "nodeLabels": ["Archived", "Tag"],
            "propertyName": "tagNumber",
            "propertyTypes": ["STRING"],
            "mandatory": False,
        },
        {
            "nodeType": ":`CiphosEntity`",
            "nodeLabels": ["CiphosEntity"],
            "propertyName": "entityKey",
            "propertyTypes": ["STRING"],
            "mandatory": True,
        },
        {
            "nodeType": ":`CiphosEntity`:`Document`",
            "nodeLabels": ["CiphosEntity", "Document"],
            "propertyName": "documentNumber",
            "propertyTypes": ["STRING"],
            "mandatory": True,
        },
        {
            "nodeType": ":`CiphosEntity`:`Tag`",
            "nodeLabels": ["CiphosEntity", "Tag"],
            "propertyName": "tagNumber",
            "propertyTypes": ["STRING"],
            "mandatory": True,
        },
        {
            "nodeType": ":`CiphosEntity`:`Vulnerability`",
            "nodeLabels": ["CiphosEntity", "Vulnerability"],
            "propertyName": "cveId",
            "propertyTypes": ["STRING", "NULL"],
            "mandatory": False,
        },
        {
            "nodeType": "",
            "nodeLabels": [],
            "propertyName": "unlabeledProperty",
            "propertyTypes": ["INTEGER"],
            "mandatory": False,
        },
    ],
    "relationship_properties": [
        {
            "relType": ":`HAS_VULNERABILITY`",
            "propertyName": "confidence",
            "propertyTypes": ["FLOAT", "INTEGER"],
            "mandatory": False,
        }
    ],
    "constraints": [
        {
            "entityType": "NODE",
            "labelsOrTypes": ["Tag"],
            "properties": ["tagNumber"],
            "type": "UNIQUENESS",
        },
        {
            "entityType": "NODE",
            "labelsOrTypes": ["Document"],
            "properties": ["documentNumber"],
            "type": "NODE_PROPERTY_EXISTENCE",
        },
        {
            "entityType": "RELATIONSHIP",
            "labelsOrTypes": ["HAS_VULNERABILITY"],
            "properties": ["confidence"],
            "type": "RELATIONSHIP_PROPERTY_EXISTENCE",
        },
    ],
    "indexes": [
        {
            "entityType": "NODE",
            "labelsOrTypes": ["Tag"],
            "properties": ["tagNumber"],
            "type": "RANGE",
        },
        {
            "entityType": "RELATIONSHIP",
            "labelsOrTypes": ["HAS_VULNERABILITY"],
            "properties": ["confidence"],
            "type": "RANGE",
        },
    ],
}

ENDPOINTS = [
    {
        "relationship_type": "HAS_VULNERABILITY",
        "source_label": "Tag",
        "target_label": "Vulnerability",
    },
    {
        "relationship_type": "REFERENCED_IN",
        "source_label": "Tag",
        "target_label": "Document",
    },
]
