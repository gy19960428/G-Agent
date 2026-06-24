import datetime as dt
import hashlib
import hmac
import importlib
import json
import mimetypes
import os
import shutil
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse

import requests


_AUDIO_EXTS = {
    ".amr",
    ".flac",
    ".m4a",
    ".mp3",
    ".mpeg",
    ".mpga",
    ".oga",
    ".ogg",
    ".opus",
    ".silk",
    ".wav",
    ".webm",
}
_CONVERT_EXTS = {".amr", ".oga", ".ogg", ".opus", ".silk"}
_MODEL_ROTATION_LOCK = threading.Lock()
_MODEL_ROTATION_POS = {}


class VoiceInputError(Exception):
    pass


def is_audio_path(path):
    return Path(str(path or "")).suffix.lower() in _AUDIO_EXTS


def transcribe_audio(path, config=None, *, source="im"):
    """Transcribe audio with the configured ASR provider."""
    raw_path = str(path)
    is_remote_url = urlparse(raw_path).scheme in {"http", "https"}
    audio_path = Path(path)
    if not is_remote_url and not audio_path.is_file():
        return None, f"audio file not found: {audio_path}"
    cfg = _normalize_config(config)
    candidates = _candidate_configs(cfg)
    missing = ["api_key"] if not cfg.get("api_key") else []
    if not _is_bailian_native(cfg) and not cfg.get("base_url"):
        missing.append("base_url")
    if not candidates:
        missing.append("model")
    if missing:
        return None, f"ASR not configured: missing {', '.join(missing)}"
    send_path, cleanup = (raw_path, None) if is_remote_url else _prepare_audio(audio_path)
    try:
        errors = []
        for item in _ordered_candidate_configs(candidates, cfg):
            try:
                if _is_bailian_native(item):
                    return _call_bailian_native_transcription(send_path, item), None
                if is_remote_url:
                    raise VoiceInputError("remote audio URLs require bailian_native provider")
                return _call_openai_transcription(send_path, item, source=source), None
            except VoiceInputError as exc:
                errors.append(f"{item.get('model')}: {exc}")
        return None, "all ASR models failed: " + " | ".join(errors)
    finally:
        if cleanup:
            try:
                Path(cleanup).unlink(missing_ok=True)
            except Exception:
                pass


def build_voice_prompt(path, config=None, *, source="im"):
    text, error = transcribe_audio(path, config, source=source)
    name = os.path.basename(str(path))
    if text:
        return f"[voice: {name}]\n[语音转写]\n{text}"
    return f"[voice: {name}]\n[File: source: {path}]\n[语音转写失败: {error}]"


def _normalize_config(config):
    cfg = dict(config or {})
    asr = cfg.get("asr") if isinstance(cfg.get("asr"), dict) else {}
    provider = str(asr.get("provider") or cfg.get("asr_provider") or os.environ.get("G_AGENT_ASR_PROVIDER") or "openai").lower()
    base_url = _strip_trailing_slash(
        asr.get("base_url") or cfg.get("asr_base_url") or os.environ.get("G_AGENT_ASR_BASE_URL")
    )
    if not base_url and provider in {"bailian", "dashscope", "aliyun"}:
        base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    object_store = _normalize_object_store(asr.get("object_store") or cfg.get("asr_object_store") or {})
    return {
        "provider": provider,
        "base_url": base_url,
        "api_key": (
            asr.get("api_key")
            or cfg.get("asr_api_key")
            or os.environ.get("G_AGENT_ASR_API_KEY")
            or os.environ.get("DASHSCOPE_API_KEY")
        ),
        "model": asr.get("model") or cfg.get("asr_model") or os.environ.get("G_AGENT_ASR_MODEL"),
        "models": asr.get("models") or cfg.get("asr_models") or _split_env("G_AGENT_ASR_MODELS"),
        "language": asr.get("language") or cfg.get("asr_language") or os.environ.get("G_AGENT_ASR_LANGUAGE"),
        "rotation": asr.get("rotation") or cfg.get("asr_rotation") or os.environ.get("G_AGENT_ASR_ROTATION") or "round_robin",
        "timeout": int(asr.get("timeout") or cfg.get("asr_timeout") or os.environ.get("G_AGENT_ASR_TIMEOUT") or 120),
        "public_base_url": _strip_trailing_slash(
            asr.get("public_base_url")
            or cfg.get("asr_public_base_url")
            or os.environ.get("G_AGENT_ASR_PUBLIC_BASE_URL")
        ),
        "public_base_path": str(
            asr.get("public_base_path")
            or cfg.get("asr_public_base_path")
            or os.environ.get("G_AGENT_ASR_PUBLIC_BASE_PATH")
            or ""
        ).strip(),
        "object_store": object_store,
    }


