"""
The fixed set of tasks the AI Brain can route. Adding a new document type
should never require adding a new task here — only a new schema/rule.
New tasks are only added for genuinely new *kinds of work* (a new modality,
a new reasoning step), not new document types.
"""

import enum


class ModelTask(str, enum.Enum):
    CLASSIFY_DOCUMENT = "classify_document"

    # Extraction — modality-specific on purpose. The router doesn't guess
    # which one to use; resolve_extraction_task() below decides based on
    # signals the caller already has (does a text layer exist, etc.).
    EXTRACT_TEXT_NATIVE = "extract_text_native"      # Tesseract / PyMuPDF / python-docx
    EXTRACT_VISUAL = "extract_visual"                # Qwen vision model

    UNDERSTAND_REQUIREMENT = "understand_requirement"  # GPT-OSS 120B
    VALIDATE_SEMANTIC = "validate_semantic"             # GPT-OSS 120B — ambiguous/judgment checks
    GENERATE_EXPLANATION = "generate_explanation"       # GPT-OSS 120B — client/CA-facing text

    VALIDATE_DETERMINISTIC = "validate_deterministic"   # Python/Pydantic rules — no model


def resolve_extraction_task(
    *, has_native_text_layer: bool, is_scanned_or_image: bool
) -> ModelTask:
    """
    Decide EXTRACT_TEXT_NATIVE vs EXTRACT_VISUAL from signals the caller
    already has after a first-pass file inspection (e.g. PyMuPDF reports
    whether a PDF page has a text layer). Kept as an explicit function
    rather than inline in the router so the decision rule is one place
    and easy to extend later (e.g. a third signal for low-DPI scans).
    """
    if is_scanned_or_image or not has_native_text_layer:
        return ModelTask.EXTRACT_VISUAL
    return ModelTask.EXTRACT_TEXT_NATIVE