"""现有按账号/Slot的epsilon探索与偏好选择，不改变已验证排名公式。"""
import math
from .models import digest


class BanditSelector:
    @staticmethod
    def score(account,slot,at,record,week,samples,threshold):
        if samples<threshold:return 'COLD_BALANCED_EXPLORATION',0
        if int(digest([account,slot.slot_position,at.isoformat()])[:8],16)%100<round(slot.exploration_ratio*100):
            return 'ACCOUNT_SLOT_EXPLORATION',0
        value=record.get('normalized_score',1) if record.get('sample_count',0)>0 else 1
        if not math.isfinite(value):raise ValueError('INVALID_AFFINITY_SCORE')
        return 'ACCOUNT_SLOT_AFFINITY',max(.25,min(3,value))*(1.3 if record.get('override')=='PREFERRED' else 1)-.15*week
