# Toonflow 源码级调研（2026-10-15，复现蓝图）

> 对象：`/mnt/disk_sdb/zxy/Toonflow-app`（v1.1.8，仅服务端；源码提取到 /tmp/opencode/tf-src/）。
> 定位：**小说→剧本→资产→分镜→视频** 的动漫短视频生产 app。Express + Socket.IO + better-sqlite3/Knex + Vercel AI SDK v6；文件式路由（fast-glob 自动注册）；前端合成（后端无 ffmpeg）。
> 结论先行：**最值得抄的是"技能包+检索"体系与七层一致性机制**——前者是我们 M5b RAG 的进阶形态，后者正是 M6 的完整参照实现。

## 1. 架构

- 三层 Agent 组织（16 agent，`o_agentDeploy` 表路由模型，key=`agent` 或 `agent:子agent`）：
  - **scriptAgent**：decision（只派发）→ execution（skeleton 骨架/adaptation 改编策略/script 剧本）→ supervision（只评分不改稿）
  - **productionAgent**：decision / directorPlan / deriveAssets / generateAssets / storyboardTable / storyboardPanel / storyboardGen / supervision
  - **universalAi**：事件提取/资产提取/音色绑定/视频提示词等边缘功能
- 供应商插件：TS 源码存 `data/vendor/{id}.ts`，**sucrase 转译 + VM 沙箱**运行时执行；VideoModel 声明 `mode: singleImage|startEndRequired|…|videoReference:N|imageReference:N|audioReference:N` + `durationResolutionMap`
- 状态机统一模式：生成任务先写"生成中"占位 → 已完成/生成失败+errorReason；`src/lib/fixDB.ts` 启动时把崩溃残留"生成中"批量矫正为失败（健壮性设计，值得抄）

## 2. 端到端流水线

```
小说 →事件提取(universalAi, 信号量并发5, 单行竖线格式防幻觉)→ 事件摘要
  →scriptAgent 三层→ 剧本(o_script, 每集±10s/150字每分/场景≤1000字/△描述=分镜提示词/节奏3-15-45)
  →资产提取(每5集一组, resultTool 强校验 {newAssets, existingAssetRefs}, 按名去重)→ o_assets(role|scene|tool)
  →提示词润色(system=艺术技能md)→ o_assets.prompt
  →资产图生成(四视图/场景/道具, p-limit, o_image 状态机)
  →productionAgent 6阶段: 导演规划→衍生资产分析→衍生资产生成(可选)→分镜表→分镜面板→分镜图生成(仅第4阶段送审)
  →分镜图(资产参考图绑定 o_assets2Storyboard 按 rowid 有序 → base64 referenceList)
  →视频提示词(模型路由: seedance多参/Wan2.6单图/通用多参/通用首尾帧五维)→ o_videoTrack.prompt
  →批量视频生成(o_video 后台状态机) → 音色绑定(AI匹配) → 前端合成
```

## 3. 提示词/技能库（精华逐字）

### 3.1 事件提取防幻觉格式（`src/utils/getPrompts.ts`）
```
## ⚠️ 输出约束（最高优先级，违反任何一条即为失败）
1. 你的**完整回复**只有一行，以 `|` 开头、以 `|` 结尾，恰好 7 个字段
| 第X章 {章节标题} | {涉及角色} | {核心事件} | {主线关系} | {信息密度} | {预估集长} | {情绪强度} |
**预估集长参考**：高密度+高情绪→45-60秒；中→35-45秒；低→25-35秒。
```

### 3.2 分镜表铁律（`data/skills/production_execution_storyboard_table.md`）
- 铁律优先级：**台词零删改 > 出场人物完整 > 只描述动作状态 > 长台词拆镜**；≤15s/片段；>20字台词强制拆镜换视角；4字/秒
- **人物外观交给图片资产——服装/发型/长相不进提示词**；声音只写环境音+音效禁 BGM；动作桥梁过渡

