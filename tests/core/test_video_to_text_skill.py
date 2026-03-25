from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.media_hooks import MediaHookRegistry
from core.platform.models import MessageType
from extension.skills.builtin.video_to_text.scripts import execute as execute_module
from extension.skills.builtin.video_to_text.scripts import video_text_service as service


@pytest.fixture(autouse=True)
def _clear_whisper_env(monkeypatch):
    for name in (
        "VIDEO_TO_TEXT_WHISPER_ENDPOINT",
        "WHISPER_INFERENCE_URL",
        "VIDEO_TO_TEXT_WHISPER_RESPONSE_FORMAT",
        "VIDEO_TO_TEXT_WHISPER_LANGUAGE",
        "VIDEO_TO_TEXT_WHISPER_TEMPERATURE",
        "VIDEO_TO_TEXT_WHISPER_TEMPERATURE_INC",
        "VIDEO_TO_TEXT_WHISPER_NO_TIMESTAMPS",
    ):
        monkeypatch.delenv(name, raising=False)


def _install_fake_audio_track(
    monkeypatch,
    tmp_path: Path,
    *,
    content: bytes = b"fake-audio-track",
) -> Path:
    audio_path = (tmp_path / "full-audio.mp3").resolve()
    audio_path.write_bytes(content)

    async def _fake_extract_audio_track(_video_path: Path, *, workspace: Path):
        _ = (_video_path, workspace)
        return audio_path, "", "audio/mpeg"

    monkeypatch.setattr(service, "extract_audio_track_file", _fake_extract_audio_track)
    return audio_path


@pytest.mark.asyncio
async def test_video_to_text_skill_registers_video_media_hooks(monkeypatch):
    registry = MediaHookRegistry()
    monkeypatch.setattr(execute_module, "media_hook_registry", registry)
    monkeypatch.setenv("VIDEO_TO_TEXT_WHISPER_ENDPOINT", "http://127.0.0.1:20800/inference")

    execute_module.VideoToTextSkillExtension().register(runtime=object())

    assert MessageType.VIDEO in registry._incoming
    assert MessageType.VIDEO in registry._reply
    assert registry._incoming[MessageType.VIDEO][0].owner == "video_to_text"
    assert registry._reply[MessageType.VIDEO][0].owner == "video_to_text"


@pytest.mark.asyncio
async def test_video_to_text_skill_skips_media_hook_registration_without_whisper_endpoint(
    monkeypatch,
):
    registry = MediaHookRegistry()
    monkeypatch.setattr(execute_module, "media_hook_registry", registry)
    monkeypatch.delenv("VIDEO_TO_TEXT_WHISPER_ENDPOINT", raising=False)
    monkeypatch.delenv("WHISPER_INFERENCE_URL", raising=False)

    execute_module.VideoToTextSkillExtension().register(runtime=object())

    assert MessageType.VIDEO not in registry._incoming
    assert MessageType.VIDEO not in registry._reply


@pytest.mark.asyncio
async def test_execute_video_to_text_returns_disabled_without_whisper_endpoint(
    monkeypatch,
):
    monkeypatch.delenv("VIDEO_TO_TEXT_WHISPER_ENDPOINT", raising=False)
    monkeypatch.delenv("WHISPER_INFERENCE_URL", raising=False)

    result = await service.execute_video_to_text(path="/tmp/demo.mp4")

    assert result["ok"] is False
    assert result["failure_mode"] == "non_recoverable"
    assert "VIDEO_TO_TEXT_WHISPER_ENDPOINT" in result["message"]


@pytest.mark.asyncio
async def test_ensure_video_artifact_for_path_writes_markdown(monkeypatch, tmp_path: Path):
    video_path = (tmp_path / "demo.mp4").resolve()
    video_path.write_bytes(b"video-bytes")
    downloads_dir = (tmp_path / "downloads").resolve()

    async def _fake_probe(_video_path: Path):
        return service.VideoMetadata(
            duration_seconds=42.0,
            width=960,
            height=540,
            fps=25.0,
            video_codec="h264",
            audio_codec="aac",
            mime_type="video/mp4",
        )

    async def _fake_extract_frames(_video_path: Path, *, duration_seconds, workspace: Path):
        _ = (_video_path, duration_seconds)
        frame_path = (workspace / "frame-001.jpg").resolve()
        frame_path.write_bytes(b"frame")
        return [
            service.FrameSample(
                index=1,
                timestamp_seconds=0.0,
                image_path=str(frame_path),
                description="一个人在厨房里切菜",
                visible_text="今日菜单",
            )
        ], []

    async def _fake_enrich_frames(frames):
        return frames, []

    async def _fake_transcribe(
        _video_path: Path,
        *,
        duration_seconds,
        workspace: Path | None = None,
        progress=None,
    ):
        _ = (_video_path, duration_seconds, workspace, progress)
        return [
            service.TranscriptSegment(
                index=1,
                start_seconds=0.0,
                end_seconds=30.0,
                status="transcribed",
                transcript="今天我们来做一道家常菜。",
            )
        ], [], False

    monkeypatch.setattr(service, "probe_video_metadata", _fake_probe)
    monkeypatch.setattr(service, "extract_frame_samples", _fake_extract_frames)
    monkeypatch.setattr(service, "enrich_frames", _fake_enrich_frames)
    monkeypatch.setattr(service, "transcribe_audio_segments", _fake_transcribe)
    monkeypatch.setattr(service, "get_download_dir", lambda: str(downloads_dir))

    result = await service.ensure_video_artifact_for_path(
        video_path,
        file_id="file-1",
        platform="telegram",
        mime_type="video/mp4",
    )

    assert result.ok is True
    assert result.artifact_path
    artifact_path = Path(result.artifact_path)
    assert artifact_path.exists()
    content = artifact_path.read_text(encoding="utf-8")
    assert "# 视频文本工件" in content
    assert str(video_path) in content
    assert "一个人在厨房里切菜" in content
    assert "今日菜单" in content
    assert "今天我们来做一道家常菜。" in content
    assert result.frame_count == 1
    assert result.transcript_segment_count == 1
    assert result.workspace_path
    assert Path(result.workspace_path).exists()
    assert result.progress_log_path
    assert Path(result.progress_log_path).exists()


