from __future__ import annotations
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, BinaryIO
import cloudinary
import cloudinary.uploader
import cloudinary.utils
from cloudinary.exceptions import Error as CloudinaryError
from app.core.config import settings
import app.schemas.document_upload

class StorageConfigurationError(RuntimeError):
    """Raised when required Cloudinary configuration is missing."""

class StorageUploadError(RuntimeError):
    """Raised when a file cannot be uploaded to Cloudinary."""

class StorageUrlGenerationError(RuntimeError):
    """Raised when a signed URL cannot be generated."""

class StorageMoveError(RuntimeError):
    """Raised when a file cannot be moved between Cloudinary stages."""

class InvalidLifecycleTransition(StorageMoveError):
    """Raised when a lifecycle transition is not allowed."""

class StorageDeleteError(RuntimeError):
    """Raised when a file cannot be deleted from Cloudinary."""

@lru_cache
def get_storage_service() -> "CloudinaryStorageService":
    """Create a Cloudinary storage service only when the route actually needs it."""
    return CloudinaryStorageService()


class CloudinaryStorageService:
    """
    Cloudinary-based document storage service.

    The service does not depend on local filesystem paths.

    Files are received as file-like objects, for example:

        UploadFile.file

    Lifecycle:

        TEMP
          ├── PERMANENT
          ├── QUARANTINE
          └── REVIEW
    """

    _DELIVERY_TYPE = "private"

    _ALLOWED_TRANSITIONS: dict[app.schemas.document_upload.StorageStage, set[app.schemas.document_upload.StorageStage]] = {
        app.schemas.document_upload.StorageStage.TEMP: {
            app.schemas.document_upload.StorageStage.PERMANENT,
            app.schemas.document_upload.StorageStage.QUARANTINE,
            app.schemas.document_upload.StorageStage.REVIEW,
        },
        app.schemas.document_upload.StorageStage.PERMANENT: set(),
        app.schemas.document_upload.StorageStage.QUARANTINE: set(),
        app.schemas.document_upload.StorageStage.REVIEW: set(),
    }

    def __init__(self) -> None:
        self._configure_cloudinary()



    @staticmethod
    def _configure_cloudinary() -> None:
        missing = [
            name
            for name, value in {
                "CLOUDINARY_CLOUD_NAME": settings.CLOUDINARY_CLOUD_NAME,
                "CLOUDINARY_API_KEY": settings.CLOUDINARY_API_KEY,
                "CLOUDINARY_API_SECRET": settings.CLOUDINARY_API_SECRET
            }.items()
            if not value
        ]

        if missing:
            raise StorageConfigurationError(
                "Missing required Cloudinary configuration values: "
                f"{', '.join(missing)}"
            )

        cloudinary.config(
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
            
            secure=True,
        )



    def upload(
        self,
        file: BinaryIO,
        *,
        filename: str,
        public_id: str | None = None,
    ) -> app.schemas.document_upload.UploadResult:
        """
        Upload a file directly to Cloudinary.

        `file` should be a file-like binary object such as
        FastAPI's `UploadFile.file`.

        The service does not read from or depend on a local file path.
        """

        if not filename or not filename.strip():
            raise StorageUploadError(
                "Filename is required for upload."
            )

        resource_type = self._resource_type_for_file(filename)

        folder = settings.CLOUDINARY_TEMP_FOLDER

        generated_public_id = self._build_public_id(
            folder=folder,
            filename=filename,
            public_id=public_id,
        )

        try:
            result: dict[str, Any] = cloudinary.uploader.upload(
                file,
                public_id=generated_public_id,
                resource_type=resource_type,
                type=self._DELIVERY_TYPE,
            )

        except CloudinaryError as exc:
            raise StorageUploadError(
                f"Cloudinary upload failed for file {filename}: {exc}"
            ) from exc

        except Exception as exc:
            raise StorageUploadError(
                "Unexpected error during Cloudinary upload "
                f"for file {filename}: {exc}"
            ) from exc

        return app.schemas.document_upload.UploadResult(
            public_id=result["public_id"],
            resource_type=result["resource_type"],
            format=result.get("format"),
            bytes=result.get("bytes"),
            source_url=result.get("secure_url"),
            stage=app.schemas.document_upload.StorageStage.TEMP,
        )



    @staticmethod
    def _resource_type_for_file(filename: str) -> str:
        """
        Determine Cloudinary resource type from the filename.

        PDF/DOCX -> raw
        JPG/JPEG/PNG -> image
        """

        extension = Path(filename).suffix.lower()

        if extension in {".pdf", ".docx"}:
            return "raw"

        if extension in {".jpg", ".jpeg", ".png"}:
            return "image"

        raise StorageUploadError(
            f"Unsupported document extension: '{extension}'"
        )



    @staticmethod
    def _build_public_id(
        *,
        folder: str,
        filename: str,
        public_id: str | None = None,
    ) -> str:
        """
        Build the Cloudinary public ID.

        The filename extension is intentionally not included in the
        public ID. The actual file format is returned by Cloudinary
        and should be retained by the caller when needed.
        """

        if public_id:
            name = public_id.strip("/")
        else:
            name = Path(filename).stem

        return f"{folder.strip('/')}/{name}"

    def generate_signed_url(
        self,
        public_id: str,
        *,
        resource_type: str,
        file_format: str,
        expires_in: int = 300,
    ) -> str:
        """
        Generate a short-lived signed URL for a private Cloudinary asset.

        `file_format` must be provided explicitly because the public ID
        does not contain the file extension.
        """

        if expires_in <= 0:
            raise StorageUrlGenerationError(
                f"Invalid expires_in value: {expires_in}. "
                "Must be a positive integer."
            )

        if not file_format or not file_format.strip():
            raise StorageUrlGenerationError(
                "File format is required to generate a signed URL."
            )

        file_format = file_format.lstrip(".")

        expires_at = (
            int(datetime.now(timezone.utc).timestamp())
            + expires_in
        )

        try:
            return cloudinary.utils.private_download_url(
                public_id,
                file_format,
                resource_type=resource_type,
                type=self._DELIVERY_TYPE,
                expires_at=expires_at,
            )

        except CloudinaryError as exc:
            raise StorageUrlGenerationError(
                f"Failed to generate signed URL for "
                f"public_id {public_id}: {exc}"
            ) from exc

        except Exception as exc:
            raise StorageUrlGenerationError(
                "Unexpected error during signed URL generation "
                f"for public_id {public_id}: {exc}"
            ) from exc



    def move(
        self,
        public_id: str,
        *,
        resource_type: str,
        current_stage: app.schemas.document_upload.StorageStage,
        target_stage: app.schemas.document_upload.StorageStage,
    ) -> app.schemas.document_upload.MoveResult:
        """
        Move a document from one lifecycle stage to another.
        """

        allowed_targets = self._ALLOWED_TRANSITIONS.get(
            current_stage,
            set(),
        )

        if target_stage not in allowed_targets:
            raise InvalidLifecycleTransition(
                f"Invalid transition from {current_stage} "
                f"to {target_stage}. "
                f"Allowed targets: {allowed_targets}. "
                f"Current public_id: {public_id}, "
                f"resource_type: {resource_type}"
            )

        source_folder = self._folder_for_stage(current_stage)
        target_folder = self._folder_for_stage(target_stage)

        file_name = Path(public_id).name

        source_public_id = public_id

        if not source_public_id.startswith(
            source_folder.rstrip("/") + "/"
        ):
            source_public_id = (
                f"{source_folder.rstrip('/')}/{file_name}"
            )

        target_public_id = (
            f"{target_folder.rstrip('/')}/{file_name}"
        )

        try:
            result: dict[str, Any] = cloudinary.uploader.rename(
                source_public_id,
                target_public_id,
                resource_type=resource_type,
                type=self._DELIVERY_TYPE,
                overwrite=False,
            )

        except CloudinaryError as exc:
            raise StorageMoveError(
                f"Failed to move {source_public_id} "
                f"to {target_public_id}: {exc}"
            ) from exc

        except Exception as exc:
            raise StorageMoveError(
                f"Unexpected error during move from "
                f"{source_public_id} to {target_public_id}: {exc}"
            ) from exc

        return app.schemas.document_upload.MoveResult(
            old_public_id=source_public_id,
            public_id=result["public_id"],
            resource_type=result["resource_type"],
            stage=target_stage,
        )

    @staticmethod
    @staticmethod
    def _folder_for_stage(stage: app.schemas.document_upload.StorageStage) -> str:
        folders = {
            app.schemas.document_upload.StorageStage.TEMP: settings.CLOUDINARY_TEMP_FOLDER,
            app.schemas.document_upload.StorageStage.PERMANENT: (
                settings.CLOUDINARY_PERMANENT_FOLDER
            ),
            app.schemas.document_upload.StorageStage.QUARANTINE: (
                settings.CLOUDINARY_QUARANTINE_FOLDER
            ),
            app.schemas.document_upload.StorageStage.REVIEW: settings.CLOUDINARY_REVIEW_FOLDER,
        }

        try:
            return folders[stage]

        except KeyError as exc:
            raise StorageMoveError(
                f"Unsupported storage stage: {stage}"
            ) from exc


    def delete(
        self,
        public_id: str,
        *,
        resource_type: str,
    ) -> app.schemas.document_upload.DeleteResult:
        """
        Delete a document from Cloudinary.
        """

        try:
            result: dict[str, Any] = cloudinary.uploader.destroy(
                public_id,
                resource_type=resource_type,
                type=self._DELIVERY_TYPE,
            )

        except CloudinaryError as exc:
            raise StorageDeleteError(
                f"Failed to delete {public_id}: {exc}"
            ) from exc

        except Exception as exc:
            raise StorageDeleteError(
                "Unexpected error during deletion of "
                f"{public_id}: {exc}"
            ) from exc

        deleted = result.get("result") == "ok"

        return app.schemas.document_upload.DeleteResult(
            public_id=public_id,
            resource_type=resource_type,
            deleted=deleted,
        )

