"""Model registry and evaluation contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from maya_contracts.common import StrictModel


class CapabilityFamily(str, Enum):
    TEXT_GENERATION = "text_generation"
    TEXT_EMBEDDING = "text_embedding"
    VISION_LANGUAGE = "vision_language"
    TTS = "tts"
    IMAGE_GENERATION = "image_generation"
    RERANKER = "reranker"


class Modality(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"


class EvalStatus(str, Enum):
    DISCOVERED = "discovered"
    QUARANTINED = "quarantined"
    METADATA_ENRICHED = "metadata_enriched"
    SMOKE_TESTED = "smoke_tested"
    HOUSE_EVALUATED = "house_evaluated"
    ARENA_EXPOSED = "arena_exposed"
    CANARY = "canary"
    PROMOTED = "promoted"
    DEPRECATED = "deprecated"
    REJECTED = "rejected"


class EvalType(str, Enum):
    DATASET_SCORED = "dataset_scored"
    JUDGE_ASSISTED = "judge_assisted"
    HUMAN_BATTLE = "human_battle"


class Artifact(StrictModel):
    path: str
    checksum: Optional[str] = None
    size_bytes: Optional[int] = None
    format: str  # safetensors, gguf, onnx, etc.


class ModelRelease(StrictModel):
    id: str
    slug: str
    provider: str  # huggingface, github, etc.
    source_url: str
    capability_family: CapabilityFamily
    modality_in: list[Modality]
    modality_out: list[Modality]
    base_model: Optional[str] = None
    quantization: Optional[str] = None
    runtime: Optional[str] = None  # vllm, llama.cpp, tei, etc.
    license: Optional[str] = None
    artifacts: list[Artifact] = []
    eval_status: EvalStatus = EvalStatus.DISCOVERED
    publisher_claims: dict[str, Any] = {}
    tags: list[str] = []
    created_at: datetime
    updated_at: datetime


class EvalRun(StrictModel):
    id: str
    model_release_id: str
    eval_suite: str  # mmlu, mteb, house_retrieval, arena, etc.
    eval_type: EvalType
    status: str  # queued, running, completed, failed
    metrics: dict[str, Any] = {}
    artifact_paths: list[str] = []
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class ModelReleaseCreate(StrictModel):
    slug: str
    provider: str
    source_url: str
    capability_family: CapabilityFamily
    modality_in: list[Modality]
    modality_out: list[Modality]
    base_model: Optional[str] = None
    quantization: Optional[str] = None
    runtime: Optional[str] = None
    license: Optional[str] = None
    artifacts: list[Artifact] = []
    tags: list[str] = []


class ModelReleaseUpdate(StrictModel):
    eval_status: Optional[EvalStatus] = None
    publisher_claims: Optional[dict[str, Any]] = None
    tags: Optional[list[str]] = None
