"""模板配置与未来接口；V0.1不计算跨片段关系。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / 'template_editing/results/consult_conversion_v1_v01'
DEFAULT_TEMPLATE = Path(__file__).resolve().parent / 'templates/consult_conversion_v1.json'


def load_template(path=DEFAULT_TEMPLATE):
    template = json.loads(Path(path).read_text('utf-8'))
    if template['topic_filter'] != 'ANY':
        raise ValueError('V0.1只开放ANY；主题过滤接口已预留')
    return template


def evaluate_transition(segment_a, segment_b):
    """V0.2预留接口；None表示未计算，不表示得分为零。"""
    return None
