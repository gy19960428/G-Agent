import json
from pathlib import Path
from urllib.error import HTTPError

from frontends import voice_input
from frontends.voice_input import build_voice_prompt, is_audio_path, transcribe_audio


def test_is_audio_path_recognizes_im_voice_formats():
    assert is_audio_path("message.ogg")
    assert is_audio_path("message.opus")
    assert is_audio_path("message.silk")
    assert is_audio_path("message.amr")
    assert not is_audio_path("video.mp4")
    assert not is_audio_path("image.png")


def test_unconfigured_asr_falls_back_to_file_prompt(tmp_path: Path):
    voice = tmp_path / "voice.ogg"
    voice.write_bytes(b"not real audio")

    text, error = transcribe_audio(voice, {})
    assert text is None
    assert "ASR not configured" in error

    prompt = build_voice_prompt(voice, {}, source="test")
    assert "[voice: voice.ogg]" in prompt
    assert "[File: source:" in prompt
    assert "ASR not configured" in prompt


def test_missing_audio_file_reports_error(tmp_path: Path):
    missing = tmp_path / "missing.ogg"
    text, error = transcribe_audio(missing, {"asr_base_url": "x", "asr_api_key": "k", "asr_model": "m"})
    assert text is None
    assert "audio file not found" in error


def test_bailian_defaults_and_model_fallback(monkeypatch, tmp_path: Path):
    voice = tmp_path / "voice.wav"
    voice.write_bytes(b"fake wav")
    calls = []

    def fake_urlopen(req, timeout):
        body = req.data.decode("utf-8", errors="ignore")
        calls.append((req.full_url, body, timeout))
        if "model-a" in body:
            raise HTTPError(req.full_url, 429, "quota exceeded", {}, None)
        return _FakeResponse({"text": "fallback text"})

    monkeypatch.setattr(voice_input.urlrequest, "urlopen", fake_urlopen)
    text, error = transcribe_audio(
        voice,
        {
            "asr": {
                "provider": "bailian",
                "api_key": "sk-test",
                "models": ["model-a", "model-b"],
                "language": "zh",
                "rotation": "none",
            }
        },
    )

    assert error is None
    assert text == "fallback text"
    assert calls[0][0] == "https://dashscope.aliyuncs.com/compatible-mode/v1/audio/transcriptions"
    assert "model-a" in calls[0][1]
    assert "model-b" in calls[1][1]


def test_model_round_robin_changes_starting_model(monkeypatch, tmp_path: Path):
    voice = tmp_path / "voice.wav"
    voice.write_bytes(b"fake wav")
    seen = []
    voice_input._MODEL_ROTATION_POS.clear()

    def fake_urlopen(req, timeout):
        body = req.data.decode("utf-8", errors="ignore")
        model = "model-a" if "model-a" in body else "model-b"
        seen.append(model)
        return _FakeResponse({"text": model})

    monkeypatch.setattr(voice_input.urlrequest, "urlopen", fake_urlopen)
    cfg = {"asr_base_url": "https://asr.example/v1", "asr_api_key": "k", "asr_models": ["model-a", "model-b"]}

    assert transcribe_audio(voice, cfg)[0] == "model-a"
    assert transcribe_audio(voice, cfg)[0] == "model-b"
    assert seen == ["model-a", "model-b"]


def test_bailian_native_requires_public_mapping(tmp_path: Path):
    voice = tmp_path / "voice.wav"
    voice.write_bytes(b"fake wav")

    text, error = transcribe_audio(
        voice,
        {"asr": {"provider": "bailian_native", "api_key": "k", "model": "paraformer-v2"}},
    )

    assert text is None
    assert "public_base_url/public_base_path" in error


