from __future__ import annotations

from PIL import Image

from videoforge.config import Settings
from videoforge.providers.base import ProviderError
from videoforge.providers.qwen_cloud import QwenCloudProvider
from videoforge.schemas import ProjectInput, ProviderImageRequest, ProviderVideoRequest


def test_qwen_provider_constructs_proven_requests_without_calling_api(monkeypatch) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("QWEN_WORKSPACE_ID", "ws-test123")
    monkeypatch.delenv("QWEN_BASE_URL", raising=False)
    provider = QwenCloudProvider(Settings())
    image = provider._image_payload(
        ProviderImageRequest(
            project_id="project-test",
            shot_id="shot-01",
            prompt="LOCKED BIBLE\nSHOT_IMAGE_DELTA: test",
            negative_prompt="text, logo",
            seed=11,
        )
    )
    assert image["model"] == "qwen-image-2.0"
    assert image["parameters"] == {
        "negative_prompt": "text, logo",
        "size": "1920*1080",
        "n": 1,
        "prompt_extend": False,
        "watermark": False,
        "seed": 11,
    }
    video = provider._video_payload(
        ProviderVideoRequest(
            project_id="project-test",
            shot_id="shot-01",
            first_frame_url="https://example.test/frame.png",
            prompt="Slow head turn. Fixed camera.",
            negative_prompt="text, logo",
            seed=22,
            duration_seconds=5,
        )
    )
    assert video["model"] == "wan2.7-i2v"
    assert video["input"]["media"] == [
        {"type": "first_frame", "url": "https://example.test/frame.png"}
    ]
    assert video["parameters"]["prompt_extend"] is False
    assert "frame_rate" not in video["parameters"]


def test_qwen_rate_quota_error_keeps_provider_code_instead_of_url_scheme() -> None:
    wrapped = QwenCloudProvider._provider_error(
        RuntimeError(
            'POST https://workspace.example/api exhausted 6 attempts: HTTP 429: '
            '{"code":"Throttling.RateQuota","message":"Requests rate limit exceeded"}'
        )
    )
    assert isinstance(wrapped, ProviderError)
    assert wrapped.code == "THROTTLING_RATE_QUOTA"
    assert wrapped.retryable


def test_medium_reframe_uses_only_upper_body_from_full_person_target() -> None:
    cropped = QwenCloudProvider._upper_body_crop_box([300, 100, 700, 900])
    assert cropped == [300.0, 100.0, 700.0, 540.0]


def test_reflection_crop_stays_inside_screen_box_at_output_aspect() -> None:
    cropped = QwenCloudProvider._inner_aspect_crop_box([300, 50, 800, 950])
    assert cropped[0] == 300.0
    assert cropped[2] == 800.0
    assert round(cropped[3] - cropped[1], 3) == 500.0


def test_ots_crop_tightly_unites_foreground_and_eyeline_target() -> None:
    cropped = QwenCloudProvider._ots_target_crop_box(
        [350, 120, 560, 700], [650, 80, 950, 620]
    )
    assert cropped == [350.0, 90.0, 950.0, 690.0]


def test_shadow_detail_crop_biases_toward_raised_hand() -> None:
    cropped = QwenCloudProvider._shadow_detail_crop_box([550, 100, 800, 850])
    assert cropped == [550.0, 162.5, 800.0, 412.5]


def test_hand_led_image_payload_adds_anatomy_negative_prompt(monkeypatch) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("QWEN_WORKSPACE_ID", "ws-test123")
    provider = QwenCloudProvider(Settings())
    payload = provider._image_payload(
        ProviderImageRequest(
            project_id="project-test",
            shot_id="shot-02",
            prompt="Medium shot of a hand and pillow.",
            negative_prompt="wide room",
            seed=12,
            framing="Medium close-up",
            framing_target="Elena's left hand and the top pillow",
        )
    )
    assert "extra fingers" in payload["parameters"]["negative_prompt"]
    assert "wrong jewelry" in payload["parameters"]["negative_prompt"]


