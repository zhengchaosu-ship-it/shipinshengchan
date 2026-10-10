"""可验证配置和状态机；权限主体须由既有8502鉴权构建。"""
from dataclasses import dataclass, replace, asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path

SHANGHAI = timezone(timedelta(hours=8))
ACTIVE = {'COLD_START', 'LEARNING', 'AUTOPILOT'}
STATES = {'SETUP', *ACTIVE, 'PAUSED', 'FINISHED', 'ATTENTION_REQUIRED'}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def policy():
    return json.loads(Path(__file__).with_name('default_policy.json').read_text('utf-8'))


def aware(value):
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if value.tzinfo is None:
        raise ValueError('TIMEZONE_REQUIRED')
    return value


@dataclass(frozen=True)
class Actor:
    employee_id: str
    permitted_accounts: frozenset[str]
    role: str = 'EMPLOYEE'

    def require(self, account_id, *, admin=False):
        if account_id not in self.permitted_accounts or (admin and self.role != 'ADMIN'):
            raise PermissionError('ACCOUNT_PERMISSION_REQUIRED')


@dataclass(frozen=True)
class Slot:
    module_type: str
    material_ids: tuple[str, ...]
    minimum_seconds: float = 1
    maximum_seconds: float = 60
    fixed_material_id: str | None = None
    core: bool = True


@dataclass(frozen=True)
class Template:
    account_id: str
    version: str
    slots: tuple[Slot, ...]

    def validate(self):
        if not self.slots:
            raise ValueError('TEMPLATE_REQUIRED')
        for slot in self.slots:
            if not slot.module_type or not slot.material_ids or len(set(slot.material_ids)) != len(slot.material_ids):
                raise ValueError('INVALID_SLOT_POOL')
            if not 0 < slot.minimum_seconds <= slot.maximum_seconds:
                raise ValueError('INVALID_DURATION_RULE')
            if slot.fixed_material_id and slot.fixed_material_id not in slot.material_ids:
                raise ValueError('FIXED_MATERIAL_OUTSIDE_POOL')


@dataclass(frozen=True)
class Profile:
    account_id: str
    target_follower_count: int | None
    template_version: str
    enabled: bool = False
    status: str = 'SETUP'
    daily_publish_limit: int = 5
    publish_times: tuple[str, ...] = ('09:00', '12:00', '15:00', '18:00', '21:00')
    learning_threshold: int = 20
    exploit_ratio: float = 0.7
    explore_ratio: float = 0.1
    execution_mode: str = 'SHADOW_MODE'
    policy_version: str = 'startup-policy-v1'
    template_hash: str | None = None
    policy_hash: str | None = None
    confirmed_by: str | None = None
    confirmed_at: str | None = None
    confirmed_config_hash: str | None = None
    attention_reason: str | None = None
    resume_status: str | None = None

    def config_hash(self):
        excluded = {'enabled','status','confirmed_by','confirmed_at','confirmed_config_hash','attention_reason','resume_status'}
        return digest({k:v for k,v in asdict(self).items() if k not in excluded})

    def validate(self):
        if self.execution_mode not in {'SHADOW_MODE','SHADOW','PRODUCTION'}:
            raise PermissionError('LIVE_AUTOPILOT_NOT_ENABLED_IN_FOUNDATION')
        if self.status not in STATES or not self.account_id:
            raise ValueError('INVALID_PROFILE')
        if self.target_follower_count is not None and (type(self.target_follower_count) is not int or self.target_follower_count<1):
            raise ValueError('INVALID_FOLLOWER_TARGET')
        if self.enabled and self.target_follower_count is None:
            raise ValueError('FOLLOWER_TARGET_REQUIRED_BEFORE_ENABLE')
        if type(self.daily_publish_limit) is not int or not 1 <= self.daily_publish_limit <= 5:
            raise ValueError('STARTUP_DAILY_LIMIT_MAXIMUM_5')
        if len(self.publish_times) != self.daily_publish_limit or len(set(self.publish_times)) != len(self.publish_times):
            raise ValueError('UNIQUE_FIXED_TIME_SLOTS_REQUIRED')
        for value in self.publish_times:
            if len(value) != 5 or datetime.strptime(value, '%H:%M').strftime('%H:%M') != value:
                raise ValueError('INVALID_PUBLISH_TIME')
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in (self.exploit_ratio,self.explore_ratio)) or self.exploit_ratio+self.explore_ratio > 1:
            raise ValueError('INVALID_SELECTION_RATIOS')
        if self.learning_threshold < 20:
            raise ValueError('LEARNING_THRESHOLD_MINIMUM_20')
        if self.enabled and (not self.confirmed_by or not self.confirmed_at or self.confirmed_config_hash != self.config_hash()):
            raise PermissionError('EXPLICIT_CONFIG_CONFIRMATION_REQUIRED')
        if self.enabled and any(not value or len(value)!=64 for value in (self.template_hash,self.policy_hash)):
            raise PermissionError('IMMUTABLE_TEMPLATE_AND_POLICY_HASH_REQUIRED')
        if self.confirmed_at:
            aware(self.confirmed_at)
        if self.status in {'SETUP','PAUSED','FINISHED','ATTENTION_REQUIRED'} and self.enabled:
            raise ValueError('INACTIVE_PROFILE_MUST_BE_DISABLED')


