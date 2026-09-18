from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
# This enum defines all the possible storage locations
# where a document can be stored in our application.
class StorageStage(str, Enum):
    TEMP = "temp"
    PERMANENT = "permanent"
    QUARANTINE = "quarantine"
    REVIEW = "review"

# This class stores the information returned after uploading a file.
# frozen=True means the result cannot be changed after it is created.


@dataclass(frozen=True)
class UploadResult:
    public_id: str
    resource_type: str
    format: str|None
    bytes: int|None
    source_url: str|None
    stage: StorageStage


# This class stores the information returned after moving a file
# from one storage stage to another.    

@dataclass(frozen=True)
class MoveResult:
    old_public_id: str
    public_id: str
    resource_type: str
    stage: StorageStage



# This class stores the information returned after deleting a file.
@dataclass(frozen=True)
class DeleteResult:
    public_id: str
    resource_type: str
    deleted: bool        