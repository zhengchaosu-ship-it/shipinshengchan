"""读取独立JSONL片段池。"""
import json
from pathlib import Path


def query(path, *, tag=None, topic='ANY'):
    with Path(path).open(encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            if (tag is None or tag in row['function_tags']) and (topic == 'ANY' or topic in row['topic_tags']):
                yield row
