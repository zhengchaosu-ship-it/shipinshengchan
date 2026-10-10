# PRODUCTION_AUTOPILOT_CONSOLIDATION — 2026-10-06

已按P0 → P1 → P2增量实施并载入现有服务。初始Gap Audit见GAP_AUDIT.md，操作与恢复说明见README.md。实现交付完成；真实多日无人值守验收尚未完成，不能标为全部READY。

## 收敛后的逐项状态

| 优先级 | 能力 | 状态 | 验证及边界 |
|---|---|---|---|
| P0 | Account Sync、唯一稳定映射、独立账号资产 | DONE | 复用原Registry；5分钟同步；保留7个映射、6套配置/背景，禁止昵称合并 |
| P0 | Auth Recovery | DONE | 用户检查请求仅同步、状态查询、对账；保留原确认；暂停/结束优先；其它异常或关键健康失败禁止恢复 |
| P0 | 每日预算、Planner | DONE | 人工与自动新计划共同最多5/账号/北京时间自然日；保留历史排期 |
| P0 | Render / Publish防重复、重启保护 | DONE / RISK | 复用原身份、唯一队列、租约、回执和提交闩锁；GUI中断或未知提交停在人工核验，不能承诺外部系统数学上的exactly-once |
| P0 | Failed / Uncertain、补位谱系 | DONE | 原FAILED不重试；只读查询已知TaskSet；恢复后新未来内容可记父子谱系；未知提交不自动补位 |
| P0 | AttentionRequired异常中心 | DONE | 去重、账号隔离、行动提示、检查请求审计；后台瞬时网络故障15分钟只读复查 |
| P0 | 固定3模块、单工作室无登录 | DONE | 实际8502浏览器验证；高级管理保留工程入口；热加载清单同步修复 |
| P1 | Metrics、20条门槛、Affinity | DONE / PARTIAL | 接入2h/24h/72h；NULL缺值、迟到标记、独立只读队列；真实公开+指标+素材ID才有效；复用原归一化/收缩/探索/疲劳/人工覆盖。当前真实指标0，尚无20条真实学习验收 |
| P1 | AccountVisualProfile | PARTIAL | 背景已共用；其它视觉字段按账号独立预留NULL，沿用原参数。字幕/字体/Logo等编辑尚未实现，未冒称支持 |
| P1 | 驾驶舱、健康 | DONE / RISK | 卡片显示真实进度/粉丝/样本/异常；5分钟健康检查已接线；Render工作站当前OFFLINE |
| P1 | 自动备份、恢复 | DONE | 每6小时备份3个业务库及审计；真实隔离恢复演练保留6份授权、完整性/hash通过；恢复保护HOLD，核对平台历史前禁止派发 |
| P2 | 10/20/50账号架构 | DONE / PARTIAL | 50账号250条持久规划、重复规划幂等与隔离fixture通过；共享RenderQueue并发领取可配置，正式并行仍1。未做250条真实视频吞吐验收 |

## 实际服务与数据保护

- 8502、原Autopilot、Publisher、Account Sync及蚁小二客户端正常；最后只读健康核验唯一问题是Render Worker OFFLINE。无新后台POC服务。
- 8502共8个业务账号，7个已同步抖音账号，1个历史账号未绑定；6个用户已配置账号保持ATTENTION_REQUIRED、enabled=0，本轮没有代用户开始或恢复托管。
- 丙曜保持原映射：business `1621131832863931` → provider `6ac389eb46f95bf847d47da1`，不重建，不新增托管配置。
- Plan、PlanItem、授权、Profile、模板、背景、分配身份及Render队列身份保护检查通过；提交闩锁总数仍44，本轮新增真实Render=0、Publish=0。未改变已进入平台的排期参数，未重发FAILED。
- 官方只读复核补齐4个原先NULL的provider_video_id，并使部分平台原失败状态返回QUEUED/SUBMITTED；保留本地旧失败分配及停用授权。`runtime/live.after.json`明确记录这些原生进展，并逐行校验其余原身份/参数未变。
- 历史details账号ID为空不再误报：只接受原payload稳定账号ID、原完整dry-run hash、原intent、原TaskSet证明；非NULL错ID直接拒绝，不按昵称找号。

## 验证证据

- 部署前64项相关回归通过；最后15项收敛专项通过，最后32项账号同步/三模块UI回归通过；认证与NULL身份兼容定向回归通过。相关26个Python文件语法通过。这些是不同阶段的检查，不相加冒充独立用例总数。
- 真实8502已验证账号总览、固定模块、异常中心及后台检查状态；截图`runtime/PRODUCTION_COCKPIT.jpg`。没有点击生成、最终开始、结束或真实验证按钮。
- 真实备份：`startup_autopilot/runtime/production_worker/consolidation/backups/20261006T133030119624Z`；隔离恢复报告在`production_autopilot/runtime/restore-drill-20261006T133030119624Z`，HOLD保护已验证。

## 仍需完成的生产运行验收

1. 恢复Render工作站在线，并人工核验已有中断/未确认输出，不能直接重Render。
2. 引流账号有3条作品记录“可能已删除”，需在抖音创作者中心核对；夏竹花开错过安全提前量，原未提交分配已保留为MISSED_NOT_SUBMITTED。其余账号原平台风险已在初始审计记录，最新只读查询有状态推进，但没有仅据ONLINE自动恢复原通用FAILED授权。
3. 用户在核验后明确确认恢复各账号；关键服务/账号/模板/额度仍由原生产校验拦截。不得为了验收替用户重发历史任务。
4. 观察真实连续多日生成→渲染→公开→Metrics闭环；累计20条本账号有效样本后核验真实Affinity优化；达到目标只提醒，结束起号停止新内容。

机器故障、平台认证与外部GUI无法由fixture消除。素材容量和疲劳约束保留用户规则；供给不足进入异常，不静默放宽。
