"""
Handles ModelTask.VALIDATE_DETERMINISTIC — the non-AI half of hybrid
validation. Every check here is objective and never calls a model:
MIME/size, dates, required fields, client-profile matching.

New document types mean new rule functions added to RULES below, never
a new processor and never a new AI system — that's the point of keeping
this generic per the architecture requirement.
"""

import logging
import re
from collections.abc import Callable
from datetime import date as date_cls, datetime
from typing import Any

from app.core.config import settings
from app.models.enums import ValidationCheckStatus
from app.services.ai_brain.context import ProcessingContext, ProcessorResult
from app.services.ai_brain.processors.base import AIProcessor
from app.services.ai_brain.tasks import ModelTask

logger = logging.getLogger(__name__)

CheckResult = dict[str, Any]
# A rule reads whatever it needs from context.extra and returns a check
# result, or None if it doesn't apply (e.g. no date_range in this
# requirement, so check_date_within_range has nothing to check).
RuleFunc = Callable[[ProcessingContext], CheckResult | None]


def _check(
    name: str,
    status: ValidationCheckStatus,
    expected: Any = None,
    actual: Any = None,
    detail: str | None = None,
) -> CheckResult:
    return {
        "check_name": name,
        "expected_value": str(expected) if expected is not None else None,
        "actual_value": str(actual) if actual is not None else None,
        "status": status.value,
        "detail": detail,
    }


def check_mime_type_allowed(context: ProcessingContext) -> CheckResult | None:
    if context.mime_type is None:
        return None
    allowed = context.mime_type in settings.ALLOWED_MIME_TYPES
    return _check(
        "mime_type_allowed",
        ValidationCheckStatus.PASS if allowed else ValidationCheckStatus.FAIL,
        expected=settings.ALLOWED_MIME_TYPES,
        actual=context.mime_type,
    )


def check_file_size_within_limit(context: ProcessingContext) -> CheckResult | None:
    size_bytes = context.extra.get("file_size_bytes")
    if size_bytes is None:
        return None
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    ok = size_bytes <= max_bytes
    return _check(
        "file_size_within_limit",
        ValidationCheckStatus.PASS if ok else ValidationCheckStatus.FAIL,
        expected=f"<= {settings.MAX_UPLOAD_SIZE_MB}MB",
        actual=f"{size_bytes / (1024 * 1024):.2f}MB",
    )


def check_required_fields_present(context: ProcessingContext) -> CheckResult | None:
    spec = context.extra.get("normalized_spec")
    fields = context.extra.get("extracted_fields")
    if not spec or fields is None:
        return None
    required = spec.get("required_fields") or []
    missing = [f for f in required if not fields.get(f)]
    if not missing:
        return _check(
            "required_fields_present",
            ValidationCheckStatus.PASS,
            expected=required,
            actual=list(fields.keys()),
        )
    return _check(
        "required_fields_present",
        ValidationCheckStatus.FAIL,
        expected=required,
        actual=missing,
        detail=f"Missing: {', '.join(missing)}",
    )


def _parse_date_value(value: Any) -> date_cls | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None

        # Common bank statement patterns: "2025-04-01", "01-Apr-2025",
        # "01 Apr 2025", "2025/04/01", and ranged strings like
        # "01-Apr-2025 to 31-Mar-2026".
        if " to " in text.lower() or " - " in text:
            parts = re.split(r"\s+to\s+|\s+-\s+", text, maxsplit=1, flags=re.IGNORECASE)
            if len(parts) == 2:
                start = _parse_date_value(parts[0])
                end = _parse_date_value(parts[1])
                if start is not None and end is not None:
                    return start
                return start or end

        for fmt in (
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%d-%b-%Y",
            "%d-%B-%Y",
            "%d %b %Y",
            "%d %B %Y",
            "%d-%m-%Y",
            "%m/%d/%Y",
            "%m-%d-%Y",
        ):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue

    return None


