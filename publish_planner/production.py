"""生产模块的类型限定边界；仅返回授权账号/创建本地测试计划。"""
from dataclasses import replace


def startup_accounts(store, session_token):
    return store.plan_accounts(session_token, "STARTUP")


def commerce_accounts(store, session_token):
    return store.plan_accounts(session_token, "COMMERCE")


def create_startup_plan(store, session_token, plan):
    return store.create_plan(session_token, replace(plan, business_type="STARTUP"))


def create_commerce_plan(store, session_token, plan):
    return store.create_plan(session_token, replace(plan, business_type="COMMERCE"))


def open_plan(st, business_type):
    if business_type not in {"STARTUP", "COMMERCE"}:
        raise ValueError("INVALID_BUSINESS_TYPE")
    st.session_state.workspace_mode = "发布管理"
    st.session_state.planner_business_context = business_type
    st.session_state.pop("planner_draft_id", None)