### 3.3 分镜提示词技法（`production_skills/storyboard_prompt_techniques.md`，409 行）
- **内容忠实性原则（最高优先级）**："提示词生成是格式转换，不是创意写作"；逐字段回溯校验，不通过=无效
- **首帧识别**：连续动作取起始凝固态（"挥剑斩下"→"剑已举至头顶即将劈下的瞬间"）
- **三段式结构**：`【画面】(最长)→【光影】(独立成段)→【风格】(最短)`，"风格词篇幅超过画面段即为失败"
- **@图N 资产绑定**：正文角色/场景/道具名全部替换为 `@图N`（绕开名称歧义直接指向参考图）
- **朝向 6 级优先级**：分镜表标注 > 方位词 > 180°视轴线 > 景别暗示 > 情绪语义 > 空间逻辑

### 3.4 分镜表技法（`storyboard_table_techniques.md`）
黄金 6 秒规则；定场≤2镜；一镜到底可破 6s 至 12s；视觉连续性铁律①-⑦（动作连续/景别渐进/180°视轴/朝向逻辑/信息控制/节拍密度/头尾0.5s安全区）；**description 15-50 字禁写光影/色调词**——光影完全由场景资产图承担，特殊光照用场景衍生（夜景版/雨天版）

### 3.5 艺术技能包（`data/skills/art_skills/{风格}/`，每风格一套）
- `prefix.md`：风格基因表 + **色彩三级约束（L1 硬约束肤色/发色/主服底色，L2 软，L3 例外）** + 10 色盘 + 8 行情绪色盘 + 色温容差表（色相±8°/饱和±10%/明度±12%）+ 必守 R1-R5 / 严禁 X1-X6
- `art_character.md`（角色四视图设定图模板，逐字要点）：
  ```
  {性别}角色四视图设定图，{风格锚}，character design sheet，character turnaround，
  {五官特征-由角色描述自然推导}，素颜无妆，{肤色}，{身高}{头身比}{身材}，
  {发色发长}{基础造型}，{角色身份常规着装，柔和低饱和}，
  同一画面左至右并排：人像特写+正视图+侧视图+后视图，
  自然站立，纯净中性灰背景，柔和电影光，四视图一致性，图中不要有任何文字
  ```
- `art_character_derivative.md`（服化叠加 L0底模/L1妆容/L2发型/L3内搭/L4主服/L5鞋履/L6配饰；铁律：面容不变、姿态不变、逐层可控、img2img）
- `art_scene.md`：前/中/后景+空气透视；**严禁出现任何人物**；材质必须有使用痕迹；单画面主视图
- `art_storyboard_video.md`：分镜视频风格标签（多参模式英文版/首尾帧模式/seedance 中文版）
- 导演技能：6 套情绪段落→光影方案映射（A柔和漫射~F柔焦暖光）；乐器组合策略（日常=钢琴+轻吉他）；**配乐覆盖率≤50%，留白比配乐更重要**
- story_skills 按题材（甜宠/热血/悬疑等）各配叙事+分镜技能，如甜宠"推拉节奏模型：靠近→退缩→再靠近→误会→分离→重逢"

### 3.6 技能激活机制（Claude Skills 式渐进披露）
`src/agents/productionAgent/index.ts`：会话启动扫描 art_skills/story_skills/production_skills 的 md（YAML frontmatter name/description）→ 注入 `<available_skills>` XML → agent 按需 `activate_skill(name)` 加载全文。

## 4. 七层一致性机制（M6 的完整参照）

1. 角色四视图设定图（单图承载多视角，作"身份锚"）
2. 衍生资产 img2img 叠加（面容不变、换装不换妆）
3. **分镜提示词不含外观**（外观交给图片资产，规避文字漂移）
4. 分镜图多参考图绑定（o_assets2Storyboard 有序 → referenceList base64；@图N 直指）
5. 镜头间连贯规则（180°视轴/位置锁定/朝向守恒/反射面镜像）
6. **场景光影资产化**（description 禁光影词；夜景/雨天=场景衍生资产）
7. 视频阶段风格锁定（art_storyboard_video 标签注入 + 首尾帧/多参考模式传资产图）

