from __future__ import annotations

import base64
import hashlib
import io
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
            if not isinstance(shot.get("imagePrompt"), str) or len(
                shot["imagePrompt"].strip()
            ) < 3:
                shot["imagePrompt"] = "pending compilation"
            if not isinstance(shot.get("motionPrompt"), str) or len(
                shot["motionPrompt"].strip()
            ) < 3:
                shot["motionPrompt"] = "pending compilation"
            seed = shot.get("videoSeed")
            if not isinstance(seed, int) or not 0 <= seed <= 2**31 - 1:
                shot["videoSeed"] = deterministic_seed(project_id, order, "video")
        for index, shot in enumerate(shots):
            if not isinstance(shot, dict):
                continue
            if index > 0 and isinstance(shots[index - 1], dict):
                previous_end = shots[index - 1].get("endState")
                if isinstance(previous_end, str) and previous_end.strip():
                    shot["startState"] = previous_end
            start_state = shot.get("startState")
            if isinstance(start_state, str):
                ledger = re.fullmatch(
                    r"BODY:\s*(?P<body>.+?)\s*\|\s*HANDS:\s*(?P<hands>.+?)\s*"
                    r"\|\s*PROP:\s*(?P<prop>.+?)\s*",
                    start_state.strip(),
                    re.IGNORECASE,
                )
                if ledger:
                    shot["subjectPosition"] = ledger.group("body")
                    shot["propState"] = ledger.group("prop")
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
            "You are VideoForge's practical film director and cinematographer. Think in "
            "screen actions that an actor and an image-to-video model can perform literally, "
            "not in literary or atmospheric prose. "
            "Return only JSON matching the supplied schema. Design one character, one "
            f"environment, and exactly {shot_count} achievable visual shots, with consecutive "
            f"IDs shot-01 through shot-{shot_count:02d}. Use this beat progression: "
            f"{beat_guidance}. For every shot, populate primarySubject, framingReason, "
            "startState, subjectAction, and endState. subjectAction must be one visible, "
            "straightforward physical action in one sentence of at most 18 words: a subject, "
            "one primary gesture and a visible result. At most one 'and' may join two parts of "
            "the same inseparable physical gesture, such as bending down and lifting a pillow. "
            "Never use 'while', 'then', or another connector to chain story actions. Do not describe sound, fabric "
            "rustling, dust, light beams, atmosphere, internal thought, recognition, memory, "
            "micro-expression, focus shifts, or simultaneous secondary motion. Translate "
            "emotion into one readable physical cue such as lowered eyes, a still mouth, or a "
            "tightened grip. Set environmentMotion to exactly 'None.'. Set cameraMotion to "
            "exactly one of: 'Static camera.', 'Slow push-in.', 'Slow pull-back.', "
            "'Slow pan left.', 'Slow pan right.', 'Slow tilt up.', 'Slow tilt down.', "
            "'Slow rise.', or 'Slow lower.'. Use 'Static camera.' by default. Never combine actor and "
            "complex camera choreography. Both startState and endState must use this exact "
            "physical-ledger format: 'BODY: ... | HANDS: ... | PROP: ...'. startState describes "
            "the first frame immediately before the action. endState describes the exact "
            "positions after the action without repeating or narrating subjectAction. Change "
            "only the ledger clause affected by the action; preserve all other physical facts. "
            "subjectPosition must copy startState's BODY clause verbatim. propState must copy "
            "startState's PROP clause verbatim, including when the prop is absent or off-screen. "
            "Prefer tracking the important prop's physical existence even while hidden by writing "
            "'concealed beneath ...' or 'off-screen at ...'. If PROP is 'none', it may become "
            "visible only through an explicit uncovering, exposing, or pull-from-under action. "
            "Never let the prop appear, disappear, turn over, or reveal information between "
            "shots without an explicit subjectAction causing that change. For every adjacent pair, "
            "Never move the prop from one hand to the other unless subjectAction explicitly "
            "names that hand transfer. "
            "copy the previous shot's endState verbatim "
            "into the next shot's startState so physical continuity is explicit. The storyboard "
            "keyframe will render startState, so do not place a reveal in startState that the "
            "shot's action is supposed to create. "
            "Do not include dialogue, crowds, location changes, or action choreography. "
            "Direct the coverage dynamically from the story; never apply a fixed shot order. "
            "The opening may be a wide, close-up, detail, POV, or another motivated frame. "
            "Across the complete sequence use at least four distinct coverage families chosen "
            "from wide/master, medium, close-up, insert/detail, over-the-shoulder, and POV. "
            "Vary framing and subject position deliberately. Choose framing because it shows "
            "the primarySubject and the physical action clearly; state that reason concretely "
            "in framingReason. Make action, eyeline, and prop position advance from one shot to "
            "the next. Establish a clear "
            "screen geography in the visual bible and preserve the 180-degree axis unless a "
            "motivated shot explicitly crosses it. Do not repeat the same seated or standing "
            "portrait composition. Set propState to its exact realistic size, placement, "
            "visibility, and story state for each shot. Make "
            "imageDelta a unique summary of the startState composition only. The server sends "
            "only startState to the image model, so all composition and prop fields must agree "
            "with that first frame rather than the action's end result. "
            "Evidence printed in a photograph cannot develop, emerge, appear, morph, or change "
            "during a shot. Put all evidence physically in the PROP ledger from the beginning, "
            "then reveal it only through uncovering, lifting, rotating, or turning the prop. "
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

    @staticmethod
    def _issue_shot_ids(issues: list[str]) -> set[str]:
        return {
            shot_id
            for issue in issues
            for shot_id in re.findall(r"\bshot-\d{2}\b", issue)
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
            for _revision_attempt in range(5):
                if not issues:
                    break
                targeted_ids = self._issue_shot_ids(issues)
                only_shot_specific = bool(targeted_ids) and all(
                    re.search(r"\bshot-\d{2}\b", issue) for issue in issues
                )
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
                revised_plan = ProductionPlan.model_validate(revised_raw)
                if only_shot_specific:
                    revised_by_id = {shot.id: shot for shot in revised_plan.shots}
                    merged_raw = plan.model_dump(by_alias=True)
                    merged_raw["shots"] = [
                        revised_by_id.get(shot.id, shot).model_dump(by_alias=True)
                        if shot.id in targeted_ids
                        else shot.model_dump(by_alias=True)
                        for shot in plan.shots
                    ]
                    merged_raw = self._normalize_plan_raw(
                        merged_raw, project_id, project
                    )
                    plan = ProductionPlan.model_validate(merged_raw)
                else:
                    plan = revised_plan
                issues = cinematography_issues(plan)
            if issues:
                raise ProviderError(
                    "Qwen's revised plan still lacks cinematographic continuity: "
                    + "; ".join(issues),
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
        issue_shot_ids = self._issue_shot_ids(issues)
        editable_shot_ids = (
            sorted(issue_shot_ids)
            if issue_shot_ids
            and all(re.search(r"\bshot-\d{2}\b", issue) for issue in issues)
            else []
        )
        return {
            "model": self.settings.qwen_text_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a film director revising a storyboard for visual and editorial "
                        "continuity. Return only the complete ProductionPlan JSON matching the "
                        "schema. Resolve every supplied validation issue, but do not impose a "
                        "fixed shot order. When editableShotIds is non-empty, copy every other "
                        "shot verbatim and revise only those named shots. "
                        "Choose coverage and order from the narrative: the film "
                        "may begin wide, close, detail, POV, or otherwise. Preserve the same "
                        "character, location, lighting, screen geography, and 180-degree axis. "
                        "Every cut must advance action, eyeline, information, or prop state. "
                        "For each shot, provide primarySubject, framingReason, startState, one "
                        "visible single-verb subjectAction of no more than 18 words, and endState. "
                        "Use at most one 'and', only for two parts of one coordinated physical "
                        "gesture; never use 'while' or 'then'. Format both states "
                        "exactly as 'BODY: ... | HANDS: ... | PROP: ...'. subjectPosition must "
                        "equal the startState BODY clause, and propState must equal the startState "
                        "PROP clause. Describe positions in endState without repeating subjectAction. Each "
                        "endState must be copied verbatim into the next startState. Remove "
                        "sound, particles, atmosphere, internal thought, focus behavior, and "
                        "secondary motion. environmentMotion must be 'None.'. cameraMotion must "
                        "be 'Static camera.' or one of the allowed single slow moves from the "
                        "original instruction. The image "
                        "keyframe depicts startState before the action, never the reveal created "
                        "by endState. Never introduce or change the prop between ledger states "
                        "without a subjectAction that physically causes it. "
                        "A change from right-hand holding to left-hand holding requires an "
                        "explicit hand-transfer action. "
                        "Track a concealed or off-screen prop explicitly when possible; otherwise "
                        "its appearance requires an explicit uncovering or pull-from-under action. "
                        "Never animate new evidence developing, emerging, appearing, or changing "
                        "inside a photograph; disclose pre-existing evidence with one physical move. "
                        "Bad: 'a new figure emerges in the photo.' Good: the figure is already "
                        "printed in PROP and the subject turns the photo toward camera. Before "
                        "returning JSON, scan every executable field and remove sound, particles, "
                        "focus changes, atmosphere, and self-changing evidence. "
                        "If validation says an action creates no new physical endState, replace "
                        "that action with one simple visible movement and update its endState, "
                        "unless it is deliberately an observational look, stare, or held reaction. "
                        "Set imagePrompt and motionPrompt to placeholders because the server compiles "
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
                            "editableShotIds": editable_shot_ids,
                            "draftPlan": plan.model_dump(by_alias=True),
                            "requiredSchema": ProductionPlan.model_json_schema(by_alias=True),
                        }
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }

    def _image_payload(self, request: ProviderImageRequest) -> dict[str, Any]:
        content: list[dict[str, str]] = []
        prompt = request.prompt
        negative_prompt = request.negative_prompt
        visual_target = request.framing_target or ""
        if re.search(r"\b(hand|hands|finger|fingers|fingertip|fingertips)\b", visual_target, re.IGNORECASE):
            negative_prompt += (
                ", extra fingers, duplicated fingers, fused fingers, malformed hands, "
                "duplicated hands, wrong jewelry"
            )
        if request.reference_image_url:
            content.append({"image": request.reference_image_url})
            composition_guide = self._composition_guide(request)
            if composition_guide:
                content.append({"image": composition_guide})
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
                + (
                    "Image 2 is a shot-shaped crop derived from Image 1. Use Image 2 only to "
                    "set the new camera scale and crop. Keep Image 1 authoritative for identity, "
                    "set geometry, wardrobe, and lighting. The desired prop or pose may be absent "
                    "from both references; create it exactly as the text ledger declares. "
                    if composition_guide
                    else ""
                )
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

    def _composition_guide(self, request: ProviderImageRequest) -> str | None:
        if not request.reference_image_path or not request.framing:
            return None
        family = framing_family(request.framing)
        if family in {"wide", "other"}:
            return None
        path = Path(request.reference_image_path)
        if not path.exists():
            return None
        mime = mimetypes.guess_type(path)[0] or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        target = request.framing_target or request.subject_position or "the named subject"
        payload = {
            "model": self.settings.qwen_vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "You are preparing a composition-reference crop from a wide "
                                "continuity master. Return only JSON with cropBox as either null "
                                "or [left, top, right, bottom] in normalized 0..1000 coordinates. "
                                "Choose a tight 16:9 crop of existing pixels that supplies the "
                                "most useful visible anchor for the requested new shot. The crop "
                                "is a camera-scale guide, not the final frame. If the requested "
                                "object is absent, crop its named supporting surface; for a face, "
                                "crop the same face; for hands, crop the hands and nearby torso; "
                                "for over-the-shoulder coverage, crop the actor's upper torso and "
                                "shoulder area. Avoid returning the full wide frame. "
                                f"REQUESTED FRAMING: {request.framing}. "
                                f"VISUAL TARGET: {target}. "
                                f"SHOT DIRECTION: {request.image_delta or ''}"
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{encoded}"},
                        },
                    ],
                }
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        data = self.client.request_json(
            "POST", f"{self.text_base}/chat/completions", json=payload
        )
        raw = self._extract_json(data["choices"][0]["message"]["content"])
        crop_box = raw.get("cropBox")
        if not self._valid_crop_box(crop_box):
            return None
        with Image.open(path) as source:
            source.load()
            width, height = source.size
            left, top, right, bottom = crop_box
            pixel_box = self._fit_crop_to_aspect(
                (
                    round(left * width / 1000),
                    round(top * height / 1000),
                    round(right * width / 1000),
                    round(bottom * height / 1000),
                ),
                width,
                height,
            )
            crop = source.crop(pixel_box).resize(
                (width, height), Image.Resampling.LANCZOS
            )
            buffer = io.BytesIO()
            crop.save(buffer, format="PNG")
        guide = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{guide}"

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
        target = request.framing_target or request.subject_position
        if not request.framing or not target:
            return None
        family = framing_family(request.framing)
        if family in {"wide", "other"}:
            return None
        decision = self._inspect_framing(
            request, output_path, family=family, target=target, allow_crop=True
        )
        if decision["compliant"]:
            decision["cropBox"] = None
            decision["postProcessed"] = False
            return decision
        crop_box = decision["cropBox"]
        if (
            not self._valid_crop_box(crop_box)
            and family in {"medium", "close", "detail"}
            and self._valid_crop_box(decision["targetBox"])
        ):
            crop_box = decision["targetBox"]
            decision["cropBox"] = crop_box
            decision["targetFallbackCrop"] = True
        if not self._valid_crop_box(crop_box):
            raise ProviderError(
                f"Generated {request.shot_id} violates its {family} framing contract and "
                f"cannot be corrected by cropping: {decision['reason']}",
                code="FRAMING_VALIDATION_FAILED",
            )
        self._apply_normalized_crop(output_path, crop_box)
        verification = self._inspect_framing(
            request, output_path, family=family, target=target, allow_crop=False
        )
        if not verification["compliant"]:
            raise ProviderError(
                f"Generated {request.shot_id} still violates its {family} framing contract "
                f"after the proposed crop: {verification['reason']}",
                code="FRAMING_VALIDATION_FAILED",
            )
        decision["postProcessed"] = True
        decision["cropVerification"] = verification
        return decision

    def reframe_existing_image(
        self, request: ProviderImageRequest, output_path: Path
    ) -> dict[str, Any]:
        framing_check = self._framing_check(request, output_path)
        return {
            "framing_check": framing_check,
            "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        }

    def _inspect_framing(
        self,
        request: ProviderImageRequest,
        output_path: Path,
        *,
        family: str,
        target: str,
        allow_crop: bool,
    ) -> dict[str, Any]:
        mime = mimetypes.guess_type(output_path)[0] or "image/png"
        encoded = base64.b64encode(output_path.read_bytes()).decode("ascii")
        contract = framing_visibility_contract(request.framing or "", target)
        prop_scale_rule = (
            " If the named target is a Polaroid, photo, or photograph, it must be exactly one "
            "physical 3.5 by 4.25 inch print with correct perspective and contact with the "
            "declared hand or surface. "
            + (
                "Because this is a detail shot, the nearby camera may make the physical print "
                "fill much of the screen. Judge its reality from visible card edges, perspective, "
                "contact shadow, and supporting-surface texture; do not reject it merely for its "
                "apparent screen size when no hand provides scale. "
                if family == "detail"
                else "When an adult hand is visible, its width may not exceed two palm widths. "
            )
            + "Reject a floating graphic, inset picture, duplicated print, body-sized print, or "
            "full-frame overlay even when the subject inside the print is correct. A face or body "
            "printed inside the physical card is explicitly allowed and must not be mistaken for "
            "a live person outside the card. A realistic tilt and a narrow area of supporting "
            "surface are allowed."
            if re.search(r"\b(polaroid|photo|photograph)\b", target, re.IGNORECASE)
            else ""
        )
        hand_anatomy_rule = (
            " The declared live hand must be anatomically plausible, with five digits total "
            "unless a digit is naturally occluded. Reject extra, duplicated, stacked, fused, "
            "forked, or malformed fingers; duplicated hands; impossible joints; and jewelry on "
            "the wrong finger. Elena's only jewelry is one thin silver ring on her left ring "
            "finger. Printed hands inside a physical photograph are prop content and are not "
            "counted as live hands."
            if re.search(
                r"\b(hand|hands|finger|fingers|fingertip|fingertips)\b",
                target,
                re.IGNORECASE,
            )
            else ""
        )
        face_close_rule = (
            " For a face target, targetBox must contain only the facial oval from forehead to "
            "chin and cheek to cheek; exclude hair volume, neck, shoulders, and torso from the "
            "box. In the final 16:9 close-up, the facial oval should occupy about 55 percent or "
            "more of frame height. Shoulders may touch only the lower edge. Bed, window, and "
            "furniture geography must not remain readable, but one non-descriptive wall texture "
            "may remain as background."
            if family == "close"
            and re.search(r"\b(face|facial|eyes|expression)\b", target, re.IGNORECASE)
            else ""
        )
        crop_instruction = (
            "If the current frame violates the contract but a tight 16:9 crop of existing "
            "pixels can satisfy every requirement, return that crop. The crop must contain the "
            "entire named target, exclude every prohibited element, and make the target dominate. "
            "For over-the-shoulder coverage, a valid crop must retain both the foreground shoulder "
            "or back and the eyeline target. If the named target is missing, return cropBox null."
            if allow_crop
            else (
                "This image has already been cropped once. Do not propose another crop; return "
                "cropBox null and mark compliant false if any requirement still fails."
            )
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
                    f"{crop_instruction} "
                    f"FRAMING CONTRACT: {contract}.{prop_scale_rule}{hand_anatomy_rule}"
                    f"{face_close_rule} "
                    f"SHOT DIRECTION: {request.image_delta or ''}"
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
        url = f"{self.native_base}/services/aigc/multimodal-generation/generation"
        try:
            payload = self._image_payload(request)
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