def phase(valid_public_samples, coverage, config):
    if valid_public_samples < config['learning_threshold']:
        return 'COLD_START'
    return 'AUTOPILOT' if coverage >= config['minimum_learning_coverage'] else 'LEARNING'


def transition(profile, actor, action, now, *, config_confirmed=False, config_hash=None, valid_samples=0, coverage=0, finish_choice=None, reason=None):
    actor.require(profile.account_id)
    profile.validate()
    if action == 'start':
        if profile.status != 'SETUP' or not config_confirmed or config_hash != profile.config_hash():
            raise PermissionError('SECOND_CONFIRMATION_REQUIRED')
        if profile.policy_hash!=digest(policy()):
            raise PermissionError('POLICY_CONFIGURATION_REQUIRES_CONFIRMATION')
        result = replace(profile, enabled=True, status=phase(valid_samples,coverage,dict(policy(),learning_threshold=profile.learning_threshold)),
                         confirmed_by=actor.employee_id,confirmed_at=aware(now).isoformat(),confirmed_config_hash=profile.config_hash())
    elif action == 'pause' and profile.status in ACTIVE:
        result = replace(profile,enabled=False,status='PAUSED',resume_status=profile.status)
    elif action == 'resume' and profile.status in {'PAUSED','ATTENTION_REQUIRED'}:
        if profile.confirmed_config_hash != profile.config_hash():
            raise PermissionError('RECONFIRM_CHANGED_CONFIGURATION')
        result = replace(profile,enabled=True,status=phase(valid_samples,coverage,dict(policy(),learning_threshold=profile.learning_threshold)),attention_reason=None)
    elif action == 'attention' and profile.status in ACTIVE and reason:
        result = replace(profile,enabled=False,status='ATTENTION_REQUIRED',resume_status=profile.status,attention_reason=reason)
    elif action == 'refresh_learning' and profile.status in ACTIVE:
        result = replace(profile,status=phase(valid_samples,coverage,dict(policy(),learning_threshold=profile.learning_threshold)))
    elif action == 'finish' and profile.status != 'FINISHED':
        if finish_choice not in {'KEEP_SCHEDULED','CANCEL_PRE_SUBMIT_ONLY'}:
            raise ValueError('EXPLICIT_EXISTING_SCHEDULE_CHOICE_REQUIRED')
        result = replace(profile,enabled=False,status='FINISHED')
    else:
        raise ValueError('INVALID_STATE_TRANSITION')
    result.validate()
    return result


def production_dispatch(*args, **kwargs):
    raise PermissionError('FOUNDATION_SHADOW_ONLY_NO_RENDER_OR_PUBLISH')


def material_override(actor, account_id, material_id, mode, allowed_materials):
    actor.require(account_id, admin=True)
    if material_id not in allowed_materials or mode not in {'LOCK','PREFERRED','BLOCK'}:
        raise ValueError('INVALID_ACCOUNT_MATERIAL_OVERRIDE')
    return {'account_id':account_id,'material_id':material_id,'mode':mode,'changed_by':actor.employee_id}