def test_over_shoulder_payload_forbids_a_second_live_copy(monkeypatch) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("QWEN_WORKSPACE_ID", "ws-test123")
    provider = QwenCloudProvider(Settings())
    payload = provider._image_payload(
        ProviderImageRequest(
            project_id="project-test",
            shot_id="shot-05",
            prompt="Over Elena's shoulder toward the photograph.",
            negative_prompt="wide room",
            seed=13,
            reference_image_url="https://example.test/master.png",
            framing="Over-the-shoulder",
            framing_target="Elena's shoulder and the Polaroid",
        )
    )
    text = payload["input"]["messages"][0]["content"][-1]["text"]
    negative = payload["parameters"]["negative_prompt"]
    assert "Render exactly one live Elena" in text
    assert "second live person" in negative
    assert "malformed hands" in negative


def test_face_up_polaroid_payload_forbids_marks_on_front_border(monkeypatch) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("QWEN_WORKSPACE_ID", "ws-test123")
    provider = QwenCloudProvider(Settings())
    payload = provider._image_payload(
        ProviderImageRequest(
            project_id="project-test",
            shot_id="shot-05",
            prompt=(
                "SHOT_START_STATE: BODY: standing | HANDS: holding print | "
                "PROP: face-up Polaroid at chest height"
            ),
            negative_prompt="wide room",
            seed=14,
            framing="Over-the-shoulder",
            framing_target="Elena's shoulder, hands, and the Polaroid",
        )
    )
    negative = payload["parameters"]["negative_prompt"]
    assert "printed text on the Polaroid's front white border" in negative
    assert negative.index("front white border") < negative.index("wide room")


def test_qwen_plan_normalization_changes_only_technical_fields() -> None:
    raw = {
        "title": "Dynamic order",
        "shots": [
            {
                "id": "wrong",
                "order": 9,
                "framing": "tight close-up",
                "subjectPosition": "wrong position",
                "startState": (
                    "BODY: Elena stands beside the bed | HANDS: Both hands are still | "
                    "PROP: The Polaroid lies on the floor"
                ),
                "endState": (
                    "BODY: Elena kneels beside the bed | HANDS: Right hand reaches down | "
                    "PROP: The Polaroid lies on the floor"
                ),
                "propState": "wrong prop state",
                "durationSeconds": 9,
                "imageSeed": -1,
                "videoSeed": 23,
                "imagePrompt": "",
                "motionPrompt": " ",
            },
            {
                "id": "also-wrong",
                "order": 4,
                "framing": "wide master",
                "durationSeconds": 1,
                "imageSeed": 17,
                "videoSeed": 2**40,
                "startState": (
                    "BODY: mismatched body | HANDS: mismatched hands | "
                    "PROP: mismatched prop"
                ),
            },
        ],
    }
    normalized = QwenCloudProvider._normalize_plan_raw(
        raw,
        "project-normalize-test",
        ProjectInput(
            title="Dynamic order",
            storyPrompt="A close-up opens the story before a wide reveal.",
            targetDurationSeconds=10,
            shotCount=2,
        ),
    )
    assert [shot["framing"] for shot in normalized["shots"]] == [
        "tight close-up",
        "wide master",
    ]
    assert [shot["id"] for shot in normalized["shots"]] == ["shot-01", "shot-02"]
    assert [shot["durationSeconds"] for shot in normalized["shots"]] == [5, 5]
    assert normalized["shots"][0]["imageSeed"] >= 0
    assert (
        normalized["shots"][0]["imageSeed"]
        == normalized["shots"][1]["imageSeed"]
    )
    assert normalized["shots"][0]["videoSeed"] == 23
    assert normalized["shots"][0]["imagePrompt"] == "pending compilation"
    assert normalized["shots"][0]["motionPrompt"] == "pending compilation"
    assert normalized["shots"][0]["subjectPosition"] == "Elena stands beside the bed"
    assert normalized["shots"][0]["propState"] == "The Polaroid lies on the floor"
    assert normalized["shots"][1]["startState"] == normalized["shots"][0]["endState"]
    assert normalized["shots"][1]["subjectPosition"] == "Elena kneels beside the bed"


def test_qwen_revision_identifies_only_named_failing_shots() -> None:
    assert QwenCloudProvider._issue_shot_ids(
        [
            "shot-02 combines multiple actions",
            "shot-04 endState must exactly equal shot-05 startState",
        ]
    ) == {"shot-02", "shot-04", "shot-05"}
    assert QwenCloudProvider._issue_shot_ids(
        ["coverage uses only two framing families"]
    ) == set()