def _split_env(name):
    value = os.environ.get(name)
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def _normalize_object_store(value):
    store = dict(value or {}) if isinstance(value, dict) else {}
    endpoint = _strip_trailing_slash(
        store.get("endpoint") or os.environ.get("G_AGENT_ASR_OBJECT_STORE_ENDPOINT")
    )
    public_endpoint = _strip_trailing_slash(
        store.get("public_endpoint") or os.environ.get("G_AGENT_ASR_OBJECT_STORE_PUBLIC_ENDPOINT") or endpoint
    )
    return {
        "type": str(store.get("type") or os.environ.get("G_AGENT_ASR_OBJECT_STORE_TYPE") or "").lower(),
        "endpoint": endpoint,
        "public_endpoint": public_endpoint,
        "access_key": store.get("access_key") or os.environ.get("G_AGENT_ASR_OBJECT_STORE_ACCESS_KEY"),
        "secret_key": store.get("secret_key") or os.environ.get("G_AGENT_ASR_OBJECT_STORE_SECRET_KEY"),
        "bucket": store.get("bucket") or os.environ.get("G_AGENT_ASR_OBJECT_STORE_BUCKET"),
        "prefix": str(store.get("prefix") or os.environ.get("G_AGENT_ASR_OBJECT_STORE_PREFIX") or "asr").strip("/"),
        "region": store.get("region") or os.environ.get("G_AGENT_ASR_OBJECT_STORE_REGION") or "us-east-1",
        "expires": int(store.get("expires") or os.environ.get("G_AGENT_ASR_OBJECT_STORE_EXPIRES") or 3600),
    }


def _candidate_configs(cfg):
    models = cfg.get("models") or cfg.get("model")
    if not models:
        return []
    if isinstance(models, (str, bytes)):
        models = [models]
    candidates = []
    for item in models:
        merged = dict(cfg)
        if isinstance(item, dict):
            merged.update(item)
        else:
            merged["model"] = str(item)
        merged.pop("models", None)
        if merged.get("model"):
            candidates.append(merged)
    return candidates


def _ordered_candidate_configs(candidates, cfg):
    if len(candidates) < 2 or str(cfg.get("rotation") or "").lower() not in {"round_robin", "rotate"}:
        return candidates
    key = "|".join([cfg.get("base_url") or "", ",".join(item.get("model") or "" for item in candidates)])
    with _MODEL_ROTATION_LOCK:
        start = _MODEL_ROTATION_POS.get(key, 0) % len(candidates)
        _MODEL_ROTATION_POS[key] = start + 1
    return candidates[start:] + candidates[:start]


def _strip_trailing_slash(value):
    return str(value or "").strip().rstrip("/")


def _is_bailian_native(cfg):
    return str(cfg.get("provider") or "").lower() in {"bailian_native", "dashscope_native", "aliyun_native"}


def _public_audio_url(path, cfg):
    raw = str(path)
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"}:
        return raw
    store = cfg.get("object_store") or {}
    if store.get("endpoint") and store.get("bucket"):
        return _upload_audio_to_object_store(Path(path), store)
    base_url = cfg.get("public_base_url")
    base_path = cfg.get("public_base_path")
    if not base_url or not base_path:
        raise VoiceInputError("bailian native ASR requires an http(s) audio URL, object_store, or public_base_url/public_base_path mapping")
    audio_path = Path(path).resolve()
    root = Path(base_path).resolve()
    try:
        rel = audio_path.relative_to(root)
    except ValueError as exc:
        raise VoiceInputError(f"audio file is outside public_base_path: {root}") from exc
    return base_url + "/" + quote(rel.as_posix())