def test_bailian_native_extracts_transcription(monkeypatch, tmp_path: Path):
    public_root = tmp_path / "public"
    public_root.mkdir()
    voice = public_root / "voice.wav"
    voice.write_bytes(b"fake wav")
    calls = []

    class FakeTranscription:
        @staticmethod
        def call(**kwargs):
            calls.append(kwargs)
            return {
                "status_code": 200,
                "output": {
                    "task_status": "SUCCEEDED",
                    "results": [
                        {"results": [{"transcription_url": "https://example.test/result.json"}]}
                    ],
                },
            }

    class FakeAsrModule:
        Transcription = FakeTranscription

    monkeypatch.setattr(voice_input.importlib, "import_module", lambda name: FakeAsrModule)
    monkeypatch.setattr(
        voice_input.urlrequest,
        "urlopen",
        lambda url, timeout: _FakeResponse({"transcripts": [{"text": "hello world"}]}),
    )

    text, error = transcribe_audio(
        voice,
        {
            "asr": {
                "provider": "bailian_native",
                "api_key": "k",
                "model": "paraformer-v2",
                "public_base_url": "https://audio.example.test/base",
                "public_base_path": str(public_root),
            }
        },
    )

    assert error is None
    assert text == "hello world"
    assert calls[0]["file_urls"] == ["https://audio.example.test/base/voice.wav"]


def test_bailian_native_accepts_remote_audio_url(monkeypatch):
    calls = []

    class FakeTranscription:
        @staticmethod
        def call(**kwargs):
            calls.append(kwargs)
            return {
                "status_code": 200,
                "output": {
                    "task_status": "SUCCEEDED",
                    "results": [
                        {"results": [{"transcription_url": "https://example.test/result.json"}]}
                    ],
                },
            }

    class FakeAsrModule:
        Transcription = FakeTranscription

    monkeypatch.setattr(voice_input.importlib, "import_module", lambda name: FakeAsrModule)
    monkeypatch.setattr(
        voice_input.urlrequest,
        "urlopen",
        lambda url, timeout: _FakeResponse({"transcripts": [{"text": "remote ok"}]}),
    )

    text, error = transcribe_audio(
        "https://audio.example.test/base/voice.wav",
        {"asr": {"provider": "bailian_native", "api_key": "k", "model": "paraformer-v2"}},
    )

    assert error is None
    assert text == "remote ok"
    assert calls[0]["file_urls"] == ["https://audio.example.test/base/voice.wav"]


def test_bailian_native_uploads_local_audio_to_object_store(monkeypatch, tmp_path: Path):
    voice = tmp_path / "voice.wav"
    voice.write_bytes(b"fake wav")
    dashscope_calls = []
    put_calls = []

    class FakeTranscription:
        @staticmethod
        def call(**kwargs):
            dashscope_calls.append(kwargs)
            return {
                "status_code": 200,
                "output": {
                    "task_status": "SUCCEEDED",
                    "results": [
                        {"results": [{"transcription_url": "https://example.test/result.json"}]}
                    ],
                },
            }

    class FakeAsrModule:
        Transcription = FakeTranscription

    class FakePutResponse:
        status_code = 200
        text = ""

    def fake_put(url, data, headers, timeout):
        put_calls.append((url, data, headers, timeout))
        return FakePutResponse()

    monkeypatch.setattr(voice_input.importlib, "import_module", lambda name: FakeAsrModule)
    monkeypatch.setattr(voice_input.requests, "put", fake_put)
    monkeypatch.setattr(
        voice_input.urlrequest,
        "urlopen",
        lambda url, timeout: _FakeResponse({"transcripts": [{"text": "object store ok"}]}),
    )

    text, error = transcribe_audio(
        voice,
        {
            "asr": {
                "provider": "bailian_native",
                "api_key": "k",
                "model": "paraformer-v2",
                "object_store": {
                    "endpoint": "http://127.0.0.1:9000",
                    "public_endpoint": "https://audio.example.test",
                    "access_key": "ak",
                    "secret_key": "sk",
                    "bucket": "g-agent-asr",
                    "prefix": "asr-test",
                    "region": "us-east-1",
                    "expires": 600,
                },
            }
        },
    )

    assert error is None
    assert text == "object store ok"
    assert put_calls[0][0].startswith("http://127.0.0.1:9000/g-agent-asr/asr-test/")
    assert put_calls[0][1] == b"fake wav"
    assert put_calls[0][2]["Authorization"].startswith("AWS4-HMAC-SHA256 ")
    file_url = dashscope_calls[0]["file_urls"][0]
    assert file_url.startswith("https://audio.example.test/g-agent-asr/asr-test/")
    assert "X-Amz-Signature=" in file_url


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")
