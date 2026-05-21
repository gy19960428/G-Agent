"""Feishu SSE event formatting helpers (Feishu SSE 事件格式化辅助)。"""
import re, json

def _one_line(text):
    text = re.sub(r'\s+', ' ', (text or '').strip())
    return text[:120].strip(' .')


def _clean_turn_brief(text):
    text = _one_line(text)
    if not text:
        return ''
    # Drop obvious prompt/history leakage and regex-like garbage from turn summaries.
    bad_pats = [
        r'^LLM Running \(Turn \d+\)',
        r'^Turn\s+\d+[：:](?:\s*思考中|\s*已完成)?$',
        r'^###\s*\[WORKING MEMORY\]',
        r'^<history>',
        r'^\[(?:USER|Agent)\]:',
        r'^[\\s\W\(\)\[\]\{\}\?\*\+\|\.^$-]+$',
    ]
    for pat in bad_pats:
        if re.match(pat, text, flags=re.IGNORECASE):
            return ''
    return text


def _extract_turn_brief(text):
    text = text or ''
    mats = re.findall(r'<summary>\s*(.*?)\s*</summary>', text, flags=re.DOTALL | re.IGNORECASE)
    for mat in reversed(mats):
        lines = [ln.strip() for ln in mat.splitlines() if ln.strip()]
        for line in lines:
            brief = _clean_turn_brief(line)
            if brief:
                return brief
        brief = _clean_turn_brief(mat)
        if brief:
            return brief
    # Fallback to the first readable plain-text line in this turn chunk.
    plain = re.sub(r'(?is)<(?:thinking|summary|tool_(?:use|call)|file_content)>[\s\S]*?</(?:thinking|summary|tool_(?:use|call)|file_content)>', '', text)
    for line in plain.splitlines():
        brief = _clean_turn_brief(line)
        if brief:
            return brief
    return ''


def _feishu_last_turn(text):
    mats = list(re.finditer(r'\*{0,2}LLM Running \(Turn (\d+)\) \.\.\.\*{0,2}', text or ''))
    return int(mats[-1].group(1)) if mats else None


def _feishu_latest_summary(text):
    return _extract_turn_brief(text)


def _feishu_turn_summaries(text):
    text = text or ''
    turn_pat = re.compile(r'\*{0,2}LLM Running \(Turn (\d+)\) \.\.\.\*{0,2}')
    turns = list(turn_pat.finditer(text))
    items = []
    for idx, mat in enumerate(turns):
        turn = int(mat.group(1))
        start = mat.end()
        end = turns[idx + 1].start() if idx + 1 < len(turns) else len(text)
        chunk = text[start:end]
        items.append({'turn': turn, 'summary': _extract_turn_brief(chunk)})
    return items


def _feishu_event(event_type, turn=None, text=None, display=None, status=None):
    event = {'type': event_type}
    if turn is not None:
        event['turn'] = turn
    if text is not None:
        event['text'] = text
    if display is not None:
        event['display'] = display
    if status is not None:
        event['status'] = status
    return event


def _feishu_done_display(turn, text):
    summary = _extract_turn_brief(text)
    return f"Turn {turn}：{summary}" if summary else f"Turn {turn}：已完成"


def _feishu_done_text(turn, text):
    for item in _feishu_turn_summaries(text):
        if item['turn'] == turn:
            return item['summary'] or ''
    return ''


def _feishu_progress_event(text):
    turn = _feishu_last_turn(text)
    if turn is None:
        return None
    display = _feishu_progress_display(text).get('display') or f"Turn {turn}：思考中"
    return _feishu_event('turn_update', turn=turn, text=text, display=display, status='running')


def _feishu_done_event(turn, text):
    done_text = _feishu_done_text(turn, text)
    display = f"Turn {turn}：{done_text}" if done_text else f"Turn {turn}：已完成"
    return _feishu_event('turn_done', turn=turn, text=text, display=display, status='done')


def _feishu_final_event(text):
    return _feishu_event('final', text=text, display=_feishu_final_display(text))


def _feishu_error_event(text, err):
    return _feishu_event('final', text=text, display=_feishu_error_display(text, err), status='error')


def _feishu_progress_display(text):
    items = _feishu_turn_summaries(text)
    if not items:
        return {}
    last = items[-1]
    display = f"Turn {last['turn']}：{last['summary']}" if last['summary'] else f"Turn {last['turn']}：思考中"
    return {'turn': last['turn'], 'status': 'running', 'display': display}


def _feishu_completed_displays(text):
    items = _feishu_turn_summaries(text)
    return [
        {
            'turn': item['turn'],
            'status': 'done',
            'display': f"Turn {item['turn']}：{item['summary']}" if item['summary'] else f"Turn {item['turn']}：已完成"
        }
        for item in items
    ]


def _feishu_final_display(text):
    text = text or ''
    mats = list(re.finditer(r'\*{0,2}LLM Running \(Turn \d+\) \.\.\.\*{0,2}\s*', text))
    if mats:
        text = text[mats[-1].end():]
    # Remove any leaked turn anchors even if formatting/newlines were mangled.
    text = re.sub(r'\*{0,2}LLM Running \(Turn \d+\) \.\.\.\*{0,2}\s*', '', text)
    text = re.sub(r'🛠️[^\n]*\n````[\s\S]*?````\s*', '', text)
    text = re.sub(r'`````[\s\S]*?`````\s*', '', text)
    for pat in [r'<thinking>[\s\S]*?</thinking>', r'<summary>[\s\S]*?</summary>', r'<tool_(?:use|call)>[\s\S]*?</tool_(?:use|call)>', r'<file_content>[\s\S]*?</file_content>']:
        text = re.sub(pat, '', text, flags=re.IGNORECASE)
    cleanup_pats = [
        r'(?im)^\*{0,2}LLM Running \(Turn \d+\) \.\.\.\*{0,2}\s*$',
        r'(?im)^Turn\s+\d+[：:].*$',
        r'(?im)^\[Info\].*$',
        r'(?is)###\s*\[WORKING MEMORY\][\s\S]*?(?=\n\s*###\s*用户当前消息|\Z)',
        r'(?is)<history>[\s\S]*?</history>',
        r'(?is)<key_info>[\s\S]*?</key_info>',
        r'(?im)^<(?:history|key_info)>\s*$',
        r'(?im)^</(?:history|key_info)>\s*$',
        r'(?im)^Current turn:\s*\d+\s*$',
        r'(?im)^\[(?:USER|Agent)\]:.*$',
        r'(?im)^有不清晰的地方请再次读取.*$',
        r'(?im)^\[SYSTEM\]\s*此为\s*\d+\s*个对话前设置的key_info.*$',
        r'(?im)^###\s*用户当前消息\s*$',
    ]
    for pat in cleanup_pats:
        text = re.sub(pat, '', text)
    # Avoid Feishu markdown swallowing the rest of the message on unmatched backticks.
    text = re.sub(r'(^|\n)`+(?=\s*(?:\n|$))', r'\1', text)
    text = re.sub(r'(?m)^`\.\.\.`\s*$', '...', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text


def _feishu_error_display(text, err):
    body = _feishu_final_display(text)
    err = _one_line(format_error(err)) or '执行失败'
    return f'{body}\n\n执行失败：{err}'.strip() if body else f'执行失败：{err}'