def _extract_document_date_bounds(fields: dict[str, Any]) -> tuple[date_cls | None, date_cls | None]:
    # Accept every date-like field name that Gemini or OCR commonly emits for
    # bank statements.
    candidates = [
        fields.get("document_date"),
        fields.get("statement_date"),
        fields.get("statement_start_date"),
        fields.get("statement_end_date"),
        fields.get("start_date"),
        fields.get("end_date"),
        fields.get("statement_period"),
    ]

    start = None
    end = None

    for candidate in candidates:
        if candidate is None:
            continue
        if isinstance(candidate, str) and " to " in candidate.lower():
            parts = re.split(r"\s+to\s+|\s+-\s+", candidate, maxsplit=1, flags=re.IGNORECASE)
            if len(parts) == 2:
                start = _parse_date_value(parts[0]) or start
                end = _parse_date_value(parts[1]) or end
                continue
        parsed = _parse_date_value(candidate)
        if parsed is not None:
            if start is None:
                start = parsed
            elif end is None:
                end = parsed

    if start is not None and end is None:
        end = start
    if end is not None and start is None:
        start = end

    return start, end


def check_date_within_range(context: ProcessingContext) -> CheckResult | None:
    spec = context.extra.get("normalized_spec")
    fields = context.extra.get("extracted_fields")
    if not spec or fields is None:
        return None
    date_range = spec.get("date_range")
    if not date_range:
        return None

    start_date, end_date = _extract_document_date_bounds(fields)
    if start_date is None and end_date is None:
        return _check(
            "date_within_range",
            ValidationCheckStatus.UNCERTAIN,
            expected=date_range,
            detail="No recognizable statement date/range field found in extracted data",
        )

    start = _parse_date_value(date_range.get("start"))
    end = _parse_date_value(date_range.get("end"))

    if start_date is None:
        start_date = end_date
    if end_date is None:
        end_date = start_date

    if start_date is not None and end_date is not None:
        in_range = (start is None or start_date >= start) and (end is None or end_date <= end)
        return _check(
            "date_within_range",
            ValidationCheckStatus.PASS if in_range else ValidationCheckStatus.FAIL,
            expected=date_range,
            actual={
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
        )

    return _check(
        "date_within_range",
        ValidationCheckStatus.UNCERTAIN,
        expected=date_range,
        actual={
            "start": start_date.isoformat() if start_date else None,
            "end": end_date.isoformat() if end_date else None,
        },
        detail="Unable to fully resolve statement date bounds",
    )


def check_client_profile_match(context: ProcessingContext) -> CheckResult | None:
    client_profile = context.extra.get("client_profile")
    fields = context.extra.get("extracted_fields")
    if not client_profile or fields is None:
        return None
    client_pan = client_profile.get("pan")
    doc_pan = fields.get("pan_number") or fields.get("pan")
    if not client_pan or not doc_pan:
        return None
    match = client_pan.strip().upper() == doc_pan.strip().upper()
    return _check(
        "client_profile_match",
        ValidationCheckStatus.PASS if match else ValidationCheckStatus.FAIL,
        expected=client_pan,
        actual=doc_pan,
    )


RULES: list[RuleFunc] = [
    check_mime_type_allowed,
    check_file_size_within_limit,
    check_required_fields_present,
    check_date_within_range,
    check_client_profile_match,
]


class DeterministicRuleProcessor(AIProcessor):
    task = ModelTask.VALIDATE_DETERMINISTIC

    async def run(self, context: ProcessingContext) -> ProcessorResult:
        checks: list[CheckResult] = []
        for rule in RULES:
            try:
                result = rule(context)
            except Exception as exc:  # noqa: BLE001 — one bad rule shouldn't
                # kill the whole validation pass; surface it as UNCERTAIN
                # on that specific check instead.
                logger.exception("Rule %s raised", rule.__name__)
                result = _check(rule.__name__, ValidationCheckStatus.UNCERTAIN, detail=str(exc))
            if result is not None:
                checks.append(result)

        if any(c["status"] == ValidationCheckStatus.FAIL.value for c in checks):
            overall = ValidationCheckStatus.FAIL
        elif any(c["status"] == ValidationCheckStatus.UNCERTAIN.value for c in checks):
            overall = ValidationCheckStatus.UNCERTAIN
        else:
            overall = ValidationCheckStatus.PASS

        return ProcessorResult(
            success=True,
            task=self.task,
            model_name="deterministic_rule_engine",
            output={"checks": checks, "overall_status": overall.value},
            confidence=1.0,  # deterministic — not a model confidence score
        )