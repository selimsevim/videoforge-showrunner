from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import ValidationError
from PIL import Image

from qwen_multishot_test import ModelStudioClient, build_base_url, get_api_key
from videoforge.cinematography import (
    cinematography_issues,
    framing_family,
    framing_visibility_contract,
)
from videoforge.config import Settings
from videoforge.consistency import repair_plan_consistency
from videoforge.planner import deterministic_seed
from videoforge.prompting import prompt_hash
from videoforge.retry import is_retryable_error
from videoforge.schemas import (
    ConsistencyReport,
    ConsistencyWarning,
    ProductionPlan,
    ProjectInput,
    ProviderImageRequest,
    ProviderVideoRequest,
    VisualBible,
)

from .base import ProviderError, ShowrunnerProvider


class QwenCloudProvider(ShowrunnerProvider):
    """Qwen Cloud provider built on the already validated raw HTTP client."""

    name = "qwen"

    def __init__(self, settings: Settings):
        self.settings = settings
        api_key = os.environ.get("QWEN_API_KEY", "").strip()
        if not api_key:
            api_key, _ = get_api_key()
        if not api_key:
            api_key = os.environ.get("QWEN_CLOUD_API_KEY", "").strip()
        if not api_key:
            raise ProviderError(
                "QWEN_API_KEY, DASHSCOPE_API_KEY, or QWEN_CLOUD_API_KEY is required",
                code="INVALID_API_KEY",
            )
        self.api_key = api_key
        try:
            self.native_base, _ = build_base_url()
        except ValueError as exc:
            raise ProviderError(str(exc), code="INVALID_BASE_URL") from exc
        self.text_base = self._text_base_url()
        self.client = ModelStudioClient(api_key, self.native_base)

    def _text_base_url(self) -> str:
        configured = (
            os.environ.get("QWEN_CLOUD_BASE_URL")
            or os.environ.get("QWEN_BASE_URL")
            or ""
        ).strip().rstrip("/")
        if configured and "compatible-mode" in configured:
            return configured
        parsed = urlparse(self.native_base)
        return f"{parsed.scheme}://{parsed.netloc}/compatible-mode/v1"

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        stripped = text.strip()
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            start, end = stripped.find("{"), stripped.rfind("}")
            if start >= 0 and end > start:
                return json.loads(stripped[start : end + 1])
            raise

    @staticmethod
    def _normalize_plan_raw(
        raw: dict[str, Any], project_id: str, project: ProjectInput
    ) -> dict[str, Any]:
        """Normalize provider bookkeeping without changing creative shot direction."""
        raw["projectId"] = project_id
        shots = raw.get("shots")
        if not isinstance(shots, list):
            return raw
        duration = max(
            2, min(5, round(project.target_duration_seconds / max(1, len(shots))))
        )
        shared_image_seed = deterministic_seed(
            project_id, 0, "shared-storyboard-image"
        )
        for order, shot in enumerate(shots, 1):
            if not isinstance(shot, dict):
                continue
            shot["id"] = f"shot-{order:02d}"
            shot["order"] = order
            shot["durationSeconds"] = duration
            shot["imageSeed"] = shared_image_seed
            seed = shot.get("videoSeed")
            if not isinstance(seed, int) or not 0 <= seed <= 2**31 - 1:
                shot["videoSeed"] = deterministic_seed(project_id, order, "video")
        return raw

    def _planning_payload(self, project_id: str, project: ProjectInput) -> dict[str, Any]:
        schema = ProductionPlan.model_json_schema(by_alias=True)
        shot_count = project.shot_count
        beat_guidance = (
            "establish, discover, inspect, recognize, dread, reveal"
            if shot_count == 6
            else "establish, escalate, reveal"
        )
        system = (
            "You are VideoForge's Narrative, Visual, and Storyboard Director. "
            "Return only JSON matching the supplied schema. Design one character, one "
            f"environment, and exactly {shot_count} achievable visual shots, with consecutive "
            f"IDs shot-01 through shot-{shot_count:02d}. Use this beat progression: "
            f"{beat_guidance}. Each shot uses one restrained action and one simple camera move. "
            "Do not include dialogue, crowds, location changes, or action choreography. "
            "Direct the coverage dynamically from the story; never apply a fixed shot order. "
            "The opening may be a wide, close-up, detail, POV, or another motivated frame. "
            "Across the complete sequence use at least four distinct coverage families chosen "
            "from wide/master, medium, close-up, insert/detail, over-the-shoulder, and POV. "
            "Vary framing and subject position deliberately and make the character's physical "
            "action and eyeline advance the story from one frame to the next. Establish a clear "
            "screen geography in the visual bible and preserve the 180-degree axis unless a "
            "motivated shot explicitly crosses it. Do not repeat the same seated or standing "
            "portrait composition. Set propState to its exact realistic size, placement, "
            "visibility, and story state for each shot. Make "
            "imageDelta a complete, concrete visual direction that restates the composition, "
            "action, emotional beat, and prop placement for that one frame. "
            f"Distribute the requested {project.target_duration_seconds} seconds across all "
            f"{shot_count} shots, keeping every duration between 2 and 5 seconds. "
            "Set imagePrompt and motionPrompt to short placeholders; the server will compile "
            "them safely from the validated visual bible."
        )
        user = {
            "projectId": project_id,
            "input": project.model_dump(by_alias=True),
            "requiredSchema": schema,
        }
        return {
            "model": self.settings.qwen_text_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
        }

    def create_production_plan(
        self, project_id: str, project: ProjectInput
    ) -> ProductionPlan:
        payload = self._planning_payload(project_id, project)
        try:
            data = self.client.request_json(
                "POST", f"{self.text_base}/chat/completions", json=payload
            )
            content = data["choices"][0]["message"]["content"]
            raw = self._normalize_plan_raw(
                self._extract_json(content), project_id, project
            )
            plan = ProductionPlan.model_validate(raw)
            issues = cinematography_issues(plan)
            if issues:
                revision = self.client.request_json(
                    "POST",
                    f"{self.text_base}/chat/completions",
                    json=self._cinematography_revision_payload(
                        project_id, project, plan, issues
                    ),
                )
                revised_raw = self._normalize_plan_raw(
                    self._extract_json(
                        revision["choices"][0]["message"]["content"]
                    ),
                    project_id,
                    project,
                )
                plan = ProductionPlan.model_validate(revised_raw)
                remaining = cinematography_issues(plan)
                if remaining:
                    raise ProviderError(
                        "Qwen's revised plan still lacks cinematographic continuity: "
                        + "; ".join(remaining),
                        code="CINEMATOGRAPHY_VALIDATION_FAILED",
                    )
            repaired, _ = repair_plan_consistency(plan)
            return repaired
        except (KeyError, IndexError, json.JSONDecodeError, ValidationError) as exc:
            raise ProviderError(
                f"Qwen returned malformed structured production-plan output: {exc}",
                code="MALFORMED_STRUCTURED_OUTPUT",
            ) from exc
        except RuntimeError as exc:
            raise self._provider_error(exc) from exc

    def _cinematography_revision_payload(
        self,
        project_id: str,
        project: ProjectInput,
        plan: ProductionPlan,
        issues: list[str],
    ) -> dict[str, Any]:
        return {
            "model": self.settings.qwen_text_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a film director revising a storyboard for visual and editorial "
                        "continuity. Return only the complete ProductionPlan JSON matching the "
                        "schema. Resolve every supplied validation issue, but do not impose a "
                        "fixed shot order. Choose coverage and order from the narrative: the film "
                        "may begin wide, close, detail, POV, or otherwise. Preserve the same "
                        "character, location, lighting, screen geography, and 180-degree axis. "
                        "Every cut must advance action, eyeline, information, or prop state. Set "
                        "imagePrompt and motionPrompt to placeholders because the server compiles "
                        "them after validation."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "projectId": project_id,
                            "input": project.model_dump(by_alias=True),
                            "validationIssues": issues,
                            "draftPlan": plan.model_dump(by_alias=True),
                            "requiredSchema": ProductionPlan.model_json_schema(by_alias=True),
                        }
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.25,
        }

    def _image_payload(self, request: ProviderImageRequest) -> dict[str, Any]:
        content: list[dict[str, str]] = []
        prompt = request.prompt
        negative_prompt = request.negative_prompt
        if request.reference_image_url:
            content.append({"image": request.reference_image_url})
            family = framing_family(request.framing or "")
            identity_rule = (
                "Image 1 is the canonical physical-set reference only. The observer must be "
                "entirely absent because this is a first-person POV: remove the woman, her face, "
                "hair, torso, legs, and body from the frame. "
                if family == "pov"
                else "Image 1 is the canonical continuity reference for the actor and set. "
            )
            if family == "pov":
                negative_prompt += (
                    ", visible woman, person, face, head, torso, legs, full body, external view, "
                    "third-person camera"
                )
            elif family == "detail":
                negative_prompt += ", face, head, torso, full body, portrait, room overview"
            prompt = (
                identity_rule
                + "Preserve the exact wall color, window count and position, "
                "bed design and position, shelf, nightstand, floor, lighting direction, and all "
                "architectural details. Do not add, remove, mirror, resize, or relocate windows, "
                "doors, furniture, or shelves. The reference locks identity and set design, NOT "
                "its camera position, crop, pose, or which elements remain visible. Recompose "
                "the camera radically when required. The FRAME_VISIBILITY_CONTRACT is a hard "
                "output specification: anything it excludes must be completely outside the "
                "generated frame. Never preserve the wide reference composition for a close-up, "
                "insert, detail, over-the-shoulder, or POV shot.\n" + prompt
            )
        content.append({"text": prompt})
        return {
            "model": (
                self.settings.qwen_image_edit_model
                if request.reference_image_url
                else self.settings.qwen_image_model
            ),
            "input": {
                "messages": [
                    {"role": "user", "content": content}
                ]
            },
            "parameters": {
                "negative_prompt": negative_prompt[:500],
                "size": request.size,
                "n": 1,
                "prompt_extend": False,
                "watermark": False,
                "seed": request.seed,
            },
        }

    def _video_payload(self, request: ProviderVideoRequest) -> dict[str, Any]:
        first_frame_url = self._media_url(request.first_frame_url)
        return {
            "model": self.settings.qwen_video_model,
            "input": {
                "prompt": request.prompt,
                "negative_prompt": request.negative_prompt,
                "media": [
                    {"type": "first_frame", "url": first_frame_url}
                ],
            },
            "parameters": {
                "resolution": request.resolution,
                "duration": request.duration_seconds,
                "prompt_extend": False,
                "watermark": False,
                "seed": request.seed,
            },
        }

    @staticmethod
    def _media_url(value: str) -> str:
        if value.startswith(("http://", "https://", "data:")):
            return value
        path = Path(value)
        mime = mimetypes.guess_type(path)[0] or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    def _framing_check(
        self, request: ProviderImageRequest, output_path: Path
    ) -> dict[str, Any] | None:
        if not request.framing or not request.subject_position:
            return None
        family = framing_family(request.framing)
        if family in {"wide", "medium", "other"}:
            return None
        mime = mimetypes.guess_type(output_path)[0] or "image/png"
        encoded = base64.b64encode(output_path.read_bytes()).decode("ascii")
        contract = framing_visibility_contract(
            request.framing, request.subject_position
        )
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "You are a strict cinematography framing inspector. Evaluate the supplied "
                    "frame against the contract below, not merely its general subject matter. "
                    "Return only JSON with keys compliant (boolean), reason (short string), and "
                    "targetBox and cropBox (each null or [left, top, right, bottom] in normalized "
                    "0..1000 coordinates). targetBox must tightly locate the named visual target "
                    "whenever it exists, even when no compliant crop seems possible. "
                    "If the current frame violates the contract but a tight 16:9 crop of existing "
                    "pixels can satisfy it, return that crop. The crop must contain the named "
                    "target, exclude every prohibited person/body/room element, and make the "
                    "target dominate the result. Otherwise return cropBox null. "
                    f"FRAMING CONTRACT: {contract}. SHOT DIRECTION: {request.image_delta or ''}"
                ),
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{encoded}"},
            },
        ]
        payload = {
            "model": self.settings.qwen_vision_model,
            "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        data = self.client.request_json(
            "POST", f"{self.text_base}/chat/completions", json=payload
        )
        raw = self._extract_json(data["choices"][0]["message"]["content"])
        decision = {
            "compliant": bool(raw.get("compliant", False)),
            "reason": str(raw.get("reason", "Framing inspector supplied no reason")),
            "targetBox": raw.get("targetBox"),
            "cropBox": raw.get("cropBox"),
            "family": family,
        }
        if decision["compliant"]:
            decision["cropBox"] = None
            decision["postProcessed"] = False
            return decision
        crop_box = decision["cropBox"]
        if not self._valid_crop_box(crop_box) and family in {
            "close",
            "detail",
            "over-shoulder",
        }:
            crop_box = decision["targetBox"]
            decision["cropBox"] = crop_box
            decision["fallbackCrop"] = True
        if not self._valid_crop_box(crop_box):
            raise ProviderError(
                f"Generated {request.shot_id} violates its {family} framing contract and "
                f"cannot be corrected by cropping: {decision['reason']}",
                code="FRAMING_VALIDATION_FAILED",
            )
        self._apply_normalized_crop(output_path, crop_box)
        decision["postProcessed"] = True
        return decision

    @staticmethod
    def _valid_crop_box(value: Any) -> bool:
        if not isinstance(value, list) or len(value) != 4:
            return False
        if not all(isinstance(item, (int, float)) for item in value):
            return False
        left, top, right, bottom = (float(item) for item in value)
        if not (0 <= left < right <= 1000 and 0 <= top < bottom <= 1000):
            return False
        width, height = right - left, bottom - top
        return width >= 80 and height >= 80

    @staticmethod
    def _apply_normalized_crop(path: Path, box: list[float]) -> None:
        with Image.open(path) as source:
            source.load()
            width, height = source.size
            left, top, right, bottom = box
            pixel_box = QwenCloudProvider._fit_crop_to_aspect(
                (
                    round(left * width / 1000),
                    round(top * height / 1000),
                    round(right * width / 1000),
                    round(bottom * height / 1000),
                ),
                width,
                height,
            )
            cropped = source.crop(pixel_box).resize(
                (width, height), Image.Resampling.LANCZOS
            )
            cropped.save(path, format="PNG")

    @staticmethod
    def _fit_crop_to_aspect(
        box: tuple[int, int, int, int], width: int, height: int
    ) -> tuple[int, int, int, int]:
        left, top, right, bottom = box
        crop_width, crop_height = right - left, bottom - top
        target_ratio = width / height
        center_x, center_y = (left + right) / 2, (top + bottom) / 2
        if crop_width / crop_height < target_ratio:
            crop_width = round(crop_height * target_ratio)
        else:
            crop_height = round(crop_width / target_ratio)
        crop_width, crop_height = min(crop_width, width), min(crop_height, height)
        left = round(center_x - crop_width / 2)
        top = round(center_y - crop_height / 2)
        left = max(0, min(left, width - crop_width))
        top = max(0, min(top, height - crop_height))
        return left, top, left + crop_width, top + crop_height

    def generate_image(
        self, request: ProviderImageRequest, output_path: Path
    ) -> dict[str, Any]:
        payload = self._image_payload(request)
        url = f"{self.native_base}/services/aigc/multimodal-generation/generation"
        try:
            data = self.client.request_json("POST", url, json=payload)
            image_url = data["output"]["choices"][0]["message"]["content"][0][
                "image"
            ]
            source_digest = self.client.download(image_url, output_path)
            framing_check = self._framing_check(request, output_path)
            post_processed = bool(
                framing_check and framing_check.get("postProcessed")
            )
            digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
            return {
                "request_id": data.get("request_id"),
                "remote_url": None if post_processed else image_url,
                "source_remote_url": image_url,
                "local_path": str(output_path),
                "sha256": digest,
                "source_sha256": source_digest,
                "framing_check": framing_check,
                "usage": data.get("usage", {}),
                "request_payload": payload,
            }
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                "Qwen image response did not contain an output image URL",
                code="MALFORMED_PROVIDER_RESPONSE",
            ) from exc
        except RuntimeError as exc:
            raise self._provider_error(exc) from exc

    def generate_video(self, request: ProviderVideoRequest) -> dict[str, Any]:
        payload = self._video_payload(request)
        url = f"{self.native_base}/services/aigc/video-generation/video-synthesis"
        try:
            data = self.client.request_json(
                "POST", url, async_call=True, json=payload
            )
            return {
                "request_id": data.get("request_id"),
                "task_id": data["output"]["task_id"],
                "task_status": data["output"].get("task_status", "PENDING"),
                "request_payload": payload,
            }
        except (KeyError, TypeError) as exc:
            raise ProviderError(
                "Wan video response did not contain a task ID",
                code="MALFORMED_PROVIDER_RESPONSE",
            ) from exc
        except RuntimeError as exc:
            raise self._provider_error(exc) from exc

    def get_video_task(self, task_id: str) -> dict[str, Any]:
        try:
            data = self.client.request_json("GET", f"{self.native_base}/tasks/{task_id}")
            output = data.get("output", {})
            return {
                "task_status": output.get("task_status", "UNKNOWN"),
                "video_url": output.get("video_url"),
                "request_id": data.get("request_id"),
                "usage": data.get("usage", {}),
                "raw": data,
            }
        except RuntimeError as exc:
            raise self._provider_error(exc) from exc

    def download_result(self, source: str, output_path: Path) -> str:
        try:
            return self.client.download(source, output_path)
        except Exception as exc:
            raise ProviderError(
                f"Failed to download generated asset: {exc}",
                code="DOWNLOAD_FAILED",
                retryable=True,
            ) from exc

    def inspect_storyboard(
        self,
        images: list[Path],
        bible: VisualBible,
        plan: ProductionPlan | None = None,
    ) -> ConsistencyReport:
        shot_directions = (
            [
                {
                    "shotId": shot.id,
                    "framing": shot.framing,
                    "subjectPosition": shot.subject_position,
                    "subjectAction": shot.subject_action,
                    "environmentState": shot.environment_state,
                    "propState": shot.prop_state,
                    "imageDelta": shot.image_delta,
                }
                for shot in plan.shots
            ]
            if plan
            else []
        )
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "Inspect these ordered storyboard frames against both the visual bible and "
                    "the matching per-shot directions. Deliberate story progression in prop "
                    "placement, prop text, pose, framing, light, or environment state is not a "
                    "continuity error when the matching shot direction explicitly requests it. "
                    "A shot-specific direction overrides a generic negative-prompt phrase. "
                    "Focus warnings on unintended identity drift, architecture changes, wrong "
                    "window/furniture geometry, or failure to depict the declared shot. Return only "
                    "JSON with approved, warnings, characterConsistencyScore, "
                    "environmentConsistencyScore, paletteConsistencyScore, "
                    "propConsistencyScore, visibleDifferences. Do not request regeneration. "
                    f"Bible: {bible.model_dump_json(by_alias=True)}. "
                    f"Ordered shot directions: {json.dumps(shot_directions)}"
                ),
            }
        ]
        for path in images:
            mime = mimetypes.guess_type(path)[0] or "image/png"
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}
            )
        payload = {
            "model": self.settings.qwen_vision_model,
            "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        try:
            data = self.client.request_json(
                "POST", f"{self.text_base}/chat/completions", json=payload
            )
            raw = self._extract_json(data["choices"][0]["message"]["content"])
            return ConsistencyReport.model_validate(
                self._normalize_consistency_raw(raw)
            )
        except Exception as exc:
            if isinstance(exc, ProviderError):
                raise
            raise ProviderError(
                f"Storyboard consistency inspection failed: {exc}",
                code="VISION_INSPECTION_FAILED",
            ) from exc

    @staticmethod
    def _normalize_consistency_raw(raw: dict[str, Any]) -> dict[str, Any]:
        """Repair common Qwen-VL formatting drift without changing its assessment."""
        normalized = dict(raw)
        score_keys = (
            "characterConsistencyScore",
            "environmentConsistencyScore",
            "paletteConsistencyScore",
            "propConsistencyScore",
        )
        for key in score_keys:
            value = normalized.get(key)
            if isinstance(value, (int, float)):
                value = float(value)
                normalized[key] = max(0.0, min(1.0, value / 100 if value > 1 else value))

        warnings: list[dict[str, Any]] = []
        for item in normalized.get("warnings") or []:
            if isinstance(item, dict):
                candidate = dict(item)
                candidate.setdefault("shotId", "storyboard")
                candidate.setdefault("field", "visualContinuity")
                candidate.setdefault("expected", "matches the locked visual bible")
                candidate.setdefault("found", str(candidate.get("message", candidate)))
                candidate.setdefault("severity", "medium")
                try:
                    warnings.append(
                        ConsistencyWarning.model_validate(candidate).model_dump(
                            by_alias=True
                        )
                    )
                except ValidationError:
                    pass
                continue
            text = str(item)
            match = re.search(r"(?:frame|shot)\s*0*(\d+)", text, re.IGNORECASE)
            shot_id = f"shot-{int(match.group(1)):02d}" if match else "storyboard"
            severity = (
                "high"
                if re.search(r"major|different|extra|missing|violat", text, re.IGNORECASE)
                else "medium"
            )
            warnings.append(
                {
                    "shotId": shot_id,
                    "field": "visualContinuity",
                    "expected": "matches the locked visual bible",
                    "found": text,
                    "severity": severity,
                }
            )
        normalized["warnings"] = warnings

        differences = normalized.get("visibleDifferences") or []
        if isinstance(differences, dict):
            differences = [f"{key}: {value}" for key, value in differences.items()]
        elif not isinstance(differences, list):
            differences = [str(differences)]
        normalized["visibleDifferences"] = [str(item) for item in differences]
        normalized["approved"] = bool(normalized.get("approved", not warnings))
        return normalized

    @staticmethod
    def _provider_error(exc: RuntimeError) -> ProviderError:
        message = str(exc)
        code = "PROVIDER_ERROR"
        match = re.search(r"(?:failed: )?([A-Za-z][A-Za-z0-9_-]+):", message)
        if match:
            code = match.group(1).upper()
        if "401" in message or "InvalidApiKey" in message:
            code = "INVALID_API_KEY"
        return ProviderError(
            message, code=code, retryable=is_retryable_error(code, message)
        )