def _upload_audio_to_object_store(path, store):
    for key in ["endpoint", "public_endpoint", "access_key", "secret_key", "bucket"]:
        if not store.get(key):
            raise VoiceInputError(f"ASR object_store missing required field: {key}")
    bucket = store["bucket"]
    prefix = store.get("prefix") or "asr"
    object_key = f"{prefix}/{dt.datetime.now(dt.UTC):%Y%m%d}/{uuid.uuid4().hex}{path.suffix.lower()}"
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body = path.read_bytes()
    upload_url = _s3_object_url(store["endpoint"], bucket, object_key)
    headers = _s3_signed_headers(
        "PUT",
        upload_url,
        store,
        payload_hash=hashlib.sha256(body).hexdigest(),
        extra_headers={"content-type": content_type},
    )
    resp = requests.put(upload_url, data=body, headers=headers, timeout=store.get("timeout") or 60)
    if resp.status_code >= 300:
        raise VoiceInputError(f"ASR object_store upload failed HTTP {resp.status_code}: {resp.text[:300]}")
    public_url = _s3_object_url(store["public_endpoint"], bucket, object_key)
    return _s3_presigned_get_url(public_url, store)


def _s3_object_url(endpoint, bucket, object_key):
    return f"{_strip_trailing_slash(endpoint)}/{quote(bucket, safe='')}/{quote(object_key, safe='/')}"


def _s3_signature_key(secret_key, date_stamp, region, service="s3"):
    key = ("AWS4" + secret_key).encode("utf-8")
    for part in [date_stamp, region, service, "aws4_request"]:
        key = hmac.new(key, part.encode("utf-8"), hashlib.sha256).digest()
    return key


