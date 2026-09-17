from app.services.storage.cloudinary_service import (
    CloudinaryStorageService,
    StorageStage,
)


def test_temp_to_permanent_transition_is_allowed():
    """Check that TEMP can move to PERMANENT."""

    service = CloudinaryStorageService()

    allowed_stages = service._ALLOWED_TRANSITIONS[StorageStage.TEMP]

    assert StorageStage.PERMANENT in allowed_stages


def test_temp_to_quarantine_transition_is_allowed():
    """Check that TEMP can move to QUARANTINE."""

    service = CloudinaryStorageService()

    allowed_stages = service._ALLOWED_TRANSITIONS[StorageStage.TEMP]

    assert StorageStage.QUARANTINE in allowed_stages


def test_temp_to_review_transition_is_allowed():
    """Check that TEMP can move to REVIEW."""

    service = CloudinaryStorageService()

    allowed_stages = service._ALLOWED_TRANSITIONS[StorageStage.TEMP]

    assert StorageStage.REVIEW in allowed_stages


def test_permanent_cannot_move_to_temp():
    """Check that PERMANENT cannot move back to TEMP."""

    service = CloudinaryStorageService()

    allowed_stages = service._ALLOWED_TRANSITIONS[StorageStage.PERMANENT]

    assert StorageStage.TEMP not in allowed_stages


def test_permanent_cannot_move_to_review():
    """Check that PERMANENT cannot move to REVIEW."""

    service = CloudinaryStorageService()

    allowed_stages = service._ALLOWED_TRANSITIONS[StorageStage.PERMANENT]

    assert StorageStage.REVIEW not in allowed_stages


def test_review_cannot_move_to_permanent():
    """Check that REVIEW cannot move to PERMANENT."""

    service = CloudinaryStorageService()

    allowed_stages = service._ALLOWED_TRANSITIONS[StorageStage.REVIEW]

    assert StorageStage.PERMANENT not in allowed_stages


def test_quarantine_cannot_move_to_review():
    """Check that QUARANTINE cannot move to REVIEW."""

    service = CloudinaryStorageService()

    allowed_stages = service._ALLOWED_TRANSITIONS[StorageStage.QUARANTINE]

    assert StorageStage.REVIEW not in allowed_stages