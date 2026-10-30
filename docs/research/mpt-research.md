# MoneyPrinterTurbo 源码级调研（2026-10-13）

> 对象：`/mnt/disk_sdb/zxy/MoneyPrinterTurbo/`（本机源码，核心 8700 行通读）。
> 结论：MPT 是"文案→库存素材→剪辑"拼装流水线（无 AI 视频生成），工程质量高（防御性注释/原子写/锁/限流齐全）。
> 分档：**A 强烈推荐 / B 已有等价物 / C 看情况**。**A 档四项已于 2026-10-13 全部实施**（见 reports-20261001.md 同日节）。

## A. 强烈推荐（✅ 已全部落地）

| # | 机制 | MPT 实现（源码位置） | Vidance 落地（2026-10-13） |
|---|------|---------------------|------------------|
| 1 | **字幕智能纠正** ✅ | `app/services/subtitle.py:209 correct()` | `utils/subtitle_correct.py`（Levenshtein 对齐+剧本文本替换+幻觉丢弃）；run_stt 三链路接线；20/20 测试 |
| 2 | **preflight 预检** ✅ | `app/services/task.py:1295-1392` | `core/preflight.py`（硬依赖拦/可降级警示的改良版）+ 5 子命令 `--no-preflight`；6/6 测试 + 实网拦截验证 |
| 3 | **素材下载验证 + 全局去重缓存** ✅ | `app/services/material.py:1007 save_video()` | `utils/material_cache.py`（URL md5 `img-{md5}` + PIL 验证 + 原子写）；asset_crawler 接线；20/20 测试 + E2E 二次 0.0s |
| 4 | **搜索结果 24h TTL 缓存** ✅ | `app/services/material_cache.py` | 同上模块 `search_get/put`（空结果不缓存）+ 白名单 TTL 清理 |

## B. 已有等价物（无需借鉴）

| MPT 机制 | 源码 | Vidance 对应 |
|----------|------|-------------|
| 原子写 JSON | `task_artifacts.py`（tempfile+fsync+os.replace） | M4 checkpoint `_save_ckpt` 同款已用 |
| 路径围栏 | `utils/file_security.py`（realpath+commonpath） | buffer `_resolve_within` 等价 |
| 任务状态机（Memory/Redis 双后端） | `state.py`（BaseState 抽象+RLock/Lua HSET） | `core/scheduler.py` tasks.sqlite 已覆盖 |
| JSON 容错/代码块剥离 | `llm.py`（_strip_code_fence+5 次重试） | M4a 修复层+带报错回喂自修 2 次，不逊色 |

## C. 看情况（有价值但优先级低/不适用）

| # | 机制 | 源码 | 评估 |
|---|------|------|------|
| 5 | `stop_at` 中间产物（只出剧本/关键词不出片） | `task.py` stop_at 分阶段 | ask/dialog 部分覆盖；对 LLM 编排链可做 `/script` 命令，约半天 |
| 6 | `think` 块清理（reasoning 模型输出） | `llm.py` | 不用 reasoning 模型，不需要 |
| 7 | API key 多 key 轮换取模 | `material.py` get_api_key | 内网 USTC LLM 单 key，不适用 |
| 8 | 配置热更新（pending 队列+延迟落盘，588 行） | `config/config.py` | 工程漂亮但 config 静态够用 |
| 9 | 跨平台发布（TikTok/IG/YT） | `services` 上传链 | v14 已移交队友，不做 |
| 10 | 音画对齐剪辑（audio_duration+安全余量+clip_speed 反推源时长） | `video.py` combine_videos | 思路可借鉴进 compose；compose 已按配音时长对齐 |

## 其余已读但无动作的模块

- `voice.py`（2319 行）：tts() 前缀协议分发 9 家供应商、静音估算——我们 TTS 结构不同
- `state.py`/`task.py` 进度粒度（5/10/20/30/40）、`_cross_post_executor` 2 worker+BoundedSemaphore 背压——调度规模不同
- `cache_manager.py`：正则白名单防误删+TTL 清理——buffer cleanup 已覆盖

## 执行建议

~~A 档 1→2→3+4 打包一个阶段~~ **已全部实施**（2026-10-13，A1/A2/A3/A4）；#5 看需求单独决定。
