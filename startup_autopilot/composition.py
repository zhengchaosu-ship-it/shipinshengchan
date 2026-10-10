"""用户定义结构。顺序与业务类型不从账号名称、备注或AI结果推断。"""
from dataclasses import asdict, dataclass
import math
import re

from .models import digest

MODULES=('引流','手法','坐诊','产品','收尾','自定义')
STRATEGIES={'FIXED':'固定','ROTATING':'轮换','LEARNABLE':'AI选择','PREFERRED_POOL':'优先素材'}
PREFIXES=dict(zip(MODULES,('FLOW','HAND','CONSULT','PRODUCT','TAIL','CUSTOM')))


@dataclass(frozen=True)
class CompositionSlot:
    slot_id: str
    slot_position: str
    module_type: str
    material_pool: str
    selection_policy: str
    fixed_material_id: str | None = None
    preferred_material_ids: tuple[str,...] = ()
    preferred_only: bool = False
    max_uses_7d: int | None = 7
    cooldown_hours: float = 0
    avoid_adjacent_repeat: bool = False
    exploration_ratio: float = .1

    def validate(self):
        if (not self.slot_id or not re.fullmatch(r'[A-Z]+_[1-9][0-9]*',self.slot_position)
            or self.module_type not in MODULES or not self.material_pool or self.selection_policy not in STRATEGIES):
            raise ValueError('SLOT_CONFIGURATION_REQUIRED')
        if self.selection_policy=='FIXED' and not self.fixed_material_id:
            raise ValueError('FIXED_MATERIAL_REQUIRED')
        if self.selection_policy=='PREFERRED_POOL' and not self.preferred_material_ids:
            raise ValueError('PREFERRED_MATERIALS_REQUIRED')
        if len(set(self.preferred_material_ids))!=len(self.preferred_material_ids):
            raise ValueError('DUPLICATE_PREFERRED_MATERIAL')
        if self.max_uses_7d is not None and (type(self.max_uses_7d) is not int or self.max_uses_7d<1):
            raise ValueError('INVALID_SLOT_WEEKLY_LIMIT')
        if not math.isfinite(self.cooldown_hours) or self.cooldown_hours<0:
            raise ValueError('INVALID_SLOT_COOLDOWN')
        if not math.isfinite(self.exploration_ratio) or not 0<=self.exploration_ratio<=1:
            raise ValueError('INVALID_SLOT_EXPLORATION')


@dataclass(frozen=True)
class StartupCompositionTemplateVersion:
    account_id: str
    version: int
    slots: tuple[CompositionSlot,...]
    created_at: str | None = None
    confirmed_by: str | None = None

    def validate(self, *, confirmed=False):
        if not self.account_id or not 1<=len(self.slots)<=20 or self.version<0:
            raise ValueError('TEMPLATE_REQUIRES_1_TO_20_USER_SLOTS')
        if len({s.slot_id for s in self.slots})!=len(self.slots) or len({s.slot_position for s in self.slots})!=len(self.slots):
            raise ValueError('SLOT_IDENTITY_MUST_BE_UNIQUE')
        for slot in self.slots:slot.validate()
        if confirmed and (self.version<1 or not self.created_at or not self.confirmed_by):
            raise PermissionError('USER_CONFIRMED_TEMPLATE_REQUIRED')

    def structure(self):
        return {'account_id':self.account_id,'slots':[asdict(s) for s in self.slots]}

    def config_hash(self):return digest(self.structure())


def from_dict(value):
    return StartupCompositionTemplateVersion(value['account_id'],value['version'],tuple(
        CompositionSlot(**{**s,'preferred_material_ids':tuple(s.get('preferred_material_ids',()))}) for s in value['slots']),
        value.get('created_at'),value.get('confirmed_by'))


def composition_signature(selections):
    # 实际媒体顺序相同即同组合；改版本、改Slot名字不会制造新的内容身份。
    return digest([s['material_id'] for s in selections])


def reorder(slots, ids):
    if len(ids)!=len(slots) or len(set(ids))!=len(ids) or set(ids)!={s['slot_id'] for s in slots}:
        raise ValueError('INVALID_SLOT_REORDER')
    by_id={s['slot_id']:s for s in slots}
    return [by_id[i] for i in ids]
