from datetime import datetime, timezone


def parse_timestamp(value, label='时间'):
    """把 ISO-8601 时间规范化为固定宽度的 UTC 字符串。

    固定宽度（微秒 6 位、固定 +00:00 后缀）保证字典序与时间序一致，
    这样快照里的时间可以直接做字符串比较。
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(label + '必须为 ISO-8601 时间字符串')
    text = value.strip()
    if not text:
        raise ValueError(label + '不能为空')
    try:
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError(label + '必须为 ISO-8601 时间，如 2026-11-19T09:00:00Z')
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime('%Y-%m-%dT%H:%M:%S.%f+00:00')
