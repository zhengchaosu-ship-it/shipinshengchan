# 寻帧候选去重上线验收

2026-09-28：候选去重已启用，8502服务已重启，使用formal_v1_repaired。ORB未接入生产；旧ORB代码与实验保留。未启动CLIP建库。

## 查询行为与回滚

开启时：原图DINO embedding → 正式FAISS Top500 → 按原始DINO降序逐帧筛选 → 最多10条结果。每asset最多5帧，与该asset已保留的全部代表帧相隔至少10秒；正好10秒允许保留。相同或邻近时间优先保留分数最高的帧。similarity、asset/video/frame ID和timestamp均不修改。

仅对最终结果读取JPEG，不对500个候选都读缩略图；不调用ORB。结果字段及页面代码不变。去重后不足10条时如实返回较少结果，不补重复帧、不增加召回范围：本次hell_02和business_15各返回5条，其余回归例返回10条。

配置文件：`D:\video_search_tool\benchmark\experiments\dino_july_web\search_config.json`

```json
{
  "search_index": "formal_v1_repaired",
  "candidate_dedup": true
}
```

- 双击 `D:\video_search_tool\关闭寻帧候选去重.bat`：改为false并重启8502，恢复原DINO Top10。
- 双击 `D:\video_search_tool\开启寻帧候选去重.bat`：改为true并重启8502。
- 手动修改布尔字段后，需要重新运行 `启动寻帧.bat`；Streamlit缓存了引擎，单纯刷新页面不负责重新读取配置。
- 旧配置缺少此字段时默认false；7月检索保持原行为。切换索引脚本保留已有开关。
- 脚本的false/true配置写入与加载均已测试；同一个实际engine关闭开关后，30例Top10逐项恢复。正式服务最后保持true。

## 修改文件

已有文件修改前均保留 `.candidate-dedup-20260928.bak`：

1. `benchmark/experiments/dino_july_web/search_adapter.py`：冻结后处理、布尔配置校验、按调用返回性能数据；原search返回契约不变。
2. `benchmark/experiments/dino_july_web/search_config.json`：正式开启candidate_dedup。
3. `benchmark/experiments/dino_july_web/switch_index.ps1`：切库时保留其它配置字段。
4. `benchmark/experiments/dino_july_web/README.md`：操作与回滚说明。
5. `HANDOFF.md`：记录已上线行为。

新增：`set_candidate_dedup.ps1`、根目录两个开/关BAT、`test_candidate_dedup.py`，以及本目录的回归/服务测试脚本和结果。未修改app.py、ui.py、search.py、启动解释器或生产MobileNet代码。

## 轻量测试与实际查询回归

62项轻量测试通过：Web/adapter/UI 30项、原项目26项、反馈库6项。新增测试覆盖10秒边界、每asset5帧上限、最高分优先、分数不变、配置兼容与非法值、Top500请求、只读取最终缩略图、跨线程连接和关闭后恢复Top10。

随后通过生产adapter对10张hell10及20张holdout原图实际重新生成query embedding、查询现有FAISS。开启和关闭两条路径均与原实验缓存的结果index_id逐项一致，分数误差小于2e-6。两条路径无需另建索引；实际返回不足10条时未强行补足。所有开启结果的路径、字段、时间戳与JPEG读取通过。

| 数据集/方案 | Top1 | Top5 | Top10 |
|---|---:|---:|---:|
| hell10 baseline | 2/10，20% | 5/10，50% | 5/10，50% |
| hell10 去重 | 2/10，20% | 5/10，50% | 6/10，60% |
| holdout20 baseline | 11/20，55% | 16/20，80% | 16/20，80% |
| holdout20 去重 | 11/20，55% | 16/20，80% | 17/20，85% |

hell10 case4：154→7；case7：226→86。没有加入ORB，因此不将此前ORB对case7的提升计入本次上线。holdout business_16：17→8。两组的原Top10成功案例均无退化，准确率与冻结去重实验一致。指标为前K条结果是否包含正确asset，未新增视频内时间精排。

## 实际8502服务验证与边界

服务固定由 `.venv-cuda-test\Scripts\python.exe -m streamlit run ...` 启动。环境检查通过：transformers 4.57.6、AutoImageProcessor正常、RTX3060 CUDA可用。8502仅监听127.0.0.1；实际进程见service_process.json。

