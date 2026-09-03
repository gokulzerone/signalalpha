"""Evidence architecture (PRD §8): record creation, span validation, claim validation, viewer."""

from evidence.claims import Claim, ClaimValidationError, validate_claims
from evidence.records import SpanError, create_evidence, create_evidence_from_quote, locate_span
from evidence.viewer import DocumentNotFoundError, DocumentView, Highlight, document_view

__all__ = [
    "Claim",
    "ClaimValidationError",
    "DocumentNotFoundError",
    "DocumentView",
    "Highlight",
    "SpanError",
    "create_evidence",
    "create_evidence_from_quote",
    "document_view",
    "locate_span",
    "validate_claims",
]