@pytest.mark.asyncio
async def test_ensure_video_artifact_for_path_returns_failure_on_fatal_audio_error(
    monkeypatch,
    tmp_path: Path,
):
    video_path = (tmp_path / "demo.mp4").resolve()
    video_path.write_bytes(b"video-bytes")
    downloads_dir = (tmp_path / "downloads").resolve()

    async def _fake_probe(_video_path: Path):
        return service.VideoMetadata(
            duration_seconds=42.0,
            width=960,
            height=540,
            fps=25.0,
            video_codec="h264",
            audio_codec="aac",
            mime_type="video/mp4",
        )

    async def _fake_extract_frames(_video_path: Path, *, duration_seconds, workspace: Path):
        _ = (_video_path, duration_seconds)
        frame_path = (workspace / "frame-001.jpg").resolve()
        frame_path.write_bytes(b"frame")
        return [], []

    async def _fake_enrich_frames(frames):
        return frames, []

    async def _fake_transcribe(
        _video_path: Path,
        *,
        duration_seconds,
        workspace: Path | None = None,
        progress=None,
    ):
        _ = (_video_path, duration_seconds, workspace, progress)
        return [], [
            "audio segmented transcription aborted after fatal backend error",
            "Error code: 500 - {'error': {'message': 'auth_unavailable: no auth available'}}",
            "fatal audio transcription error: Error code: 500 - {'error': {'message': 'auth_unavailable: no auth available'}}",
        ], True

    monkeypatch.setattr(service, "probe_video_metadata", _fake_probe)
    monkeypatch.setattr(service, "extract_frame_samples", _fake_extract_frames)
    monkeypatch.setattr(service, "enrich_frames", _fake_enrich_frames)
    monkeypatch.setattr(service, "transcribe_audio_segments", _fake_transcribe)
    monkeypatch.setattr(service, "get_download_dir", lambda: str(downloads_dir))

    result = await service.ensure_video_artifact_for_path(video_path, mime_type="video/mp4")

    assert result.ok is False
    assert result.artifact_path == ""
    assert any("fatal audio transcription error:" in item for item in result.diagnostics)
    assert not list(downloads_dir.rglob("*.md"))