def test_qwen_image_edit_payload_uses_canonical_reference(monkeypatch) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("QWEN_WORKSPACE_ID", "ws-test123")
    monkeypatch.delenv("QWEN_BASE_URL", raising=False)
    provider = QwenCloudProvider(Settings())
    payload = provider._image_payload(
        ProviderImageRequest(
            project_id="project-test",
            shot_id="shot-03",
            prompt="Extreme close-up insert of only the photograph and fingers.",
            negative_prompt="extra windows, full face, full body",
            seed=11,
            reference_shot_id="shot-01",
            reference_image_url="https://example.test/master.png",
        )
    )
    content = payload["input"]["messages"][0]["content"]
    assert payload["model"] == "qwen-image-2.0-pro"
    assert content[0] == {"image": "https://example.test/master.png"}
    assert "canonical continuity reference" in content[1]["text"]
    assert "Extreme close-up insert" in content[1]["text"]


def test_qwen_image_edit_payload_adds_shot_shaped_composition_guide(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("QWEN_WORKSPACE_ID", "ws-test123")
    provider = QwenCloudProvider(Settings())
    reference = tmp_path / "master.png"
    Image.new("RGB", (1920, 1080), "teal").save(reference)
    monkeypatch.setattr(
        provider,
        "_composition_guide",
        lambda request: "data:image/png;base64,composition-guide",
    )
    payload = provider._image_payload(
        ProviderImageRequest(
            project_id="project-test",
            shot_id="shot-03",
            prompt="Insert of the print on the bed.",
            negative_prompt="wide room",
            seed=19,
            reference_image_url="https://example.test/master.png",
            reference_image_path=str(reference),
            framing="Insert/detail",
            framing_target="The Polaroid on the bedsheet",
        )
    )
    content = payload["input"]["messages"][0]["content"]
    assert content[0] == {"image": "https://example.test/master.png"}
    assert content[1] == {"image": "data:image/png;base64,composition-guide"}
    assert "shot-shaped crop" in content[2]["text"]


def test_qwen_reflection_ots_never_instructs_model_to_create_photograph(
    monkeypatch,
) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("QWEN_WORKSPACE_ID", "ws-test123")
    provider = QwenCloudProvider(Settings())
    payload = provider._image_payload(
        ProviderImageRequest(
            project_id="project-test",
            shot_id="shot-04",
            prompt="Over Elena's shoulder toward the cracked television.",
            negative_prompt="duplicate person",
            seed=23,
            reference_image_url="https://example.test/master.png",
            framing="Over-the-shoulder (from behind Elena)",
            framing_target="Elena's reflection in the black TV screen",
        )
    )
    text = payload["input"]["messages"][0]["content"][-1]["text"]
    assert "same optical reflection may appear inside the TV glass" in text
    assert "looking at the photograph she holds" not in text


def test_qwen_late_reflection_retry_uses_actor_free_set_plate(monkeypatch) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("QWEN_WORKSPACE_ID", "ws-test123")
    provider = QwenCloudProvider(Settings())
    monkeypatch.setattr(
        provider,
        "_set_plate_guide",
        lambda request: "data:image/png;base64,actor-free-set",
    )
    payload = provider._image_payload(
        ProviderImageRequest(
            project_id="project-test",
            shot_id="shot-04",
            prompt="Over Elena's shoulder toward the cracked television.",
            negative_prompt="duplicate person",
            seed=29,
            reference_image_url="https://example.test/master.png",
            framing="Over-the-shoulder from behind Elena",
            framing_target="Elena's reflection in the black TV screen",
            continuity_reference_mode="set-plate-composition-reset",
        )
    )
    content = payload["input"]["messages"][0]["content"]
    assert content[0] == {"image": "data:image/png;base64,actor-free-set"}
    assert "actor-free set plate" in content[-1]["text"]


def test_qwen_video_payload_accepts_exact_local_reviewed_frame(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("QWEN_WORKSPACE_ID", "ws-test123")
    provider = QwenCloudProvider(Settings())
    frame = tmp_path / "approved.png"
    Image.new("RGB", (1280, 720), "navy").save(frame)
    payload = provider._video_payload(
        ProviderVideoRequest(
            project_id="project-test",
            shot_id="shot-03",
            first_frame_url=str(frame),
            prompt="Hold the close-up.",
            negative_prompt="wide shot",
            seed=3,
            duration_seconds=5,
        )
    )
    media_url = payload["input"]["media"][0]["url"]
    assert media_url.startswith("data:image/png;base64,")


def test_normalized_crop_preserves_output_size(tmp_path) -> None:
    path = tmp_path / "frame.png"
    Image.new("RGB", (1920, 1080), "black").save(path)
    QwenCloudProvider._apply_normalized_crop(path, [250, 250, 750, 531.25])
    with Image.open(path) as result:
        assert result.size == (1920, 1080)


def test_face_crop_ignores_a_broad_proposed_crop(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("QWEN_WORKSPACE_ID", "ws-test123")
    provider = QwenCloudProvider(Settings())

    class StubClient:
        def __init__(self) -> None:
            self.responses = [
                (
                    '{"compliant":false,"reason":"too wide",'
                    '"targetBox":[300,100,700,900],"cropBox":[0,0,1000,1000]}'
                ),
                (
                    '{"compliant":true,"reason":"face dominates",'
                    '"targetBox":[100,50,900,950],"cropBox":null}'
                ),
            ]

        def request_json(self, *args, **kwargs):
            content = self.responses.pop(0)
            return {"choices": [{"message": {"content": content}}]}

    provider.client = StubClient()
    path = tmp_path / "face-wide.png"
    Image.new("RGB", (1920, 1080), "black").save(path)
    decision = provider._framing_check(
        ProviderImageRequest(
            project_id="project-test",
            shot_id="shot-04",
            prompt="Tight face.",
            negative_prompt="wide room",
            seed=4,
            framing="Close-up (tight on face)",
            framing_target="Elena's face",
        ),
        path,
    )
    assert decision["faceTargetCrop"] is True
    assert decision["cropBox"] == [300, 100, 700, 900]


def test_face_crop_records_geometry_override_when_recheck_hallucinates(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("QWEN_WORKSPACE_ID", "ws-test123")
    provider = QwenCloudProvider(Settings())

    class StubClient:
        def __init__(self) -> None:
            self.responses = [
                (
                    '{"compliant":false,"reason":"too wide",'
                    '"targetBox":[300,100,700,900],"cropBox":null}'
                ),
                (
                    '{"compliant":false,"reason":"incorrectly reports old wide frame",'
                    '"targetBox":[300,100,700,900],"cropBox":null}'
                ),
            ]

        def request_json(self, *args, **kwargs):
            content = self.responses.pop(0)
            return {"choices": [{"message": {"content": content}}]}

    provider.client = StubClient()
    path = tmp_path / "face-hallucination.png"
    Image.new("RGB", (1920, 1080), "black").save(path)
    decision = provider._framing_check(
        ProviderImageRequest(
            project_id="project-test",
            shot_id="shot-04",
            prompt="Tight face.",
            negative_prompt="wide room",
            seed=4,
            framing="Close-up (tight on face)",
            framing_target="Elena's face",
        ),
        path,
    )
    assert decision["cropVerification"]["compliant"] is False
    assert decision["geometryOverride"]["method"] == "exact-face-target-box"


def test_reflection_crop_uses_exact_screen_box_even_if_recheck_is_stale(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("QWEN_WORKSPACE_ID", "ws-test123")
    provider = QwenCloudProvider(Settings())

    class StubClient:
        def __init__(self) -> None:
            self.responses = [
                (
                    '{"compliant":false,"reason":"room visible",'
                    '"targetBox":[350,120,900,850],"cropBox":null}'
                ),
                (
                    '{"compliant":false,"reason":"stale room report",'
                    '"targetBox":[350,120,900,850],"cropBox":null}'
                ),
            ]

        def request_json(self, *args, **kwargs):
            content = self.responses.pop(0)
            return {"choices": [{"message": {"content": content}}]}

    provider.client = StubClient()
    path = tmp_path / "tv-reflection.png"
    Image.new("RGB", (1920, 1080), "black").save(path)
    decision = provider._framing_check(
        ProviderImageRequest(
            project_id="project-test",
            shot_id="shot-06",
            prompt="Tight TV reflection.",
            negative_prompt="room overview",
            seed=6,
            framing="Insert detail",
            framing_target="TV screen reflection with a raised hand",
        ),
        path,
    )
    assert decision["reflectionTargetCrop"] is True
    assert (
        decision["geometryOverride"]["method"]
        == "exact-reflective-surface-target-box"
    )


def test_shadow_crop_uses_exact_shadow_box_when_recheck_is_stale(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("QWEN_WORKSPACE_ID", "ws-test123")
    provider = QwenCloudProvider(Settings())

    class StubClient:
        def __init__(self) -> None:
            self.responses = [
                (
                    '{"compliant":false,"reason":"room visible",'
                    '"targetBox":[550,100,800,850],"foregroundBox":null,"cropBox":null}'
                ),
                '{"shadowBox":[550,100,800,850]}',
                (
                    '{"compliant":false,"reason":"stale room report",'
                    '"targetBox":[100,100,900,900],"foregroundBox":null,"cropBox":null}'
                ),
            ]

        def request_json(self, *args, **kwargs):
            return {"choices": [{"message": {"content": self.responses.pop(0)}}]}

    provider.client = StubClient()
    path = tmp_path / "shadow.png"
    Image.new("RGB", (1920, 1080), "black").save(path)
    decision = provider._framing_check(
        ProviderImageRequest(
            project_id="project-test",
            shot_id="shot-03",
            prompt="Wall shadow only.",
            negative_prompt="room overview",
            seed=3,
            framing="Close-up on wall shadow",
            framing_target="The shadow on the wall",
        ),
        path,
    )
    assert decision["shadowTargetCrop"] is True
    assert decision["geometryOverride"]["method"] == "exact-shadow-target-box"


def test_ots_reflection_crop_uses_foreground_and_target_boxes(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("QWEN_WORKSPACE_ID", "ws-test123")
    provider = QwenCloudProvider(Settings())

    class StubClient:
        def __init__(self) -> None:
            self.responses = [
                (
                    '{"compliant":false,"reason":"too wide",'
                    '"targetBox":[650,100,950,650],'
                    '"foregroundBox":[350,120,580,700],"cropBox":null}'
                ),
                (
                    '{"compliant":false,"reason":"stale wide report",'
                    '"targetBox":[650,100,950,650],'
                    '"foregroundBox":[350,120,580,700],"cropBox":null}'
                ),
            ]

        def request_json(self, *args, **kwargs):
            return {"choices": [{"message": {"content": self.responses.pop(0)}}]}

    provider.client = StubClient()
    path = tmp_path / "ots.png"
    Image.new("RGB", (1920, 1080), "black").save(path)
    decision = provider._framing_check(
        ProviderImageRequest(
            project_id="project-test",
            shot_id="shot-04",
            prompt="One subject and TV reflection.",
            negative_prompt="duplicate person",
            seed=4,
            framing="Over-the-shoulder from behind Elena",
            framing_target="Elena's reflection in the TV screen",
        ),
        path,
    )
    assert decision["otsTargetCrop"] is True
    assert (
        decision["geometryOverride"]["method"]
        == "foreground-and-eyeline-target-box"
    )


def test_provider_image_request_tracks_visual_target_separately_from_body() -> None:
    request = ProviderImageRequest(
        project_id="project-test",
        shot_id="shot-05",
        prompt="Over the shoulder toward the held print.",
        negative_prompt="wide room",
        seed=5,
        framing="Over-the-shoulder",
        subject_position="standing beside the bed",
        framing_target="Elena's shoulder and the Polaroid",
    )
    assert request.subject_position == "standing beside the bed"
    assert request.framing_target == "Elena's shoulder and the Polaroid"


def test_framing_gate_uses_visual_target_and_rechecks_crop(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("QWEN_WORKSPACE_ID", "ws-test123")
    provider = QwenCloudProvider(Settings())

    class StubClient:
        def __init__(self) -> None:
            self.calls = []
            self.responses = [
                {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"compliant":false,"reason":"too wide",'
                                    '"targetBox":[300,300,700,700],'
                                    '"cropBox":null}'
                                )
                            }
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"compliant":true,"reason":"target dominates",'
                                    '"targetBox":[150,120,850,880],"cropBox":null}'
                                )
                            }
                        }
                    ]
                },
            ]

        def request_json(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return self.responses.pop(0)

    provider.client = StubClient()
    path = tmp_path / "frame.png"
    Image.new("RGB", (1920, 1080), "black").save(path)
    request = ProviderImageRequest(
        project_id="project-test",
        shot_id="shot-03",
        prompt="Detail frame.",
        negative_prompt="wide room",
        seed=8,
        framing="Insert/detail",
        subject_position="standing beside the bed",
        framing_target="The Polaroid on the bedsheet",
    )
    decision = provider._framing_check(request, path)
    first_prompt = provider.client.calls[0][1]["json"]["messages"][0]["content"][0]["text"]
    second_prompt = provider.client.calls[1][1]["json"]["messages"][0]["content"][0]["text"]
    assert decision["postProcessed"] is True
    assert decision["targetFallbackCrop"] is True
    assert decision["cropVerification"]["compliant"] is True
    assert "The Polaroid on the bedsheet" in first_prompt
    assert "3.5 by 4.25 inch print" in first_prompt
    assert "nearby camera may make the physical print" in first_prompt
    assert "anatomically plausible" not in first_prompt
    assert "already been cropped once" in second_prompt


def test_face_up_polaroid_gate_requires_a_blank_front_border(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("QWEN_WORKSPACE_ID", "ws-test123")
    provider = QwenCloudProvider(Settings())

    class StubClient:
        def __init__(self) -> None:
            self.call = None

        def request_json(self, *args, **kwargs):
            self.call = (args, kwargs)
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"compliant":true,"reason":"clean border",'
                                '"targetBox":[250,250,750,750],"cropBox":null}'
                            )
                        }
                    }
                ]
            }

    provider.client = StubClient()
    path = tmp_path / "polaroid.png"
    Image.new("RGB", (1920, 1080), "black").save(path)
    provider._framing_check(
        ProviderImageRequest(
            project_id="project-test",
            shot_id="shot-05",
            prompt="PROP: face-up Polaroid held at chest height",
            negative_prompt="wide room",
            seed=5,
            framing="Over-the-shoulder",
            framing_target="Elena's shoulder, both hands, and the Polaroid",
        ),
        path,
    )
    prompt = provider.client.call[1]["json"]["messages"][0]["content"][0]["text"]
    assert "front white border must be blank" in prompt
    assert "Reject any handwriting" in prompt


