"""Validated, synchronous orchestration for the loopback File Processor API.

This module has no Flask dependency.  It is intentionally the boundary between
untrusted JSON and the terminal-oriented :class:`FileProcessor` implementation.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.connection_profiles import ProfileStore
from src.profile_resolver import resolve_profile_by_name

from .audio_processor import (
    ARNNDN_MODELS,
    BITRATE_OPTIONS,
    SAMPLE_RATE_OPTIONS,
    AudioProcessor,
    Intensity,
    get_all_presets,
)
from .checkpoint import CheckpointManager
from .config import get_file_processor_prompts, get_prompt_by_key, load_tools_config
from .file_handler import FileHandler, FileInfo, ScanResult
from .file_processor import LARGE_FILE_MODE_CHUNKING, LARGE_FILE_MODE_FILES_API, LARGE_FILE_MODE_SKIP, FileProcessor
from .pdf_processor import get_pdf_page_count, is_pypdf_available, parse_page_range, split_pdf

EFFECT_NAMES = {"highpass", "lowpass", "afftdn", "speechnorm", "dynaudnorm", "loudnorm", "equalizer", "compand"}
LARGE_FILE_MODES = {LARGE_FILE_MODE_FILES_API, LARGE_FILE_MODE_CHUNKING, LARGE_FILE_MODE_SKIP}


class JobValidationError(ValueError):
    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("Invalid File Processor job request")


class JobSemanticError(JobValidationError):
    """A well-formed request which cannot safely be run."""


class JobBusyError(RuntimeError):
    def __init__(self, job_id: str | None):
        self.job_id = job_id
        super().__init__("A File Processor job is already running")


@dataclass
class ScriptedOutputOptions:
    mode: str
    path: Path
    naming: str
    extension: str
    overwrite: bool = False


@dataclass
class ScriptedJobOptions:
    input_path: Path
    recursive: bool
    file_types: set[str] | None
    prompt_key: str
    prompt_text: str
    profile_name: str
    output: ScriptedOutputOptions
    delay: float = 1.0
    use_batch: bool = False
    include_filename: bool = True
    custom_instructions: str | None = None
    per_file_instructions: dict[str, str] = field(default_factory=dict)
    large_file_mode: str = LARGE_FILE_MODE_FILES_API
    pdf: dict[str, Any] = field(default_factory=lambda: {"split": False, "page_range": "all"})
    transcribe_config: dict[str, Any] | None = None
    audio_preprocessing: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["input_path"] = str(self.input_path)
        value["file_types"] = sorted(self.file_types) if self.file_types else None
        value["output"]["path"] = str(self.output.path)
        return value


@dataclass
class ScriptedJobResult:
    job_id: str
    status: str
    tool_result: Any
    output_paths: list[str]
    elapsed_time: float

    @property
    def success(self) -> bool:
        return self.status == "completed"

    def to_api_dict(self) -> dict[str, Any]:
        relative = []
        cwd = Path.cwd().resolve()
        for path in self.output_paths:
            try:
                relative.append(str(Path(path).resolve().relative_to(cwd)))
            except ValueError:
                relative.append(str(Path(path).resolve()))
        return {
            "success": self.success,
            "job_id": self.job_id,
            "status": self.status,
            "message": self.tool_result.message,
            "processed_count": self.tool_result.processed_count,
            "failed_count": self.tool_result.failed_count,
            "total_count": self.tool_result.total_count,
            "output_path": self.tool_result.output_path,
            "output_paths": self.output_paths,
            "output_paths_relative": relative,
            "errors": self.tool_result.errors,
            "elapsed_time": round(self.elapsed_time, 3),
        }


def _path(value: Any, field_name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise JobValidationError({field_name: "Must be a non-empty string"})
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def _json_scalar(value: Any) -> bool:
    return (
        value is None
        or (isinstance(value, (str, int, float, bool)) and not isinstance(value, float))
        or (isinstance(value, float) and math.isfinite(value))
    )


def _parse_audio(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or not value:
        raise JobValidationError({"audio": "Must be a non-empty object or null"})
    typ = value.get("type")
    errors: dict[str, str] = {}
    if typ not in {"normalize", "amplify", "amplify_normalize", "preset", "custom"}:
        errors["audio.type"] = "Unsupported audio processing type"
    if typ in {"amplify", "amplify_normalize"} and (
        not isinstance(value.get("volume_percent"), (int, float)) or value["volume_percent"] <= 0
    ):
        errors["audio.volume_percent"] = "Must be a positive number"
    if typ == "preset":
        preset_ids = {p.id for p in get_all_presets()}
        if value.get("preset_id") not in preset_ids:
            errors["audio.preset_id"] = "Unknown preset"
        if value.get("intensity", "medium") not in {x.value for x in Intensity}:
            errors["audio.intensity"] = "Must be low, medium, or high"
        if value.get("arnndn_model") is not None and value["arnndn_model"] not in ARNNDN_MODELS:
            errors["audio.arnndn_model"] = "Unknown ARNNDN model"
    if typ == "custom":
        effects = value.get("effects")
        if not isinstance(effects, list) or not effects or len(effects) > 32:
            errors["audio.effects"] = "Must contain 1 to 32 effects"
        else:
            for index, effect in enumerate(effects):
                if not isinstance(effect, dict) or effect.get("name") not in EFFECT_NAMES:
                    errors[f"audio.effects.{index}"] = "Unknown effect"
                    continue
                params = effect.get("params", {})
                if not isinstance(params, dict) or not all(
                    isinstance(k, str) and _json_scalar(v) for k, v in params.items()
                ):
                    errors[f"audio.effects.{index}.params"] = "Parameters must be JSON scalars"
    optimization = value.get("optimization")
    if optimization is not None:
        if not isinstance(optimization, dict):
            errors["audio.optimization"] = "Must be an object"
        else:
            if "convert_to_mono" in optimization and not isinstance(optimization["convert_to_mono"], bool):
                errors["audio.optimization.convert_to_mono"] = "Must be boolean"
            if "sample_rate" in optimization and optimization["sample_rate"] not in SAMPLE_RATE_OPTIONS:
                errors["audio.optimization.sample_rate"] = "Unsupported sample rate"
            if "bitrate_kbps" in optimization and optimization["bitrate_kbps"] not in BITRATE_OPTIONS:
                errors["audio.optimization.bitrate_kbps"] = "Unsupported bitrate"
    if "force_no_chunking" in value and not isinstance(value["force_no_chunking"], bool):
        errors["audio.force_no_chunking"] = "Must be boolean"
    if errors:
        raise JobValidationError(errors)
    processor = AudioProcessor()
    if not processor.is_available():
        raise JobSemanticError({"audio": "FFmpeg is required for requested audio processing"})
    if typ == "preset" and value.get("arnndn_model") and not processor.is_arnndn_available():
        raise JobSemanticError({"audio.arnndn_model": "The selected ARNNDN effect is unavailable"})
    if typ == "preset" and value.get("preset_id") == "ai_deep_denoise" and not processor.is_deep_filter_available():
        raise JobSemanticError({"audio.preset_id": "DeepFilterNet is unavailable"})
    return value


def parse_scripted_options(
    payload: Any, *, config: dict, ai_params: dict, key_managers: dict, resume_options: ScriptedJobOptions | None = None
) -> ScriptedJobOptions:
    """Parse JSON into typed options.  Raises errors grouped by JSON field."""
    if not isinstance(payload, dict):
        raise JobValidationError({"body": "Expected a JSON object"})
    data = dict(payload)
    if resume_options:
        immutable = {
            key: "This field is immutable when resuming"
            for key in ("input_path", "recursive", "file_types")
            if key in data
        }
        if immutable:
            raise JobValidationError(immutable)
        merged = resume_options.to_dict()
        merged.update(data)
        if "output" in data and isinstance(data["output"], dict):
            merged["output"].update(data["output"])
        data = merged

    errors: dict[str, str] = {}
    semantic: dict[str, str] = {}
    try:
        input_path = _path(data.get("input_path"), "input_path")
    except JobValidationError as exc:
        errors.update(exc.errors)
        input_path = Path(".")
    recursive = data.get("recursive", False)
    if not isinstance(recursive, bool):
        errors["recursive"] = "Must be boolean"
    raw_types = data.get("file_types")
    file_types = None
    allowed_types = set(FileHandler.DEFAULT_FILE_TYPES)
    if raw_types is not None:
        if (
            not isinstance(raw_types, list)
            or not raw_types
            or any(not isinstance(x, str) or x not in allowed_types for x in raw_types)
        ):
            errors["file_types"] = "Must be a non-empty subset of supported file types"
        else:
            file_types = set(raw_types)
    named, literal = data.get("prompt_name"), data.get("prompt")
    if bool(isinstance(named, str) and named.strip()) == bool(isinstance(literal, str) and literal.strip()):
        errors["prompt"] = "Provide exactly one non-empty prompt_name or prompt"
    tools = load_tools_config()
    prompt_key, prompt_text, prompt_config = "", "", {}
    if isinstance(named, str) and named.strip():
        prompt_key = named.strip()
        prompt_config = get_prompt_by_key(tools, prompt_key) or {}
        if not prompt_config:
            semantic["prompt_name"] = "Unknown configured prompt"
        else:
            prompt_text = prompt_config.get("prompt", prompt_config.get("instruction", ""))
    elif isinstance(literal, str) and literal.strip():
        prompt_key, prompt_text = "Custom", literal.strip()
    profile_name = data.get("profile_name")
    profile = (
        ProfileStore.get_instance().get_profile(profile_name)
        if isinstance(profile_name, str) and profile_name.strip()
        else None
    )
    if not profile_name or not isinstance(profile_name, str):
        errors["profile_name"] = "Must be a non-empty profile name"
    elif not profile or not profile.enabled:
        semantic["profile_name"] = "Profile does not exist or is disabled"
    out = data.get("output")
    output = None
    if not isinstance(out, dict):
        errors["output"] = "Must be an object"
    else:
        mode, naming = out.get("mode"), out.get("naming")
        try:
            out_path = _path(out.get("path"), "output.path")
        except JobValidationError as exc:
            errors.update(exc.errors)
            out_path = Path(".")
        extension = out.get("extension")
        if mode not in {"individual", "combined"}:
            errors["output.mode"] = "Must be individual or combined"
        if not isinstance(naming, str) or not naming or any(s in naming for s in ("/", "\\")):
            errors["output.naming"] = "Must be a filename template without path separators"
        if not isinstance(extension, str) or not extension.strip() or "/" in extension or "\\" in extension:
            errors["output.extension"] = "Must be a filename suffix"
        else:
            extension = "." + extension.lstrip(".")
        if not isinstance(out.get("overwrite", False), bool):
            errors["output.overwrite"] = "Must be boolean"
        output = ScriptedOutputOptions(mode or "", out_path, naming or "", extension or "", out.get("overwrite", False))
    delay = data.get("delay", 1.0)
    if not isinstance(delay, (int, float)) or isinstance(delay, bool) or not math.isfinite(delay) or delay < 0:
        errors["delay"] = "Must be a finite number >= 0"
    use_batch = data.get("use_batch", False)
    if not isinstance(use_batch, bool):
        errors["use_batch"] = "Must be boolean"
    if profile and use_batch and profile.provider != "google":
        errors["use_batch"] = "Batch API requires a Google profile"
    if not isinstance(data.get("include_filename", True), bool):
        errors["include_filename"] = "Must be boolean"
    if data.get("custom_instructions") is not None and not isinstance(data["custom_instructions"], str):
        errors["custom_instructions"] = "Must be a string or null"
    large = data.get("large_file_mode", LARGE_FILE_MODE_FILES_API)
    if large not in LARGE_FILE_MODES:
        errors["large_file_mode"] = "Unsupported large file mode"
    if profile and large == LARGE_FILE_MODE_FILES_API and profile.provider != "google":
        errors["large_file_mode"] = "Files API requires a Google profile"
    pdf = data.get("pdf", {"split": False, "page_range": "all"})
    if (
        not isinstance(pdf, dict)
        or not isinstance(pdf.get("split", False), bool)
        or not isinstance(pdf.get("page_range", "all"), str)
    ):
        errors["pdf"] = "Invalid PDF options"
    elif pdf.get("split") and not is_pypdf_available():
        raise JobSemanticError({"pdf.split": "pypdf is required for PDF splitting"})
    transcription = data.get("transcription")
    if transcription is not None:
        if not isinstance(transcription, dict):
            errors["transcription"] = "Must be an object"
        elif not (
            prompt_config.get("transcribe_model")
            or (profile and (profile.provider == "transcription" or "transcribe" in profile.model.lower()))
        ):
            errors["transcription"] = "Requires a transcription prompt or profile"
        else:
            mode = transcription.get("mode", "VERBATIM")
            if mode not in {"VERBATIM", "SMART"}:
                errors["transcription.mode"] = "Must be VERBATIM or SMART"
            if mode == "SMART" and (transcription.get("diarization") or transcription.get("word_timestamp")):
                errors["transcription"] = "SMART does not support diarization or word timestamps"
            if any(not isinstance(x, str) or not x.strip() for x in transcription.get("language_codes", [])):
                errors["transcription.language_codes"] = "Must contain non-empty strings"
            if any(not isinstance(x, str) for x in transcription.get("custom_vocabulary", [])):
                errors["transcription.custom_vocabulary"] = "Must contain strings"
    try:
        audio = _parse_audio(data.get("audio"))
    except JobValidationError as exc:
        errors.update(exc.errors)
        audio = None
    if errors:
        raise JobValidationError(errors)
    if semantic:
        raise JobSemanticError(semantic)
    if transcription is None and (
        prompt_config.get("transcribe_model") or (profile and profile.provider == "transcription")
    ):
        transcription = (
            profile.to_transcribe_config()
            if profile and profile.provider == "transcription"
            else {
                "model": prompt_config.get("model", "gemini-3.5-transcribe"),
                "mode": prompt_config.get("transcribe_mode", "VERBATIM"),
                "diarization": False,
                "word_timestamp": False,
                "language_codes": [],
                "custom_vocabulary": [],
            }
        )
    return ScriptedJobOptions(
        input_path,
        recursive,
        file_types,
        prompt_key,
        prompt_text,
        profile_name.strip(),
        output,
        float(delay),
        use_batch,
        data.get("include_filename", True),
        data.get("custom_instructions"),
        {},
        large,
        {"split": pdf.get("split", False), "page_range": pdf.get("page_range", "all")},
        transcription,
        audio,
    )


class FileProcessorJobService:
    JOBS_DIR = Path(".file_processor_jobs")

    def __init__(self, config: dict, ai_params: dict, key_managers: dict):
        self.config, self.ai_params, self.key_managers = config, ai_params, key_managers
        self._lock = threading.Lock()
        self.active_job_id: str | None = None

    def capabilities(self) -> dict[str, Any]:
        prompts = get_file_processor_prompts(load_tools_config())
        return {
            "api_version": 1,
            "busy": self.active_job_id is not None,
            "profiles": ProfileStore.get_instance().get_profile_names(),
            "prompts": [
                {
                    "name": n,
                    "description": p.get("description", ""),
                    "input_types": p.get("input_types", []),
                    "output_extension": p.get("output_extension", ""),
                    "default_naming": p.get("default_naming", ""),
                    "transcribe_model": bool(p.get("transcribe_model")),
                }
                for n, p in prompts.items()
                if not n.startswith("_")
            ],
            "file_types": list(FileHandler.DEFAULT_FILE_TYPES),
            "large_file_modes": sorted(LARGE_FILE_MODES),
            "audio": {
                "preset_ids": [p.id for p in get_all_presets()],
                "intensities": [x.value for x in Intensity],
                "arnndn_models": list(ARNNDN_MODELS),
                "effect_names": sorted(EFFECT_NAMES),
            },
        }

    def _scan(self, options: ScriptedJobOptions, job_dir: Path) -> list[FileInfo]:
        if not options.input_path.exists():
            raise JobSemanticError({"input_path": "Path does not exist"})
        scan = FileHandler().scan(options.input_path, recursive=options.recursive)
        files = [f for f in scan.files if not options.file_types or f.file_type in options.file_types]
        if options.pdf["split"]:
            expanded: list[FileInfo] = []
            for info in files:
                if info.file_type != "document":
                    expanded.append(info)
                    continue
                count = get_pdf_page_count(info.path)
                pages = parse_page_range(options.pdf["page_range"], count or 0)
                if not pages:
                    raise JobSemanticError({"pdf.page_range": f"No selected pages in {info.path.name}"})
                expanded.extend(
                    FileHandler().get_file_info(p)
                    for p in split_pdf(info.path, pages, job_dir / "pdf_tmp" / info.path.stem)
                )
            files = expanded
        if not files:
            raise JobSemanticError({"input_path": "No supported files matched"})
        if options.output.mode == "combined" and len(files) < 2:
            raise JobSemanticError({"output.mode": "Combined output requires multiple files"})
        return files

    def _planned_outputs(self, options: ScriptedJobOptions, files: list[FileInfo], timestamp: datetime) -> list[Path]:
        handler = FileHandler()
        if options.output.mode == "combined":
            return [
                handler.get_output_path(
                    options.input_path,
                    options.output.path,
                    "batch_output_{date}_{time}",
                    options.output.extension,
                    timestamp=timestamp,
                )
            ]
        return [
            handler.get_output_path(
                f.path,
                options.output.path,
                options.output.naming,
                options.output.extension,
                i,
                options.input_path if options.input_path.is_dir() else None,
                timestamp,
            )
            for i, f in enumerate(files)
        ]

    def _preflight(
        self,
        options: ScriptedJobOptions,
        files: list[FileInfo],
        timestamp: datetime,
        allowed: set[str] | None = None,
    ) -> None:
        allowed = allowed or set()
        planned = self._planned_outputs(options, files, timestamp)
        if len(set(planned)) != len(planned):
            raise JobSemanticError({"output": "Output naming creates duplicate paths"})
        if not options.output.overwrite:
            collision = next((p for p in planned if p.exists() and str(p) not in allowed), None)
            if collision:
                raise JobSemanticError(
                    {"output": f"Output already exists: {collision}. Set output.overwrite=true to replace it."}
                )

    def _atomic_json(self, path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            name = handle.name
        Path(name).replace(path)

    def _run(
        self,
        job_id: str,
        options: ScriptedJobOptions,
        files: list[FileInfo],
        job_dir: Path,
        previous: list[str] | None = None,
        timestamp: datetime | None = None,
    ) -> ScriptedJobResult:
        started = timestamp or datetime.now()
        timestamp = started
        processor = FileProcessor(config=self.config)
        processor.checkpoint_manager = CheckpointManager(checkpoint_file="checkpoint.json", checkpoint_dir=job_dir)
        processor._output_timestamp = timestamp
        result = processor.run_scripted(options, input_files=files)
        paths = list(dict.fromkeys((previous or []) + result.output_paths))
        status = "completed" if result.success else "failed"
        return ScriptedJobResult(job_id, status, result, paths, (datetime.now() - started).total_seconds())

    def run(self, payload: dict) -> ScriptedJobResult:
        options = parse_scripted_options(
            payload, config=self.config, ai_params=self.ai_params, key_managers=self.key_managers
        )
        job_id = uuid.uuid4().hex[:12]
        job_dir = self.JOBS_DIR / job_id
        files = self._scan(options, job_dir)
        timestamp = datetime.now()
        self._preflight(options, files, timestamp)
        # Validate per-file instructions after the source set is known.
        per = payload.get("per_file_instructions", {})
        if not isinstance(per, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in per.items()):
            raise JobValidationError({"per_file_instructions": "Must map paths to strings"})
        source_set = {str(f.path.resolve()) for f in files}
        options.per_file_instructions = {str(_path(k, "per_file_instructions")): v for k, v in per.items()}
        if not set(options.per_file_instructions).issubset(source_set):
            raise JobSemanticError({"per_file_instructions": "Contains a path outside this job"})
        if not self._lock.acquire(blocking=False):
            raise JobBusyError(self.active_job_id)
        self.active_job_id = job_id
        try:
            self._atomic_json(
                job_dir / "job.json",
                {
                    "job_id": job_id,
                    "created_at": datetime.now().isoformat(),
                    "status": "running",
                    "options": options.to_dict(),
                    "input_files": [str(x.path) for x in files],
                    "completed_output_paths": [],
                },
            )
            response = self._run(job_id, options, files, job_dir, timestamp=timestamp)
            self._atomic_json(job_dir / "result.json", response.to_api_dict())
            if response.success:
                shutil.rmtree(job_dir, ignore_errors=True)
            return response
        finally:
            self.active_job_id = None
            self._lock.release()

    def get(self, job_id: str) -> dict[str, Any] | None:
        path = self.JOBS_DIR / job_id / "result.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def resume(self, job_id: str, payload: dict) -> ScriptedJobResult:
        job_dir = self.JOBS_DIR / job_id
        job_file = job_dir / "job.json"
        if not job_file.exists():
            raise FileNotFoundError(job_id)
        record = json.loads(job_file.read_text(encoding="utf-8"))
        saved = parse_scripted_options(
            record["options"], config=self.config, ai_params=self.ai_params, key_managers=self.key_managers
        )
        options = parse_scripted_options(
            payload, config=self.config, ai_params=self.ai_params, key_managers=self.key_managers, resume_options=saved
        )
        manager = CheckpointManager(checkpoint_file="checkpoint.json", checkpoint_dir=job_dir)
        checkpoint = manager.load() or manager.load_failed()
        if not checkpoint:
            raise JobSemanticError({"job_id": "Job has no resumable checkpoint"})
        # A failed checkpoint contains only failures (the interactive retry
        # format). Restore the original ordered set so output {index} values
        # remain stable and completed inputs are never retried.
        original_files = [str(Path(p).resolve()) for p in record["input_files"]]
        failed_paths = {str(Path(p).resolve()) for p in checkpoint.input_files}
        checkpoint.input_files = original_files
        checkpoint.completed_files = [p for p in original_files if p not in failed_paths]
        checkpoint.input_path = str(saved.input_path)
        files = [FileHandler().get_file_info(Path(p)) for p in original_files]
        previous = (self.get(job_id) or {}).get("output_paths", [])
        if not self._lock.acquire(blocking=False):
            raise JobBusyError(self.active_job_id)
        self.active_job_id = job_id
        try:
            # Failed checkpoints contain only failed inputs; clear their failure list so they are retried.
            checkpoint.failed_files = []
            remaining = [f for f in files if str(f.path) not in set(checkpoint.completed_files)]
            self._preflight(options, remaining, datetime.now(), set(previous))
            processor = FileProcessor(config=self.config)
            processor.checkpoint_manager = manager
            processor._output_timestamp = datetime.now()
            result = processor.run_scripted(options, input_files=files, checkpoint=checkpoint)
            paths = list(dict.fromkeys(previous + result.output_paths))
            response = ScriptedJobResult(
                job_id, "completed" if result.success else "failed", result, paths, result.elapsed_time
            )
            self._atomic_json(job_dir / "result.json", response.to_api_dict())
            if response.success:
                shutil.rmtree(job_dir, ignore_errors=True)
            return response
        finally:
            self.active_job_id = None
            self._lock.release()

    def delete(self, job_id: str) -> bool:
        if self.active_job_id == job_id:
            raise JobBusyError(job_id)
        path = self.JOBS_DIR / job_id
        if not path.exists():
            return False
        shutil.rmtree(path)
        return True