@pytest.mark.asyncio
async def test_process_current_video_message_prefers_cached_artifact(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("VIDEO_TO_TEXT_WHISPER_ENDPOINT", "http://127.0.0.1:20800/inference")
    artifact_path = (tmp_path / "cached_artifact.md").resolve()
    artifact_path.write_text("# 视频文本工件\n", encoding="utf-8")
    source_video_path = (tmp_path / "cached_video.mp4").resolve()
    source_video_path.write_bytes(b"video")

    async def _allow_user(_user_id: str):
        return True

    async def _allow_feature(_ctx, _feature: str):
        return True

    async def _fake_extract_media_input(_ctx, *, expected_types, auto_download):
        _ = (expected_types, auto_download)
        return SimpleNamespace(
            file_id="video-1",
            mime_type="video/mp4",
            file_name="demo.mp4",
            caption="帮我提取完整内容",
        )

    async def _fake_cached_artifact(_platform: str, _file_id: str):
        return {
            "artifact_path": str(artifact_path),
            "source_video_path": str(source_video_path),
            "mime_type": "video/mp4",
            "duration_seconds": 65.0,
            "frame_count": 4,
            "transcript_segment_count": 2,
            "diagnostics": [],
        }

    monkeypatch.setattr(service, "is_user_allowed", _allow_user)
    monkeypatch.setattr(service, "require_feature_access", _allow_feature)
    monkeypatch.setattr(service, "extract_media_input", _fake_extract_media_input)
    monkeypatch.setattr(service, "get_cached_artifact", _fake_cached_artifact)

    replies = []
    actions = []
    ctx = SimpleNamespace(
        message=SimpleNamespace(
            user=SimpleNamespace(id="u-1"),
            platform="telegram",
            file_id="video-1",
            text="",
            caption="帮我提取完整内容",
        ),
        reply=lambda text, **kwargs: _collect_reply(replies, text, kwargs),
        send_chat_action=lambda action, **kwargs: _collect_action(actions, action, kwargs),
    )

    outcome = await service.process_current_video_message(ctx)

    assert outcome.handled is True
    assert "完整提取结果在该 Markdown 文件中" in outcome.forward_text
    assert str(artifact_path) in outcome.forward_text
    assert replies == [("🎬 正在提取视频文本，请稍候...", {})]
    assert actions == [("typing", {})]


@pytest.mark.asyncio
async def test_transcribe_audio_segments_auto_shrinks_before_transcription(
    monkeypatch,
    tmp_path: Path,
):
    video_path = (tmp_path / "demo.mp4").resolve()
    video_path.write_bytes(b"video")
    audio_path = _install_fake_audio_track(monkeypatch, tmp_path)
    transcribe_calls = []

    async def _fake_extract(
        _audio_path: Path,
        *,
        start_seconds: float,
        duration_seconds: float | None,
        mime_type: str = "audio/mpeg",
    ):
        _ = (start_seconds, mime_type)
        assert _audio_path == audio_path
        if float(duration_seconds or 0.0) > 60.0:
            return b"x" * 5_000_000, "", "audio/mpeg"
        return b"x" * 32_000, "", "audio/mpeg"

    async def _fake_transcribe(
        audio_bytes: bytes,
        mime_type: str,
        *,
        transcription_state=None,
    ):
        _ = transcription_state
        transcribe_calls.append((len(audio_bytes), mime_type))
        return "transcribed", "这是转写结果", None

    monkeypatch.setattr(service, "extract_audio_file_segment", _fake_extract)
    monkeypatch.setattr(service, "_transcribe_audio_bytes_internal", _fake_transcribe)
    monkeypatch.setenv("VIDEO_TO_TEXT_AUDIO_SEGMENT_SECONDS", "120")
    monkeypatch.setenv("VIDEO_TO_TEXT_MIN_AUDIO_SEGMENT_SECONDS", "30")
    monkeypatch.setenv("VIDEO_TO_TEXT_AUDIO_MAX_REQUEST_BYTES", "6291456")

    segments, diagnostics, audio_incomplete = await service.transcribe_audio_segments(
        video_path,
        duration_seconds=120.0,
    )

    assert audio_incomplete is False
    assert [round(item.end_seconds - item.start_seconds) for item in segments] == [60, 60]
    assert all(item.status == "transcribed" for item in segments)
    assert all(item.transcript == "这是转写结果" for item in segments)
    assert all(mime_type == "audio/mpeg" for _, mime_type in transcribe_calls)
    assert any("auto-shrunk before transcription" in item for item in diagnostics)


@pytest.mark.asyncio
async def test_transcribe_audio_segments_retries_after_oversized_request_error(
    monkeypatch,
    tmp_path: Path,
):
    video_path = (tmp_path / "demo.mp4").resolve()
    video_path.write_bytes(b"video")
    audio_path = _install_fake_audio_track(monkeypatch, tmp_path)
    transcribe_calls = []

    async def _fake_extract(
        _audio_path: Path,
        *,
        start_seconds: float,
        duration_seconds: float | None,
        mime_type: str = "audio/mpeg",
    ):
        _ = (start_seconds, mime_type)
        assert _audio_path == audio_path
        if float(duration_seconds or 0.0) > 60.0:
            return b"x" * 96_000, "", "audio/mpeg"
        return b"x" * 32_000, "", "audio/mpeg"

    async def _fake_transcribe(
        audio_bytes: bytes,
        mime_type: str,
        *,
        transcription_state=None,
    ):
        _ = transcription_state
        transcribe_calls.append((len(audio_bytes), mime_type))
        if len(audio_bytes) > 64_000:
            return (
                "failed",
                "Error code: 400 - {'error': {'message': 'Exceeded limit on max bytes to request body : 6291456'}}",
                None,
            )
        return "transcribed", "这是转写结果", None

    monkeypatch.setattr(service, "extract_audio_file_segment", _fake_extract)
    monkeypatch.setattr(service, "_transcribe_audio_bytes_internal", _fake_transcribe)
    monkeypatch.setenv("VIDEO_TO_TEXT_AUDIO_SEGMENT_SECONDS", "120")
    monkeypatch.setenv("VIDEO_TO_TEXT_MIN_AUDIO_SEGMENT_SECONDS", "30")
    monkeypatch.setenv("VIDEO_TO_TEXT_AUDIO_MAX_REQUEST_BYTES", "99999999")

    segments, diagnostics, audio_incomplete = await service.transcribe_audio_segments(
        video_path,
        duration_seconds=120.0,
    )

    assert audio_incomplete is False
    assert [round(item.end_seconds - item.start_seconds) for item in segments] == [60, 60]
    assert all(item.status == "transcribed" for item in segments)
    assert all(mime_type == "audio/mpeg" for _, mime_type in transcribe_calls)
    assert any("auto-shrunk after oversized request" in item for item in diagnostics)


@pytest.mark.asyncio
async def test_transcribe_audio_segments_extracts_full_audio_track_once(
    monkeypatch,
    tmp_path: Path,
):
    video_path = (tmp_path / "demo.mp4").resolve()
    video_path.write_bytes(b"video")
    track_calls = []
    segment_sources = []

    async def _fake_extract_track(_video_path: Path, *, workspace: Path):
        track_calls.append((_video_path, workspace))
        audio_path = (workspace / "audio" / "full-audio.mp3").resolve()
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(b"audio-track")
        return audio_path, "", "audio/mpeg"

    async def _fake_extract_segment(
        _audio_path: Path,
        *,
        start_seconds: float,
        duration_seconds: float | None,
        mime_type: str = "audio/mpeg",
    ):
        _ = (start_seconds, duration_seconds, mime_type)
        segment_sources.append(_audio_path)
        return b"audio", "", "audio/mpeg"

    async def _fake_transcribe_audio(
        _audio_bytes: bytes,
        _mime_type: str,
        *,
        transcription_state=None,
    ):
        _ = transcription_state
        return "transcribed", "内容", None

    monkeypatch.setattr(service, "extract_audio_track_file", _fake_extract_track)
    monkeypatch.setattr(service, "extract_audio_file_segment", _fake_extract_segment)
    monkeypatch.setattr(service, "_transcribe_audio_bytes_internal", _fake_transcribe_audio)
    monkeypatch.setattr(
        service,
        "_available_audio_transcription_targets",
        lambda: [("proxy/gpt-5.4", object())],
    )

    segments, diagnostics, audio_incomplete = await service.transcribe_audio_segments(
        video_path,
        duration_seconds=20.0,
        workspace=tmp_path,
    )

    assert audio_incomplete is False
    assert len(track_calls) == 1
    assert len(segments) == 1
    assert segment_sources
    assert all(path == segment_sources[0] for path in segment_sources)
    assert any("audio track extracted:" in item for item in diagnostics)


@pytest.mark.asyncio
async def test_transcribe_audio_segments_prefers_full_audio_for_whisper_http(
    monkeypatch,
    tmp_path: Path,
):
    video_path = (tmp_path / "demo.mp4").resolve()
    video_path.write_bytes(b"video")
    audio_path = _install_fake_audio_track(monkeypatch, tmp_path, content=b"full-audio-track")
    transcribe_calls: list[tuple[int, str]] = []

    async def _fake_probe(*_args, **_kwargs):
        return True, ["whisper http endpoint configured: http://127.0.0.1:20800/inference"]

    async def _fake_transcribe_audio(
        audio_bytes: bytes,
        mime_type: str,
        *,
        transcription_state=None,
    ):
        _ = transcription_state
        transcribe_calls.append((len(audio_bytes), mime_type))
        return "transcribed", "整段 Whisper 转写结果", None

    async def _unexpected_extract_segment(*_args, **_kwargs):
        raise AssertionError("segmented extraction should not run when full-audio whisper succeeds")

    monkeypatch.setenv("VIDEO_TO_TEXT_WHISPER_ENDPOINT", "http://127.0.0.1:20800/inference")
    monkeypatch.setattr(service, "_probe_audio_transcription_mode", _fake_probe)
    monkeypatch.setattr(service, "_transcribe_audio_bytes_internal", _fake_transcribe_audio)
    monkeypatch.setattr(service, "extract_audio_file_segment", _unexpected_extract_segment)

    segments, diagnostics, audio_incomplete = await service.transcribe_audio_segments(
        video_path,
        duration_seconds=20.0,
        workspace=tmp_path,
    )

    assert audio_incomplete is False
    assert len(segments) == 1
    assert segments[0].status == "transcribed"
    assert segments[0].transcript == "整段 Whisper 转写结果"
    assert transcribe_calls == [(audio_path.stat().st_size, "audio/mpeg")]
    assert any("whisper full-audio mode enabled" in item for item in diagnostics)
    assert any("full audio transcription completed without segmentation" in item for item in diagnostics)
    transcript_files = sorted((tmp_path / "audio" / "transcripts").glob("*.txt"))
    segment_audio_files = sorted((tmp_path / "audio" / "segments").glob("*.mp3"))
    assert len(transcript_files) == 1
    assert len(segment_audio_files) == 1
    assert "整段 Whisper 转写结果" in transcript_files[0].read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_transcribe_audio_segments_stops_without_video_fallback_when_audio_modality_unsupported(
    monkeypatch,
    tmp_path: Path,
):
    video_path = (tmp_path / "demo.mp4").resolve()
    video_path.write_bytes(b"video")
    audio_path = _install_fake_audio_track(monkeypatch, tmp_path)

    async def _fake_extract_audio(
        _audio_path: Path,
        *,
        start_seconds: float,
        duration_seconds: float | None,
        mime_type: str = "audio/mpeg",
    ):
        _ = (start_seconds, duration_seconds, mime_type)
        assert _audio_path == audio_path
        return b"audio", "", "audio/mpeg"

    async def _fake_transcribe_audio(
        _audio_bytes: bytes,
        _mime_type: str,
        *,
        transcription_state=None,
    ):
        _ = transcription_state
        return (
            "unsupported_modality",
            "Error code: 400 - {'error': {'message': \"Invalid value: file. Supported values are: 'text','image_url','video_url' and 'video'.\"}}",
            None,
        )

    monkeypatch.setattr(service, "extract_audio_file_segment", _fake_extract_audio)
    monkeypatch.setattr(service, "_transcribe_audio_bytes_internal", _fake_transcribe_audio)
    monkeypatch.setattr(
        service,
        "_available_audio_transcription_targets",
        lambda: [("proxy/gemini-3.1-flash-lite", object())],
    )

    segments, diagnostics, audio_incomplete = await service.transcribe_audio_segments(
        video_path,
        duration_seconds=20.0,
    )

    assert audio_incomplete is True
    assert segments == []
    assert any("audio input unsupported on current backend, video fallback disabled" in item for item in diagnostics)
    assert any("fatal audio transcription error:" in item for item in diagnostics)
    assert not any("video fallback active" in item for item in diagnostics)


@pytest.mark.asyncio
async def test_transcribe_audio_segments_aborts_after_first_fatal_backend_error(
    monkeypatch,
    tmp_path: Path,
):
    video_path = (tmp_path / "demo.mp4").resolve()
    video_path.write_bytes(b"video")
    audio_path = _install_fake_audio_track(monkeypatch, tmp_path)
    transcribe_calls = []

    async def _fake_extract_audio(
        _audio_path: Path,
        *,
        start_seconds: float,
        duration_seconds: float | None,
        mime_type: str = "audio/mpeg",
    ):
        _ = (start_seconds, duration_seconds, mime_type)
        assert _audio_path == audio_path
        return b"audio", "", "audio/mpeg"

    async def _fake_transcribe_audio(
        _audio_bytes: bytes,
        _mime_type: str,
        *,
        transcription_state=None,
    ):
        _ = transcription_state
        transcribe_calls.append("called")
        return (
            "failed",
            "Error code: 500 - {'error': {'message': 'auth_unavailable: no auth available', 'type': 'server_error', 'code': 'internal_server_error'}}",
            None,
        )

    monkeypatch.setattr(service, "extract_audio_file_segment", _fake_extract_audio)
    monkeypatch.setattr(service, "_transcribe_audio_bytes_internal", _fake_transcribe_audio)
    monkeypatch.setattr(
        service,
        "_available_audio_transcription_targets",
        lambda: [("proxy/qwen3-vl-flash", object())],
    )

    segments, diagnostics, audio_incomplete = await service.transcribe_audio_segments(
        video_path,
        duration_seconds=600.0,
    )

    assert audio_incomplete is True
    assert len(transcribe_calls) == 1
    assert segments == []
    assert any("audio probe failed with fatal backend error" in item for item in diagnostics)
    assert any("fatal audio transcription error:" in item for item in diagnostics)


@pytest.mark.asyncio
async def test_transcribe_audio_bytes_prefers_structured_no_audio_over_refusal_text(
    monkeypatch,
):
    async def _fake_generate_text(**_kwargs):
        return (
            "I don't have the capability to access or process audio files. "
            'However, here is a fallback payload: {"status":"no_audio","transcript":"Please provide the audio content for transcription."}'
        )

    monkeypatch.setattr(service, "generate_text", _fake_generate_text)
    monkeypatch.setattr(
        service,
        "_available_audio_transcription_targets",
        lambda: [("proxy/gemini-3.1-flash-lite", object())],
    )

    status, detail = await service.transcribe_audio_bytes(b"audio", "audio/mpeg")

    assert status == "no_audio"
    assert detail == ""


@pytest.mark.asyncio
async def test_transcribe_audio_bytes_rejects_placeholder_transcript(
    monkeypatch,
):
    async def _fake_generate_text(**_kwargs):
        return '{"status":"transcribed","transcript":"..."}'

    monkeypatch.setattr(service, "generate_text", _fake_generate_text)
    monkeypatch.setattr(
        service,
        "_available_audio_transcription_targets",
        lambda: [("proxy/gpt-5.4", object())],
    )
    monkeypatch.setattr(service, "_candidate_audio_part_styles", lambda: ["input_audio"])

    status, detail = await service.transcribe_audio_bytes(b"audio", "audio/mpeg")

    assert status == "empty"
    assert detail == ""


@pytest.mark.asyncio
async def test_transcribe_audio_bytes_uses_voice_capable_candidate_model(
    monkeypatch,
):
    called = {}

    async def _fake_generate_text(**kwargs):
        called["model"] = kwargs["model"]
        return '{"status":"transcribed","transcript":"你好"}'

    def _fake_get_candidates(
        input_type: str = "text",
        pool_type: str = "primary",
        *,
        preferred_model: str | None = None,
        include_failed: bool = False,
    ):
        _ = (preferred_model, include_failed)
        if input_type != "voice":
            return []
        if pool_type == "voice":
            return ["proxy/qwen3-vl-flash", "proxy/gpt-5.4"]
        if pool_type == "routing":
            return ["proxy/gemini-3.1-flash-lite"]
        return []

    def _fake_get_client(model_key: str, *, is_async: bool = False):
        assert is_async is True
        called.setdefault("client_models", []).append(model_key)
        if model_key == "proxy/qwen3-vl-flash":
            return object()
        return None

    monkeypatch.setattr(service, "generate_text", _fake_generate_text)
    monkeypatch.setattr(service, "get_model_candidates_for_input", _fake_get_candidates)
    monkeypatch.setattr(service, "get_client_for_model", _fake_get_client)
    monkeypatch.setattr(service, "get_voice_model", lambda: "proxy/qwen3-vl-flash")

    status, detail = await service.transcribe_audio_bytes(b"audio", "audio/mpeg")

    assert status == "transcribed"
    assert detail == "你好"
    assert called["model"] == "proxy/qwen3-vl-flash"
    assert called["client_models"][0] == "proxy/qwen3-vl-flash"
    assert "proxy/gpt-5.4" in called["client_models"]


@pytest.mark.asyncio
async def test_transcribe_audio_bytes_falls_back_to_next_supported_model(
    monkeypatch,
):
    attempted_models = []

    async def _fake_generate_text(**kwargs):
        attempted_models.append(kwargs["model"])
        if kwargs["model"] == "proxy/qwen3-vl-flash":
            raise RuntimeError(
                "Error code: 400 - {'error': {'message': \"Invalid value: file. Supported values are: "
                "'text','image_url','video_url' and 'video'.\", 'code': 'invalid_value'}}"
            )
        return '{"status":"transcribed","transcript":"来自 gpt-5.4 的转写"}'

    monkeypatch.setattr(service, "generate_text", _fake_generate_text)
    monkeypatch.setattr(
        service,
        "_available_audio_transcription_targets",
        lambda: [
            ("proxy/qwen3-vl-flash", object()),
            ("proxy/gpt-5.4", object()),
        ],
    )
    monkeypatch.setattr(service, "_candidate_audio_part_styles", lambda: ["file"])

    status, detail = await service.transcribe_audio_bytes(b"audio", "audio/mpeg")

    assert status == "transcribed"
    assert detail == "来自 gpt-5.4 的转写"
    assert attempted_models[0] == "proxy/qwen3-vl-flash"
    assert attempted_models[-1] == "proxy/gpt-5.4"
    assert "proxy/gpt-5.4" in attempted_models


@pytest.mark.asyncio
async def test_transcribe_audio_bytes_falls_back_to_next_model_after_backend_failure(
    monkeypatch,
):
    attempted_models = []

    async def _fake_generate_text(**kwargs):
        attempted_models.append(kwargs["model"])
        if kwargs["model"] == "proxy/qwen3-vl-flash":
            raise RuntimeError(
                "Error code: 429 - {'error': {'code': 'model_cooldown', 'message': "
                "'All credentials for model qwen3-vl-flash are cooling down'}}"
            )
        return '{"status":"transcribed","transcript":"来自第二个模型"}'

    monkeypatch.setattr(service, "generate_text", _fake_generate_text)
    monkeypatch.setattr(
        service,
        "_available_audio_transcription_targets",
        lambda: [
            ("proxy/qwen3-vl-flash", object()),
            ("proxy/gpt-5.4", object()),
        ],
    )
    monkeypatch.setattr(service, "_candidate_audio_part_styles", lambda: ["input_audio"])

    status, detail = await service.transcribe_audio_bytes(b"audio", "audio/mpeg")

    assert status == "transcribed"
    assert detail == "来自第二个模型"
    assert attempted_models[0] == "proxy/qwen3-vl-flash"
    assert attempted_models[-1] == "proxy/gpt-5.4"


@pytest.mark.asyncio
async def test_transcribe_audio_bytes_internal_reuses_locked_strategy(
    monkeypatch,
):
    attempts = []
    state = service.AudioTranscriptionState()

    async def _fake_generate_text(**kwargs):
        model = kwargs["model"]
        config = kwargs.get("config") or {}
        style = str(config.get("audio_part_style") or "")
        attempts.append((model, style))
        if model == "proxy/qwen3-vl-flash":
            raise RuntimeError(
                "Error code: 400 - {'error': {'message': '<400> InternalError.Algo.InvalidParameter: "
                "The provided URL does not appear to be valid. Ensure it is correctly formatted.', "
                "'code': 'invalid_parameter_error'}}"
            )
        if style == "file":
            raise RuntimeError(
                "Error code: 400 - {'error': {'message': \"Invalid 'input[0].content[1].file_data'.\", "
                "'type': 'invalid_request_error', 'param': 'input[0].content[1].file_data', "
                "'code': 'invalid_value'}}"
            )
        return '{"status":"transcribed","transcript":"锁定后的转写"}'

    monkeypatch.setattr(service, "generate_text", _fake_generate_text)
    monkeypatch.setattr(
        service,
        "_available_audio_transcription_targets",
        lambda: [
            ("proxy/qwen3-vl-flash", object()),
            ("proxy/gpt-5.4", object()),
        ],
    )
    monkeypatch.setattr(
        service,
        "_candidate_audio_part_styles",
        lambda: ["file", "input_audio"],
    )

    async def _fake_transcode(*_args):
        return None

    monkeypatch.setattr(service, "_transcode_audio_bytes_to_wav", _fake_transcode)

    status, detail, strategy = await service._transcribe_audio_bytes_internal(
        b"audio",
        "audio/mpeg",
        transcription_state=state,
    )

    assert status == "transcribed"
    assert detail == "锁定后的转写"
    assert strategy is not None
    assert state.locked_strategy is not None
    assert state.locked_strategy.model == "proxy/gpt-5.4"
    assert state.locked_strategy.audio_part_style == "input_audio"

    attempts.clear()
    status, detail, strategy = await service._transcribe_audio_bytes_internal(
        b"audio",
        "audio/mpeg",
        transcription_state=state,
    )

    assert status == "transcribed"
    assert detail == "锁定后的转写"
    assert strategy is not None
    assert attempts == [("proxy/gpt-5.4", "input_audio")]


@pytest.mark.asyncio
async def test_transcribe_audio_bytes_internal_prefers_whisper_http(
    monkeypatch,
):
    posted = {}
    state = service.AudioTranscriptionState()

    class _FakeResponse:
        text = "这是 Whisper 的转写结果"

        def raise_for_status(self):
            return None

    class _FakeAsyncClient:
        def __init__(self, *, timeout):
            posted["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, data=None, files=None):
            posted["url"] = url
            posted["data"] = dict(data or {})
            posted["files"] = files
            return _FakeResponse()

    monkeypatch.setenv("VIDEO_TO_TEXT_WHISPER_ENDPOINT", "http://127.0.0.1:20800/inference")
    monkeypatch.setattr(service.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(
        service,
        "_available_audio_transcription_targets",
        lambda: [("proxy/gpt-5.4", object())],
    )

    async def _unexpected_generate_text(**_kwargs):
        raise AssertionError("llm should not be used")

    monkeypatch.setattr(service, "generate_text", _unexpected_generate_text)

    status, detail, strategy = await service._transcribe_audio_bytes_internal(
        b"mp3-bytes",
        "audio/mpeg",
        transcription_state=state,
    )

    assert status == "transcribed"
    assert detail == "这是 Whisper 的转写结果"
    assert strategy is not None
    assert strategy.model == "whisper_http"
    assert state.locked_strategy is not None
    assert state.locked_strategy.model == "whisper_http"
    assert posted["url"] == "http://127.0.0.1:20800/inference"
    assert posted["data"]["response_format"] == "text"
    assert posted["data"]["language"] == "zh"
    assert posted["data"]["temperature"] == "0.00"
    assert posted["data"]["temperature_inc"] == "0.00"
    assert posted["data"]["no_timestamps"] == "true"
    assert posted["files"]["file"][0].endswith(".mp3")


@pytest.mark.asyncio
async def test_transcribe_audio_segments_supports_whisper_http_without_llm_targets(
    monkeypatch,
    tmp_path: Path,
):
    video_path = (tmp_path / "demo.mp4").resolve()
    video_path.write_bytes(b"video")
    audio_path = _install_fake_audio_track(monkeypatch, tmp_path)
    posted_urls = []

    async def _fake_extract_audio(
        _audio_path: Path,
        *,
        start_seconds: float,
        duration_seconds: float | None,
        mime_type: str = "audio/mpeg",
    ):
        _ = (start_seconds, duration_seconds, mime_type)
        assert _audio_path == audio_path
        return b"audio", "", "audio/mpeg"

    class _FakeResponse:
        text = "这是 Whisper 的分段转写"

        def raise_for_status(self):
            return None

    class _FakeAsyncClient:
        def __init__(self, *, timeout):
            _ = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, data=None, files=None):
            _ = (data, files)
            posted_urls.append(url)
            return _FakeResponse()

    monkeypatch.setenv("VIDEO_TO_TEXT_WHISPER_ENDPOINT", "http://127.0.0.1:20800/inference")
    monkeypatch.setattr(service, "extract_audio_file_segment", _fake_extract_audio)
    monkeypatch.setattr(service.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(service, "_available_audio_transcription_targets", lambda: [])
    monkeypatch.setattr(service, "_resolve_audio_transcription_target", lambda: ("", None, []))

    segments, diagnostics, audio_incomplete = await service.transcribe_audio_segments(
        video_path,
        duration_seconds=20.0,
    )

    assert audio_incomplete is False
    assert len(segments) == 1
    assert segments[0].status == "transcribed"
    assert segments[0].transcript == "这是 Whisper 的分段转写"
    assert posted_urls
    assert any("whisper http endpoint configured:" in item for item in diagnostics)
    assert any("locked audio transcription strategy: model=whisper_http" in item for item in diagnostics)


def test_candidate_audio_part_styles_defaults_to_file_first_for_non_gpt(monkeypatch):
    monkeypatch.delenv("OPENAI_AUDIO_PART_STYLE", raising=False)
    monkeypatch.setattr(service, "get_voice_model", lambda: "proxy/qwen3-vl-flash")

    styles = service._candidate_audio_part_styles()

    assert styles[0] == "file"
    assert styles[:3] == ["file", "input_audio", "input_audio_data_uri"]


def test_candidate_audio_part_styles_prefers_input_audio_for_gpt(monkeypatch):
    monkeypatch.delenv("OPENAI_AUDIO_PART_STYLE", raising=False)
    monkeypatch.setattr(service, "get_voice_model", lambda: "proxy/gpt-5.4")

    styles = service._candidate_audio_part_styles()

    assert styles[0] == "input_audio"
    assert styles[:3] == ["input_audio", "file", "input_audio_data_uri"]


@pytest.mark.asyncio
async def test_transcribe_audio_bytes_retries_transcoded_wav_before_returning_no_audio(
    monkeypatch,
):
    attempted_mimes = []

    async def _fake_generate_text(**kwargs):
        mime_type = kwargs["contents"][0]["parts"][1]["inline_data"]["mime_type"]
        attempted_mimes.append(mime_type)
        if mime_type == "audio/wav":
            return '{"status":"transcribed","transcript":"这是 wav 转写结果"}'
        return '{"status":"no_audio","transcript":""}'

    async def _fake_transcode(_audio_bytes: bytes, _mime_type: str):
        return b"wav-bytes"

    monkeypatch.setattr(service, "generate_text", _fake_generate_text)
    monkeypatch.setattr(
        service,
        "_available_audio_transcription_targets",
        lambda: [("proxy/gpt-5.4", object())],
    )
    monkeypatch.setattr(service, "_transcode_audio_bytes_to_wav", _fake_transcode)
    monkeypatch.setattr(service, "_candidate_audio_part_styles", lambda: ["input_audio"])

    status, detail = await service.transcribe_audio_bytes(b"mp3-bytes", "audio/mpeg")

    assert status == "transcribed"
    assert detail == "这是 wav 转写结果"
    assert attempted_mimes[0] == "audio/wav"


@pytest.mark.asyncio
async def test_transcribe_audio_bytes_falls_back_to_next_style_on_url_parameter_error(
    monkeypatch,
):
    attempted_styles = []

    async def _fake_generate_text(**kwargs):
        config = kwargs.get("config") or {}
        attempted_styles.append(
            (
                str(config.get("audio_part_style") or ""),
                bool(config.get("response_mime_type")),
            )
        )
        if config.get("audio_part_style") == "input_audio":
            raise RuntimeError(
                "Error code: 400 - {'error': {'message': '<400> InternalError.Algo.InvalidParameter: "
                "The provided URL does not appear to be valid. Ensure it is correctly formatted.', "
                "'code': 'invalid_parameter_error'}}"
            )
        return '{"status":"transcribed","transcript":"file style transcript"}'

    monkeypatch.setattr(service, "generate_text", _fake_generate_text)
    monkeypatch.setattr(
        service,
        "_available_audio_transcription_targets",
        lambda: [("proxy/qwen3-vl-flash", object())],
    )
    monkeypatch.setattr(
        service,
        "_candidate_audio_part_styles",
        lambda: ["input_audio", "file"],
    )

    status, detail = await service.transcribe_audio_bytes(b"audio", "audio/mpeg")

    assert status == "transcribed"
    assert detail == "file style transcript"
    assert attempted_styles[:2] == [("input_audio", True), ("file", True)]


@pytest.mark.asyncio
async def test_transcribe_audio_bytes_falls_back_from_file_data_error_to_input_audio(
    monkeypatch,
):
    attempted_styles = []

    async def _fake_generate_text(**kwargs):
        config = kwargs.get("config") or {}
        attempted_styles.append(
            (
                str(config.get("audio_part_style") or ""),
                bool(config.get("response_mime_type")),
            )
        )
        if config.get("audio_part_style") == "file":
            raise RuntimeError(
                "Error code: 400 - {'error': {'message': \"Invalid 'input[0].content[1].file_data'.\", "
                "'type': 'invalid_request_error', 'param': 'input[0].content[1].file_data', "
                "'code': 'invalid_value'}}"
            )
        return '{"status":"transcribed","transcript":"input_audio transcript"}'

    monkeypatch.setattr(service, "generate_text", _fake_generate_text)
    monkeypatch.setattr(
        service,
        "_available_audio_transcription_targets",
        lambda: [("proxy/gpt-5.4", object())],
    )
    monkeypatch.setattr(
        service,
        "_candidate_audio_part_styles",
        lambda: ["file", "input_audio"],
    )

    status, detail = await service.transcribe_audio_bytes(b"audio", "audio/mpeg")

    assert status == "transcribed"
    assert detail == "input_audio transcript"
    assert attempted_styles[:2] == [("file", True), ("input_audio", True)]


@pytest.mark.asyncio
async def test_transcribe_audio_bytes_times_out_fast_on_slow_backend(
    monkeypatch,
):
    async def _slow_generate_text(**_kwargs):
        await asyncio.sleep(0.05)
        return '{"status":"transcribed","transcript":"slow"}'

    monkeypatch.setattr(service, "generate_text", _slow_generate_text)
    monkeypatch.setattr(service, "_audio_request_timeout_seconds", lambda: 0.01)
    monkeypatch.setattr(
        service,
        "_available_audio_transcription_targets",
        lambda: [("proxy/gpt-5.4", object())],
    )
    monkeypatch.setattr(service, "_candidate_audio_part_styles", lambda: ["input_audio"])

    status, detail = await service.transcribe_audio_bytes(b"audio", "audio/mpeg")

    assert status == "failed"
    assert "timed out" in detail


@pytest.mark.asyncio
async def test_transcribe_audio_segments_keeps_audio_path_when_probe_returns_no_audio(
    monkeypatch,
    tmp_path: Path,
):
    video_path = (tmp_path / "demo.mp4").resolve()
    video_path.write_bytes(b"video")
    audio_path = _install_fake_audio_track(monkeypatch, tmp_path)

    async def _fake_extract_audio(
        _audio_path: Path,
        *,
        start_seconds: float,
        duration_seconds: float | None,
        mime_type: str = "audio/mpeg",
    ):
        _ = (start_seconds, duration_seconds, mime_type)
        assert _audio_path == audio_path
        return b"audio", "", "audio/mpeg"

    async def _fake_transcribe_audio(
        _audio_bytes: bytes,
        _mime_type: str,
        *,
        transcription_state=None,
    ):
        _ = transcription_state
        return "no_audio", "", None

    monkeypatch.setattr(service, "extract_audio_file_segment", _fake_extract_audio)
    monkeypatch.setattr(service, "_transcribe_audio_bytes_internal", _fake_transcribe_audio)
    monkeypatch.setattr(
        service,
        "_available_audio_transcription_targets",
        lambda: [("proxy/gemini-3.1-flash-lite", object())],
    )

    segments, diagnostics, audio_incomplete = await service.transcribe_audio_segments(
        video_path,
        duration_seconds=20.0,
    )

    assert audio_incomplete is False
    assert len(segments) == 1
    assert segments[0].status == "no_audio"
    assert segments[0].error == "no_audio"
    assert any("audio transcription model candidates:" in item for item in diagnostics)
    assert any("audio probe returned no_audio, keep audio transcription path" in item for item in diagnostics)
    assert not any("video fallback active" in item for item in diagnostics)


def test_parse_audio_response_payload_extracts_embedded_json():
    raw_text = (
        "I cannot help directly.\n\n"
        '{"status":"no_audio","transcript":"Please provide the audio content for transcription."}'
    )

    status, transcript = service._parse_audio_response_payload(raw_text)

    assert status == "no_audio"
    assert transcript == "Please provide the audio content for transcription."


def test_parse_audio_response_payload_reads_error_payload():
    status, transcript = service._parse_audio_response_payload(
        '{"error":"failed to read audio data"}'
    )

    assert status == "failed"
    assert transcript == "failed to read audio data"


async def _collect_reply(replies, text, kwargs):
    replies.append((text, dict(kwargs)))
    return None


async def _collect_action(actions, action, kwargs):
    actions.append((action, dict(kwargs)))
    return True