def _s3_signed_headers(method, url, store, *, payload_hash, extra_headers=None):
    parsed = urlparse(url)
    now = dt.datetime.now(dt.UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    headers = {
        "host": parsed.netloc,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    for key, value in (extra_headers or {}).items():
        headers[key.lower()] = str(value)
    signed_headers = ";".join(sorted(headers))
    canonical_headers = "".join(f"{key}:{headers[key].strip()}\n" for key in sorted(headers))
    canonical_request = "\n".join([
        method.upper(),
        parsed.path or "/",
        parsed.query,
        canonical_headers,
        signed_headers,
        payload_hash,
    ])
    region = store.get("region") or "us-east-1"
    credential_scope = f"{date_stamp}/{region}/s3/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])
    signature = hmac.new(
        _s3_signature_key(store["secret_key"], date_stamp, region),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    auth = (
        "AWS4-HMAC-SHA256 "
        f"Credential={store['access_key']}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    result = {key: value for key, value in headers.items() if key != "host"}
    result["Authorization"] = auth
    return result


def _s3_presigned_get_url(url, store):
    parsed = urlparse(url)
    now = dt.datetime.now(dt.UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    region = store.get("region") or "us-east-1"
    credential_scope = f"{date_stamp}/{region}/s3/aws4_request"
    params = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{store['access_key']}/{credential_scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(int(store.get("expires") or 3600)),
        "X-Amz-SignedHeaders": "host",
    }
    canonical_query = urlencode(sorted(params.items()), quote_via=quote, safe="")
    canonical_headers = f"host:{parsed.netloc}\n"
    canonical_request = "\n".join([
        "GET",
        parsed.path or "/",
        canonical_query,
        canonical_headers,
        "host",
        "UNSIGNED-PAYLOAD",
    ])
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])
    signature = hmac.new(
        _s3_signature_key(store["secret_key"], date_stamp, region),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{url}?{canonical_query}&X-Amz-Signature={signature}"


def _call_bailian_native_transcription(path, cfg):
    file_url = _public_audio_url(path, cfg)
    try:
        transcription = importlib.import_module("dashscope.audio.asr").Transcription
    except Exception as exc:
        raise VoiceInputError("dashscope package is required for bailian_native ASR: pip install dashscope") from exc

    try:
        resp = transcription.call(
            model=cfg["model"],
            file_urls=[file_url],
            api_key=cfg.get("api_key"),
            language_hints=[cfg.get("language") or "zh"],
        )
    except Exception as exc:
        raise VoiceInputError(f"bailian native ASR request failed: {type(exc).__name__}: {exc}") from exc
    data = _dashscope_response_dict(resp)
    output = data.get("output") or {}
    status = data.get("status_code")
    task_status = output.get("task_status")
    if status and int(status) >= 400:
        raise VoiceInputError(f"bailian native ASR HTTP {status}: {data.get('message') or data}")
    if task_status and task_status != "SUCCEEDED":
        raise VoiceInputError(f"bailian native ASR task {task_status}: {output.get('message') or data.get('message') or data}")
    text = _extract_bailian_text(output)
    if not text:
        raise VoiceInputError(f"bailian native ASR response missing text: {json.dumps(data, ensure_ascii=False)[:300]}")
    return text


def _dashscope_response_dict(resp):
    if isinstance(resp, dict):
        return resp
    if hasattr(resp, "__dict__"):
        return dict(resp.__dict__)
    return {}


def _extract_bailian_text(output):
    candidates = []
    for subtask in output.get("results") or []:
        for result in subtask.get("results") or []:
            candidates.append(result.get("transcription_url"))
        candidates.extend(item.get("transcription_url") for item in subtask.get("transcription_urls") or [])
    texts = []
    for url in [item for item in candidates if item]:
        try:
            with urlrequest.urlopen(url, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception:
            continue
        for transcript in payload.get("transcripts") or []:
            text = str(transcript.get("text") or "").strip()
            if text:
                texts.append(text)
    return "\n".join(texts).strip()


def _prepare_audio(path):
    ext = path.suffix.lower()
    if ext not in _CONVERT_EXTS:
        return path, None
    if ext == ".silk":
        converted = _prepare_silk_audio(path)
        if converted:
            return converted
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return path, None
    fd, out_name = tempfile.mkstemp(prefix="g_agent_voice_", suffix=".wav")
    os.close(fd)
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(path), "-ar", "16000", "-ac", "1", out_name]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        return Path(out_name), out_name
    except Exception:
        Path(out_name).unlink(missing_ok=True)
        return path, None


def _prepare_silk_audio(path):
    try:
        import pilk
    except Exception:
        return None
    fd, out_name = tempfile.mkstemp(prefix="g_agent_voice_", suffix=".wav")
    os.close(fd)
    try:
        pilk.silk_to_wav(str(path), out_name, 16000)
        return Path(out_name), out_name
    except Exception:
        Path(out_name).unlink(missing_ok=True)
        return None


def _call_openai_transcription(path, cfg, *, source):
    boundary = "----GAgentVoiceBoundary"
    fields = {"model": cfg["model"]}
    if cfg.get("language"):
        fields["language"] = cfg["language"]
    body = _multipart_body(boundary, fields, "file", path)
    url = cfg["base_url"] + "/audio/transcriptions"
    req = urlrequest.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": f"G-Agent voice-input/{source}",
        },
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=cfg["timeout"]) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise VoiceInputError(f"ASR HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise VoiceInputError(f"ASR request failed: {exc.reason}") from exc
    except Exception as exc:
        raise VoiceInputError(f"ASR request failed: {type(exc).__name__}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VoiceInputError(f"ASR response is not JSON: {raw[:200]}") from exc
    text = str(data.get("text") or "").strip()
    if not text:
        raise VoiceInputError(f"ASR response missing text: {raw[:200]}")
    return text


def _multipart_body(boundary, fields, file_field, path):
    chunks = []
    for key, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                str(value).encode(),
                b"\r\n",
            ]
        )
    data = Path(path).read_bytes()
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{file_field}"; filename="{Path(path).name}"\r\n'.encode(),
            b"Content-Type: application/octet-stream\r\n\r\n",
            data,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks)
