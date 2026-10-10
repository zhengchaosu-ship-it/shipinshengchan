# 账号背景 ACCOUNT_VISUAL_LAYER

独立于内容Slot、TemplateVersion、StartupProfile和托管授权。按`business_account_id`绑定，任何昵称、备注或文件名均不用于账号身份匹配。

## 本地部署

`AccountBackgroundStore.migrate()`执行`migrations/001_background.sql`，先备份operations.db，不修改既有表。素材目录沿用`jianying_auto/config.json`的`bg_dir`；本机为`E:\备份\背景素材`。新增账号不存在绑定行，默认NONE，不初始化托管或复制其它账号背景。

`catalog.scan()`只显式扫描背景目录，SHA256作为稳定素材ID并去重。支持图片PNG/JPG/JPEG/WEBP/BMP、视频MP4/MOV/MKV/AVI/WEBM/M4V/GIF；记录尺寸、时长、类型、路径和缩略图。普通页面、账号切换、背景下拉只读SQLite。刷新失败保留已有记录；文件缺失/被改写在生成前拒绝，必须重新编目并由用户选择。

## 用户操作

8502 → AI托管 → 选择托管账号 → 账号设置 · 账号背景 → 选择背景 → 预览、显示方式 → 保存账号背景。关闭弹窗取消未保存选择。账号背景可在托管运行时明确修改，只影响以后新生成草稿，不改变模板、授权或历史。

人工自动起号默认继承绑定，可在“本次使用其它背景”选择一次生成的覆盖素材和fit；不会写回绑定。AI托管从业务ID读取绑定，不接受随机覆盖。开启“生成必须有背景”后，没有可用背景会在生成任务创建前阻止；未启用此要求时允许NONE。

## 生成接线

人工批次的`generation_context.target_account_id`与托管的`ServiceGrant.account_id`均作为背景作用域。生成前冻结快照、核验文件hash；通过隐藏子进程环境交给原剪映生成器，再次验证账号ID和hash。

最底层`账号背景`轨，0秒开始至最终duration。图片静帧拉满；视频静音循环，最后一段精确截断。COVER/CONTAIN/STRETCH只调整背景居中缩放，主体绿幕、裁切、位置不改，画布1080×1920。快照写入新草稿`account_visual_layer.json`和人工批次结果，供审计。缩略图和停用绑定的旧路径不成为Render素材依赖。既有素材打包器可携带真实背景图片/视频，无需改变Render/Publish链。

无业务账号的旧独立CLI保留随机背景兼容；8502人工/AI入口都必须携带业务ID，NONE不会进入旧随机分支。历史草稿不被重写。

## 验证

```
.venv-cuda-test\Scripts\python.exe -X utf8 -m unittest account_visuals.tests.test_background account_visuals.tests.test_ui -v
```

两账号真实剪映草稿和视频循环/fit验收使用已配置的剪映Python：`jianying_auto/runtime/account_background_20261006/draft_acceptance.py`。全部输出在隔离验收目录；不调用StartupContentRegistration、RenderQueue提交或Publish。首次执行不覆盖已有证据；`--resume`只继续验收已有测试草稿。

验收报告：`jianying_auto/runtime/account_background_20261006/REPORT.md`。
