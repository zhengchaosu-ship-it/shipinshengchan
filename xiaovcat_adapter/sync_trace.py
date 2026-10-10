"""同步阶段证据，不记录凭据或完整桌面树。"""
from datetime import datetime
import json


class SyncTrace:
    def __init__(self, directory):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.stage = 'WINDOW_NOT_FOUND'
        self.events = []

    def emit(self, stage, status='START', **details):
        self.stage = stage
        event = dict(at=datetime.now().astimezone().isoformat(), stage=stage,
                     status=status, **details)
        self.events.append(event)
        (self.directory / 'STAGES.json').write_text(
            json.dumps(self.events, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(event, ensure_ascii=False), flush=True)
