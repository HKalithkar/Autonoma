from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


def validate_input_schema(schema: dict[str, Any]) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Invalid input_schema", "message": str(exc)},
        ) from exc


def validate_workflow_params(schema: dict[str, Any], params: dict[str, Any]) -> None:
    required_fields, optional_fields = extract_schema_fields(schema)
    if required_fields:
        missing_required = [field for field in required_fields if field not in params]
        if missing_required:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "Missing required params",
                    "missing_required": missing_required,
                    "required_fields": required_fields,
                    "optional_fields": optional_fields,
                },
            )
    validator = Draft202012Validator(schema)
    errors = []
    for error in validator.iter_errors(params):
        path = "/".join(str(item) for item in error.path)
        errors.append(
            {
                "path": f"/{path}" if path else "/",
                "message": error.message,
            }
        )
    if errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "Invalid params",
                "violations": errors,
                "required_fields": required_fields,
                "optional_fields": optional_fields,
            },
        )


def ensure_params_object(raw_params: Any) -> dict[str, Any]:
    if raw_params is None:
        return {}
    if not isinstance(raw_params, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="params must be an object",
        )
    return dict(raw_params)


def extract_schema_fields(schema: dict[str, Any]) -> tuple[list[str], list[str]]:
    if not isinstance(schema, dict):
        return [], []
    required_raw = schema.get("required", [])
    required = required_raw if isinstance(required_raw, list) else []
    required_fields = [str(item) for item in required if str(item).strip()]
    properties_raw = schema.get("properties", {})
    properties = properties_raw if isinstance(properties_raw, dict) else {}
    optional_fields = [
        str(name)
        for name in properties.keys()
        if str(name).strip() and str(name) not in required_fields
    ]
    return required_fields, optional_fields