## 5. 数据模型要点（initDB.ts 全表）

- `o_assets`：name/prompt/describe/**type**(role|scene|tool|audio)/**assetsId**(衍生父)/imageId/promptState
- `o_storyboard`：videoDesc/prompt/filePath/duration/track/index/**shouldGenerateImage**/state
- `o_assets2Storyboard`：storyboardId+assetId 联合主键（**有序绑定**）
- `o_video`：filePath/time/videoTrackId + state；`o_videoTrack`：prompt/**selectVideoId**（多候选择优）
- `o_assetsRole2Audio`：角色↔音色 junction（音色也是资产）
- `o_skillList`：md5/path/description/**embedding**/type(main|references)/state —— **技能注册表带嵌入向量**

## 6. 嵌入与技能检索（我们 M5b 的进阶形态）

- 本地 ONNX `all-MiniLM-L6-v2`（fp16）+ mean pooling + L2 归一化，JS 内余弦——**无外部向量库**
- 8 main + 12 references 技能；references 的中文 description 初始化时算嵌入存 `o_skillList.embedding`
- 决策层用**向量检索**决定"派发子任务时附带哪个格式规范文档"
- 记忆系统：每 N 条消息 LLM 压缩摘要（≤500字）；短期 5 + 摘要 10 + RAG 3 + 深检索 5；isolationKey=agent+项目/集数

## 7. 音频/字幕

- TTS 接口齐全但**未接线**——配音靠用户上传；音色绑定走 universalAi 语义匹配（性别/年龄/性格 vs 音色描述）写 `o_assetsRole2Audio`
- `audio:{id}` 可注入多参考视频模型的 audioReference（音色进视频生成）
- 字幕/合成全在前端，后端无可抄代码——我们自有的 TTS/STT/ffmpeg 链路反而是强项

## 8. 复现建议（面向 vidance M6+）

### 值得抄（按优先级）
1. **资产提示词与外观解耦**（分镜 prompt 不写外观，全靠参考图）——配我们 FLUX 参考帧+Wan I2V 链路，直接降低文字漂移
2. **@图N 资产绑定 + 有序 junction 表**——asset_registry 加 storyboard↔assets 绑定表，检索注入时编号引用
3. **场景衍生资产承担光影**（夜景/雨天=场景变体，description 禁光影词）——与 BigBanana consistencyAnchors 互补
4. **三段式提示词结构 + 内容忠实性原则**（画面>光影>风格；"格式转换不是创意写作"）——直接进 M6 提示词模板
5. **首帧识别原则**（连续动作取起始凝固态）——Wan I2V 首帧驱动的正确姿势
6. **supervision 只评分不改稿 + decision 只派发不读数据**——三层 agent 分工，避免审片 agent 顺手改稿引入新问题
7. **技能包渐进披露**（<available_skills> + activate_skill）——SKILL/ 目录已有的思路，升级为"按需加载"，配合 M5b RAG 做语义召回
8. **四视图设定图**（比 BigBanana 九宫格轻：单图四视角，FLUX 可直接照模板出）——角色定妆的中间档方案
9. **fixDB 式启动自愈**（崩溃残留"生成中"批量矫正）——M4 checkpoint 补一条启动扫描
10. **音色作为资产**（o_assetsRole2Audio）——voices 已有 meta，补角色↔音色绑定即可

### 不值得抄
- VM 沙箱 + sucrase 运行时转译供应商插件（我们 vendor 层简单，杀鸡牛刀）
- 前端合成（后端无 ffmpeg——我们后端合成是强项，倒过来）
- TTS 用户上传模式（我们有 CosyVoice 克隆，强得多）
- Socket.IO 实时总线（任务队列+轮询已够用）
- 记忆压缩摘要全套（长对话场景才有价值，当前单任务流水线用不上）