浏览器打开后确认页面仍显示正式素材库、319个素材、约507小时、DINO formal_v1_repaired、1,843,351画面。**当前浏览器自动化未能打开原生文件选择器；可用浏览器只有Codex内置浏览器，因此不能声称浏览器手工上传端到端已经通过。**

为验证真正运行中的服务，独立测试客户端使用实际HTTP上传端点和Streamlit WebSocket页面事件，完成以下3张真实图片的上传、搜索、正确素材反馈和预览。没有mock上传控件、没有替换engine，没有使用独立AppTest假装线上会话。

| 图片 | 最终正确asset排名 | 返回数量 | 媒体图片可读 | 搜索服务往返 | 预览可解码 |
|---|---:|---:|---:|---:|---|
| hell10 4.png | 7 | 10 | 11/11 | 0.581秒 | 是 |
| business20 16.png | 8 | 10 | 11/11 | 0.355秒 | 是 |
| business20 5.png | 4 | 10 | 11/11 | 0.375秒 | 是 |

每次返回的asset_id、video_id、timestamp均与adapter回归逐项匹配，所有视频路径存在；11张图片包含1张query和10张结果缩略图。搜索与反馈实际写入独立feedback库，反馈已回读校验，备注明确标记“上线Smoke Test、既有case、不是新增独立案例”。测试过程中总计产生5条带candidate_dedup_smoke前缀的搜索记录（含2次测试脚本核对中断的尝试），没有删除旧记录。最终3次完整通过见live_service_smoke.json。

预览调用现有页面处理器生成/读取短MP4，HTTP读取后实际解码成功。沿用返回timestamp前1秒的既有预览逻辑；3段有效视频帧长度约5.67、5.75、6.27秒，源TS的时间起点偏移会计入播放器时间轴，因此不直接等于请求的8秒。另在真实浏览器打开business_05返回的预览URL，播放器readyState=4、960×2020、无解码错误，播放到7.966秒结束，确认浏览器媒体播放可用。本次未修改预览实现。返回时间点与GT时间并不总是相同（例如hell4首个正确asset代表帧在19秒、其GT为476秒）；这属于原有素材内时间定位问题，不是本次去重改写时间轴。本次确认预览围绕返回位置生成，不宣称已解决GT时间定位。

## 性能

下表为30个实际query、开启路径的逐次观测；模型/FAISS加载不计入，但首张CUDA查询预热计入。不是并发压力测试。

| 阶段 | median | P95 |
|---|---:|---:|
| DINO query：embedding+FAISS Top500 | 142.468ms | 206.915ms |
| 500条metadata读取 | 9.535ms | 10.241ms |
| 去重本身 | **0.131ms** | **0.201ms** |
| 最终缩略图读取与结果整理 | 2.600ms | 2.715ms |
| adapter总搜索 | **154.672ms** | **219.229ms** |

去重是轻量CPU操作，没有明显延迟。Top500的metadata读取额外约10ms，未发生500张JPEG额外I/O。实际Web服务事件往返另包含页面与反馈处理，不和纯查询耗时混用。

正式engine的search_with_timings返回每次调用的性能数据，search继续只返回结果列表，并向search_adapter INFO logger记录计时（是否显示取决于运行日志级别）；未新增跨线程共享last_timing变量。

## 保护检查与最终状态

formal_v1、formal_v1_repaired、CLIP、models和此前三个诊断/实验目录共858个受保护文件的路径、大小、mtime_ns前后一致。正式FAISS ntotal仍为1,843,351。此为文件stat检查，不冒称重新做了全库SHA256校验。没有写FAISS、metadata、feature或模型，也没有删除旧ORB代码/实验。

上线状态：**已上线候选去重；candidate_dedup=true；ORB不启用。** 浏览器原生文件选择器的自动化验证仍有上述限制，其余实际运行服务的3张图上传、搜索、反馈、预览链路通过。

服务地址：http://127.0.0.1:8502 。日常双击启动寻帧.bat；一键回滚使用关闭寻帧候选去重.bat。

本次完成后停止，不继续调参或ORB优化。
