from __future__ import annotations

from PIL import Image

from videoforge.config import Settings
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
    assert "70 percent or more" in prompt


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
