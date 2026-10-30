# v17 使用指南 — 会话资产层 / 断点续跑 / RAG / 五维模板 / 嵌入 / 重试

> v17（原 v12 规划）整合开源项目工程能力。七个里程碑全部完成（2026-10-30 关版）。
> 设计文档：[v17-design.md](../design/v17-design.md) · 状态权威：[roadmap.md](../roadmap.md) §v17

## M1-M3 会话资产层（buffer + 附件 + @ 引用）

### 上传与归档

```bash
# 上传文件入会话缓冲区（multipart，session_id 必带）
curl -X POST "http://127.0.0.1:8894/api/upload?session_id=demo" -F "file=@参考图.png"
# → {asset_id, path, url, name, size, sha256, is_ref}

# 列会话资产
curl "http://127.0.0.1:8894/api/assets?session_id=demo"

# 产物归档（引用式，不拷贝 output/ 成片）
curl -X POST http://127.0.0.1:8894/api/assets/archive \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"demo","path":"output/xxx/final.mp4"}'

# 删除单个资产（被引用返回 409，可 --force）/ 整会话（联动删 uploads+引用，成片不动）
curl -X DELETE "http://127.0.0.1:8894/api/assets/{id}?session_id=demo"
curl -X DELETE "http://127.0.0.1:8894/api/session/demo"
```

- 存储位置：`output/buffer/{session_id}/uploads/`（真文件）；TTL 7 天守护线程兜底清理
- 前端：`:8894/ui` 📎 按钮 / 拖拽 / 粘贴上传 → chip（@N 序号）；产物卡「📥 存入 buffer」

### @ 引用

```bash
# 命令/自然语言中 @N 按附件顺序替换为 buffer 绝对路径（服务端完成，防注入）
curl -X POST http://127.0.0.1:8894/api/tool/clip \
  -H 'Content-Type: application/json' \
  -d '{"args":"用 @1 生成视频"}'   # @1 → 第 1 个附件
```

### M6 产物归档（novel2video 管线配套）

```bash
# 拆解 JSON/成片/字幕/prompt 清单/拼贴图 一键引用式归档（幂等，按 name+sha 去重）
python input/rag_test/m6_archive_buffer.py m6_kongyiji_v3
```

## M4 断点续跑 + JSON 容错

```bash
# 常规跑（自动生成 task_id，checkpoint.json 实时落 output/{task_id}/）
python core/vidance.py auto "深海探险" --character "蓝色水母" --character-mode flux

# 中断后续跑：跳过已缓存阶段（编剧/prompts/角色）+ 逐镜复用（sha256 指纹校验，
# 产物被篡改/缺失自动重做；概念可省略，从 checkpoint 取）
python core/vidance.py auto --resume {task_id}

# 黑板步进记录（agent_runs 表，m4:script/prompts/character/clip:N/done）
curl "http://127.0.0.1:8894/api/tasks/{task_id}/trace"
```

实现要点：checkpoint 原子写（fsync+os.replace，崩溃半文件自动重建）；`utils/llm.py`
统一出口带 JSON 容错（markdown 栅栏剥离/尾逗号）+ 失败回喂重问 + max_tokens 16384。

## M5 五维提示词模板 + RAG

### 模板（SKILL/templates/ 资产化）

```bash
# cinematic / documentary / anime90s / guofeng 四模板（五维词汇域约束 + style_pack 风格包）
python core/vidance.py auto "概念" --template cinematic
```

模板 YAML 结构：`five_dim_guide`（visual/motion/camera/audio/narrative 注入编剧）
+ 可选 `style_pack`（style_anchor 等锚点直接覆盖 LLM 生成）。新模板落
`SKILL/templates/{name}.yaml` 即被 SkillManager 发现，无需改代码。

### RAG（长文本参考 + 小说拆解）

```bash
# 文档入索引（md5 缓存去重）→ 检索
python core/vidance.py rag add 文档.md --novel     # 小说路线：分章+人物卡
python core/vidance.py rag search "华老栓买了什么"  # chunk 级检索
python core/vidance.py rag ask "孔乙己的外貌"       # 问答（注入人物卡）

# 编剧时引用
python core/vidance.py auto "孔乙己的故事" --rag-doc input/nahan.txt --rag-novel
```

已知局限：聚合类问题（"列举所有角色"）chunk 检索必挂——走 `rag ask` 注入人物卡路线。

## M7 嵌入 + 重试

### 本地语义嵌入（MiniLM ONNX，无外网可复现）

```python
from utils.embed_index import EmbedIndex
idx = EmbedIndex(dim=384)
idx.add(['asset 描述文本', ...])          # 增量，npz 持久化
idx.save('output/asset_index.npz')
hits = idx.search('query', topk=5)        # 暴力余弦，资产量级 <1e4 不引 faiss
```

模型：`/mnt/dataset/zxy/hf_cache/all-MiniLM-L6-v2/onnx/model_qint8.onnx`（23MB），
经 hf-mirror curl 直下；缺失时延迟报错不阻塞 import。中文语义仍走 bge/RagIndex。

### 重试标准化（tenacity）

```python
from utils.retry import retry_net, RetryableError

@retry_net('llm')   # 指数退避 3 次（2/8/32s）；'tts'=2s×3；'comfy'=10s×2
def call_api():
    ...             # 5xx/429/网络类自动重试；4xx/404 直抛不重试
```

## novel2video（M6 管线技能，小说→成片）

```bash
# 档1 拆解：小说章节 → 角色/场景/道具/分镜 JSON（流式 ~15min，幂等）
python SKILL/commands/novel2video/m6_breakdown_test.py

# 档3 全链路渲染：拆解 JSON → FLUX 关键帧 → Wan I2V → TTS → 慢放/KenBurns/xfade
#     → SRT 字幕 → yuv420p 终拼（Windows 兼容铁律）
python SKILL/commands/novel2video/m6_render_v3.py                # 8 关键镜子集
M6_ALL=1 python SKILL/commands/novel2video/m6_render_v3.py       # 全量镜头（M6_ALL=1）

# 产物归档 buffer
python SKILL/commands/novel2video/m6_archive_buffer.py {session_id}
```

硬约束（详见 SKILL/commands/novel2video/README.md）：FLUX 只吃英文 prompt（LLM 中译英）；
一律 I2V 禁裸 T2V；TTS 用 cosy-default（克隆音色有幻听风险）；每环节显式
`-pix_fmt yuv420p -profile:v high`；成片必须烧字幕；prompts.md 落盘可追溯。
