from dataclasses import FrozenInstanceError

import pytest

from app.services.storage.schemas import (
    DeleteResult,
    MoveResult,
    StorageStage,
    UploadResult,
)


def test_storage_stage_values():
    """Check that all storage stages have the correct values."""

    assert StorageStage.TEMP.value == "temp"
    assert StorageStage.PERMANENT.value == "permanent"
    assert StorageStage.QUARANTINE.value == "quarantine"
    assert StorageStage.REVIEW.value == "review"


def test_upload_result():
    """Check that UploadResult stores upload information correctly."""

    result = UploadResult(
        public_id="caba/temp/test-document",
        resource_type="raw",
        format="pdf",
        bytes=1024,
        source_url="https://example.com/test-document.pdf",
        stage=StorageStage.TEMP,
    )

    assert result.public_id == "caba/temp/test-document"
    assert result.resource_type == "raw"
    assert result.format == "pdf"
    assert result.bytes == 1024
    assert result.source_url == "https://example.com/test-document.pdf"
    assert result.stage == StorageStage.TEMP


def test_move_result():
    """Check that MoveResult stores move information correctly."""

    result = MoveResult(
        old_public_id="caba/temp/test-document",
        public_id="caba/permanent/test-document",
        resource_type="raw",
        stage=StorageStage.PERMANENT,
    )

    assert result.old_public_id == "caba/temp/test-document"
    assert result.public_id == "caba/permanent/test-document"
    assert result.resource_type == "raw"
    assert result.stage == StorageStage.PERMANENT


def test_delete_result():
    """Check that DeleteResult stores delete information correctly."""

    result = DeleteResult(
        public_id="caba/temp/test-document",
        resource_type="raw",
        deleted=True,
    )

    assert result.public_id == "caba/temp/test-document"
    assert result.resource_type == "raw"
    assert result.deleted is True


def test_upload_result_is_immutable():
    """Check that UploadResult cannot be changed after creation."""

    result = UploadResult(
        public_id="caba/temp/test-document",
        resource_type="raw",
        format="pdf",
        bytes=1024,
        source_url=None,
        stage=StorageStage.TEMP,
    )

    with pytest.raises(FrozenInstanceError):
        result.public_id = "caba/permanent/test-document"


def test_move_result_is_immutable():
    """Check that MoveResult cannot be changed after creation."""

    result = MoveResult(
        old_public_id="caba/temp/test-document",
        public_id="caba/permanent/test-document",
        resource_type="raw",
        stage=StorageStage.PERMANENT,
    )

    with pytest.raises(FrozenInstanceError):
        result.stage = StorageStage.REVIEW


def test_delete_result_is_immutable():
    """Check that DeleteResult cannot be changed after creation."""

    result = DeleteResult(
        public_id="caba/temp/test-document",
        resource_type="raw",
        deleted=True,
    )

    with pytest.raises(FrozenInstanceError):
        result.deleted = False