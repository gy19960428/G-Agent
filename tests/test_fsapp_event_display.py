import importlib
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "frontends"))

fsapp = importlib.import_module("frontends.fsapp")


def test_final_display_prefers_explicit_final_display():
    item = {
        "done": "raw answer with [FILE:/tmp/out.txt]",
        "final_display": "clean final answer",
        "events": [{"type": "final", "display": "event final answer"}],
    }

    assert fsapp._final_display_from_queue_item(item) == "clean final answer"


def test_final_display_falls_back_to_final_event_display():
    item = {
        "done": "raw answer",
        "events": [
            {"type": "progress", "display": "working"},
            {"type": "final", "display": "event final answer"},
        ],
    }

    assert fsapp._final_display_from_queue_item(item) == "event final answer"


def test_final_display_falls_back_to_cleaned_done():
    item = {"done": "<thinking>hidden</thinking>visible"}

    assert fsapp._final_display_from_queue_item(item) == "visible"


def test_extract_post_content_returns_file_resources():
    content = {
        "zh_cn": {
            "content": [[
                {"tag": "text", "text": "请查看附件"},
                {"tag": "file", "file_key": "file-key-1", "file_name": "example.md"},
            ]]
        }
    }

    text, images, files = fsapp._extract_post_content(content)

    assert text == "请查看附件"
    assert images == []
    assert files == [{"file_key": "file-key-1", "file_name": "example.md"}]


def test_build_user_message_downloads_post_file(monkeypatch, tmp_path):
    class Message:
        message_type = "post"
        message_id = "message-id"
        content = '{"zh_cn":{"content":[[{"tag":"file","file_key":"file-key-1","file_name":"example.md"}]]}}'

    saved_file = tmp_path / "example.md"
    saved_file.write_text("content", encoding="utf-8")
    monkeypatch.setattr(
        fsapp,
        "_download_and_save_media",
        lambda msg_type, content_json, message_id: (str(saved_file), "example.md"),
    )

    text, image_paths = fsapp._build_user_message(Message())

    assert text == f"[file: example.md]\n[File: source: {saved_file}]"
    assert image_paths == []
