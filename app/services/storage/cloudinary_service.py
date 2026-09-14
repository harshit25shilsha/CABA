from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
import cloudinary
import cloudinary.uploader
import cloudinary.utils
from cloudinary.exceptions import Error as CloudinaryError

from app.core.config import settings
from .schemas import (
    UploadResult,
    MoveResult,
    DeleteResult,
    StorageStage,
)

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


class CloudinaryStorageService:
    _DELIVERY_TYPE = "private"
    # _DELIVERY_TYPE = "upload"

    _ALLOWED_TRANSITIONS: dict[StorageStage, set[StorageStage]] ={
        StorageStage.TEMP:{
            StorageStage.PERMANENT,
            StorageStage.QUARANTINE,
            StorageStage.REVIEW,
        },
        StorageStage.PERMANENT:set(),
        StorageStage.QUARANTINE:set(),
        StorageStage.REVIEW:set(),
    }

    def __init__(self) -> None:
        self._configure_cloudinary()

    @staticmethod
    def _configure_cloudinary() -> None:
        missing = [
            name for name , value in {
                "CLOUDINARY_CLOUD_NAME": settings.cloudinary_cloud_name,
                "CLOUDINARY_API_KEY": settings.cloudinary_api_key,
                "CLOUDINARY_API_SECRET": settings.cloudinary_api_secret,
            }.items()
            if not value
        ]
        if missing:
            raise  StorageConfigurationError(
                f"Missing required Cloudinary configuration values: {', '.join(missing)}"
            )

        cloudinary.config(
            cloud_name=settings.cloudinary_cloud_name,
            api_key=settings.cloudinary_api_key,
            api_secret=settings.cloudinary_api_secret,
            secure=True,
        )


    def upload(
            self,
            file_path: str|Path,
            *,
            public_id: str|None = None,

    )    -> UploadResult:
        path = Path(file_path)
        if not path.is_file():
            raise StorageUploadError(
                f"File not found: {path}"
            )

        resource_type = self._resource_type_for_file(path)
        folder = settings.cloudinary_temp_folder
        generated_public_id = self._build_public_id(
            folder=folder,
            path = path,
            resource_type=resource_type,
            public_id=public_id,
        )

        try:
            result : dict[str, Any] = cloudinary.uploader.upload(
                str(path),
                public_id=generated_public_id,
                resource_type=resource_type,
                type=self._DELIVERY_TYPE,
            )
        except CloudinaryError as exc:
            raise StorageUploadError(
                f"Cloudinary upload failed for file {path}: {exc}"
            )from exc
        except Exception as exc:
            raise StorageUploadError(
                f"Unexpected error during Cloudinary upload for file {path}: {exc}"
            )from exc 
        return UploadResult(
            public_id=result["public_id"],
            resource_type=result["resource_type"],
            format=result.get("format"),
            bytes=result.get("bytes"),
            source_url=result.get("secure_url"),
            stage=StorageStage.TEMP,
        )


    @staticmethod
    def _resource_type_for_file(path: Path) -> str:
        extension = path.suffix.lower()

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
        path: Path,
        resource_type: str,
        public_id: str|None = None,
    ) -> str:
        if public_id:
            name = public_id.strip("/")
        elif resource_type == "raw":
            name = path.stem
        else:
            name = path.stem

        return f"{folder.strip('/')}/{name}"

    def generate_signed_url(
            self,
            public_id: str,
            *,
            resource_type: str,
            expires_in: int = 300,
    ) -> str:
        """Generate a short-lived signed URL for a private asset."""
        if expires_in <= 0:
            raise StorageUrlGenerationError(
                f"Invalid expires_in value: {expires_in}. Must be a positive integer."
            )

        file_format = Path(public_id).suffix.lstrip(".")

        if not file_format:
            raise StorageUrlGenerationError(
                f"Cannot determine file format from public_id: {public_id}"
            )

        expires_at = int(datetime.now(timezone.utc).timestamp()) + expires_in
        try:
            return cloudinary.utils.private_download_url(
                public_id,
                file_format,
                resource_type=resource_type,
                type = self._DELIVERY_TYPE,
                expires_at=expires_at,
            )
        except CloudinaryError as exc:
            raise StorageUrlGenerationError(
                f"Failed to generate signed URL for public_id {public_id}: {exc}"
            ) from exc
        except Exception as exc:
            raise StorageUrlGenerationError(
                f"Unexpected error during signed URL generation for public_id {public_id}: {exc}"
            ) from exc


    def move(
            self,
            public_id: str,
            *,
            resource_type: str, 
            current_stage: StorageStage,
            target_stage: StorageStage,
        ) -> MoveResult:
            """Move a document from one lifecycle stage to another."""
            allowed_targets = self._ALLOWED_TRANSITIONS.get(current_stage, set())

            if target_stage not in allowed_targets:
                raise InvalidLifecycleTransition(
                    f"Invalid transition from {current_stage} to {target_stage}. Allowed targets: {allowed_targets}"
                    f"Current public_id: {public_id}, resource_type: {resource_type}"
                )

            source_folder = self._folder_for_stage(current_stage)
            target_folder = self._folder_for_stage(target_stage)

            file_name = Path(public_id).name
            source_public_id = public_id

            if not source_public_id.startswith(source_folder.rstrip("/") + "/"):
                source_public_id = f"{source_folder.rstrip('/')}/{file_name}"

            target_public_id = f"{target_folder.rstrip('/')}/{file_name}"

            try:
                result: dict[str, Any] = cloudinary.uploader.rename(
                    source_public_id,
                    target_public_id,
                    resource_type=resource_type,
                    type=self._DELIVERY_TYPE,
                    # overwrite=True,
                    overwrite = False,
                )
            except CloudinaryError as exc:
                raise StorageMoveError(
                    f"Failed to move {source_public_id} "
                    f"to {target_public_id}: {exc}"
                )
            except Exception as exc:
                raise StorageMoveError(
                    f"Unexpected error during move from {source_public_id} "
                    f"to {target_public_id}: {exc}"
                ) from exc

            return MoveResult(
                old_public_id=source_public_id,
                public_id=result["public_id"],
                resource_type=result["resource_type"],
                stage=target_stage,
            )

    @staticmethod
    def _folder_for_stage(stage: StorageStage) -> str:
     folders = {
        StorageStage.TEMP: settings.cloudinary_temp_folder,
        StorageStage.PERMANENT: settings.cloudinary_permanent_folder,
        StorageStage.QUARANTINE: settings.cloudinary_quarantine_folder,
        StorageStage.REVIEW: settings.cloudinary_review_folder,
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
    ) -> DeleteResult:
        """Delete a document from Cloudinary."""
        try:
            result = cloudinary.uploader.destroy(
              public_id,
              resource_type=resource_type,
              type=self._DELIVERY_TYPE,
            )
        except CloudinaryError as exc:
            raise StorageDeleteError(
                f"failed  to delete{public_id}:{exc}"

            )   from exc
        except Exception as exc:
            raise StorageDeleteError(
                f"Unexpected error during the deletion of {public_id}: {exc}   "

            ) from exc
        deleted = result.get("result") == "ok"
        return DeleteResult(
        public_id=public_id,
        resource_type=resource_type,
        deleted=deleted,
        )








            
            

