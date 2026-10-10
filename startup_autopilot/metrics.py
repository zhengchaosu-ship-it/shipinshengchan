"""纯函数指标契约。没有网络采集器；真实公开证据是反馈窗口的前置条件。"""
from dataclasses import dataclass, asdict
from datetime import timedelta
import math
from typing import Protocol

from .models import aware, digest

FIELDS = ('views','likes','comments','shares','favorites','followers_delta','completion_rate','watch_seconds')
WINDOWS = (2,24,72)


@dataclass(frozen=True)
class PublishedWork:
    account_id: str
    work_id: str
    public_at: str
    public_evidence_ref: str
    state: str = 'PUBLISHED'

    def validate(self):
        if self.state != 'PUBLISHED' or not all((self.account_id,self.work_id,self.public_evidence_ref)):
            raise ValueError('CONFIRMED_PUBLIC_WORK_REQUIRED')
        aware(self.public_at)


def feedback_requests(work):
    work.validate()
    return [{'account_id':work.account_id,'work_id':work.work_id,'window_hours':hours,
             'due_at':(aware(work.public_at)+timedelta(hours=hours)).isoformat(),
             'public_at':work.public_at,'public_evidence_ref':work.public_evidence_ref}
            for hours in WINDOWS]


@dataclass(frozen=True)
class MetricSnapshot:
    account_id: str
    work_id: str
    window_hours: int
    observed_at: str
    public_at: str
    values: dict
    capabilities: dict
    source: str
    evidence_ref: str
    evidence_hash: str
    time_precision: str = 'EXACT'

    def validate(self):
        if self.window_hours not in WINDOWS or not self.source or not self.evidence_ref or not self.evidence_hash:
            raise ValueError('METRICS_EVIDENCE_REQUIRED')
        if aware(self.observed_at) < aware(self.public_at)+timedelta(hours=self.window_hours):
            raise ValueError('FEEDBACK_WINDOW_NOT_DUE')
        if set(self.values)!=set(FIELDS) or set(self.capabilities)!=set(FIELDS):
            raise ValueError('METRICS_FIELDS_REQUIRED')
        for name, value in self.values.items():
            if self.capabilities[name] not in {'AVAILABLE','NOT_SUPPORTED','NOT_RETURNED','INVALID'}:
                raise ValueError('INVALID_METRICS_CAPABILITY')
            if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value)):
                raise ValueError('INVALID_METRIC')
            if value is not None and name!='followers_delta' and value<0:
                raise ValueError('NEGATIVE_METRIC')
            if name=='completion_rate' and value is not None and not 0<=value<=1:
                raise ValueError('INVALID_COMPLETION_RATE')
            if (value is not None) != (self.capabilities[name]=='AVAILABLE'):
                raise ValueError('METRICS_CAPABILITY_VALUE_MISMATCH')


class MetricsProvider(Protocol):
    """未来连接器必须返回可追溯快照，不改变业务作品身份。"""
    def collect(self, work: PublishedWork, window_hours: int) -> MetricSnapshot: ...


class YixiaoerMetricsDecoder:
    """仅解码既有证据出现的statistic字段；不宣称其它官方接口不存在。"""
    FIELD_MAP = {'views':'viewCount','likes':'greatCount','comments':'commentCount',
                 'shares':'shareCount','favorites':'collectCount'}

    def decode(self, work, hours, observed_at, statistic, *, evidence_ref, time_precision='EXACT'):
        work.validate()
        values, capabilities = {}, {}
        for field in FIELDS:
            key = self.FIELD_MAP.get(field)
            value = statistic.get(key) if key else None
            capability = 'NOT_SUPPORTED' if not key else 'NOT_RETURNED'
            if value is not None:
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
                    capability='INVALID'; value=None
                else:
                    capability='AVAILABLE'
            values[field],capabilities[field] = value,capability
        result = MetricSnapshot(work.account_id,work.work_id,hours,aware(observed_at).isoformat(),work.public_at,
                                values,capabilities,'YIXIAOER_STATISTIC',evidence_ref,digest(statistic),time_precision)
        result.validate()
        return result


def valid_public_sample_count(works, account_id):
    valid = set()
    for work in works:
        try:
            work.validate()
        except ValueError:
            continue
        if work.account_id==account_id:
            valid.add((work.account_id,work.work_id))
    return len(valid)
