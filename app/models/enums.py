import enum


class UserRole(str, enum.Enum):
    CA = "ca"
    SUB_CA = "sub_ca"
    ADMIN = "admin"


class RequestStatus(str, enum.Enum):
    DRAFT = "draft"
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class RequirementStatus(str, enum.Enum):
    PENDING_INTERPRETATION = "pending_interpretation"
    INTERPRETED = "interpreted"
    FAILED = "failed"


class UploadStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    VALID = "valid"
    INVALID = "invalid"
    NEEDS_REVIEW = "needs_review"
    EXPIRED = "expired"


class ProcessingStage(str, enum.Enum):
    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"
    REQUIREMENT_UNDERSTANDING = "requirement_understanding"


class ValidationCheckStatus(str, enum.Enum):
    PASS = "pass"
    FAIL = "fail"
    UNCERTAIN = "uncertain"


class ReviewDecision(str, enum.Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    REQUEST_REUPLOAD = "request_reupload"