def test_face_close_gate_requests_a_face_only_target_box(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("QWEN_WORKSPACE_ID", "ws-test123")
    provider = QwenCloudProvider(Settings())

    class StubClient:
        def __init__(self) -> None:
            self.call = None

        def request_json(self, *args, **kwargs):
            self.call = (args, kwargs)
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"compliant":true,"reason":"tight face",'
                                '"targetBox":[300,100,700,900],"cropBox":null}'
                            )
                        }
                    }
                ]
            }

    provider.client = StubClient()
    path = tmp_path / "face.png"
    Image.new("RGB", (1920, 1080), "black").save(path)
    provider._framing_check(
        ProviderImageRequest(
            project_id="project-test",
            shot_id="shot-04",
            prompt="Tight close-up.",
            negative_prompt="wide room",
            seed=4,
            framing="Close-up (tight on face)",
            framing_target="Elena's face",
        ),
        path,
    )
    prompt = provider.client.call[1]["json"]["messages"][0]["content"][0]["text"]
    assert "forehead to chin and cheek to cheek" in prompt
    assert "55 percent or more" in prompt
    assert "one non-descriptive wall texture" in prompt


def test_qwen_consistency_output_normalizes_percent_scores_and_text_warnings() -> None:
    normalized = QwenCloudProvider._normalize_consistency_raw(
        {
            "approved": False,
            "characterConsistencyScore": 82,
            "environmentConsistencyScore": 74,
            "paletteConsistencyScore": 0.86,
            "propConsistencyScore": 68,
            "warnings": ["Frame 2 has an extra window."],
            "visibleDifferences": {"room": "window count changes"},
        }
    )
    assert normalized["characterConsistencyScore"] == 0.82
    assert normalized["paletteConsistencyScore"] == 0.86
    assert normalized["warnings"][0]["shotId"] == "shot-02"
    assert normalized["warnings"][0]["severity"] == "high"
    assert normalized["visibleDifferences"] == ["room: window count changes"]
