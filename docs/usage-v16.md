# usage-v16 — SAM2 图片/视频编辑 + 生成式编辑（原 v19）

> 三个入口：CLI `python core/vidance.py edit ...` · WebUI `:8894/ui` 输入 `/edit ...` · API `POST /api/tool/edit`
> 设计与实现细节见 [v16-design.md](./v16-design.md)；本文件是上手速查（示例可直接复制）。

## 模型一览（谁在干什么）

| 模型 | 跑在哪 | 干什么 | 什么时候用 |
|------|--------|--------|-----------|
| **SAM2.1 hiera**（tiny/small/base） | 宿主 GPU（自动选卡），权重 `models/sam2/` | 分割：点/框提示 → 二值 mask；视频逐帧追踪（双向传播） | 所有需要"知道物体在哪"的操作 |
| **YOLOv8s**（COCO 80 类） | 宿主 GPU，`models/yolo/yolov8s.pt` | 自动物体检测 → 框提示给 SAM（Grounded-SAM 流程）；移除后复检目标是否消失 | 不想手动找坐标时 |
| **OpenCV TELEA** | CPU（恒可用） | 传统 inpaint：把周围像素"糊"过来补洞 | 快速去水印/小字/小区域（不懂内容，秒级） |
| **FLUX.1-Fill-dev fp8** | flux 8192 | 生成式局部重绘：mask 内按 prompt"画出"内容 | 去物体后要补真实背景、换内容（~1min） |
| **Union ControlNet**（Shakker-Labs pro fp8） | flux 8192 | canny 边缘结构保持重绘 | 改物种但要保留姿态/轮廓 |
| **Qwen-Image-Edit 2509 fp8** | flux 8192 | 指令式编辑：一句话（中文可）整图生效，无需 mask | "把猫换成狗"这类全局改写 |
| **Wan2.1 VACE 1.3B fp16** | wan 8189 | 参考图 → 主体一致视频（480×832@16fps，81 帧内 4n+1）；视频级生成式 inpaint | 角色参考图生视频（M7，`vace` 命令）+ 视频移除/替换物体（`edit video --engine vace`） |

### 服务依赖速查

| 操作 | 依赖 | 不在线时 |
|------|------|---------|
| `segment`/`cutout`/`mosaic`/`visualize`/`replace_bg`（cv）/`inpaint`（cv） | SAM2（宿主，无需 ComfyUI） | — |
| `inpaint`/`replace_bg --engine flux`、`instruct`、`--controlnet canny` | flux 8192 | RuntimeError（cv 引擎可兜底） |
| `video` 全部 op（mosaic/blur_bg/cutout/color） | SAM2（宿主） | — |
| `video --engine vace` | SAM2（宿主）+ wan 8189 | RuntimeError |
| `vace` | wan 8189 | RuntimeError |

---

## 三步上手（30 秒）

```bash
# 1. 找一张图（现成的测试图有猫和狗）
ls output/test_inputs/scene_cat_dog.png

# 2. 先跑 visualize 看物体在哪、是什么颜色（强烈建议第一步）
python core/vidance.py edit output/test_inputs/scene_cat_dog.png visualize

# 3. 按需换操作词：cutout / mosaic / replace_bg / inpaint / instruct
python core/vidance.py edit output/test_inputs/scene_cat_dog.png cutout --point 311,175 -o output/edit_demo/dog_cut.png
```

WebUI 里同理（命令前加 `/`）：`/edit output/test_inputs/scene_cat_dog.png visualize`

### 不知道坐标怎么点？

- **省略 `--point`**：SAM 自动找主体（网格打点并集），最省事
- **`visualize` 先看一眼**：彩色标注画在物体上，物体位置 ≈ 像素坐标（左上角为原点，向右 x 向下 y）
- **加 `--yolo --classes cat`**：YOLO 自动找猫，完全不需要坐标（推荐）

---

## 图编辑七模式

### visualize — 先看后改

彩色多物体可视化（SAM demo 风格 + 标签），不改动图，只看 SAM/YOLO 都认出了什么。

```bash
python core/vidance.py edit 图.jpg visualize                                  # 自动找主体
python core/vidance.py edit 图.jpg visualize --yolo --classes "cat,dog"       # YOLO 自动检测 + 标签
python core/vidance.py edit 图.jpg visualize --box "x1,y1,x2,y2"              # 手动框（大物体比点准）
```

### cutout — 抠主体（透明 PNG）

```bash
python core/vidance.py edit 图.jpg cutout --point 311,175 -o out.png          # 点提示
python core/vidance.py edit 图.jpg cutout -o out.png                          # 省略 = 自动主体
python core/vidance.py edit 图.jpg cutout --yolo --classes dog -o out.png     # YOLO 自动找狗
```

### mosaic — 打码（pixel/blur）

```bash
python core/vidance.py edit 图.jpg mosaic --point x,y --mode pixel            # 像素化（默认）
python core/vidance.py edit 图.jpg mosaic --point x,y --mode blur             # 高斯模糊
python core/vidance.py edit 图.jpg mosaic --yolo --classes person --strength 24   # YOLO 找人，强打码
```

### replace_bg — 换背景（纯色/模糊/生成式）

```bash
python core/vidance.py edit 图.jpg replace_bg --point x,y --bg 101827         # 纯色（hex）
python core/vidance.py edit 图.jpg replace_bg --point x,y --bg blur           # 模糊原图
# 生成式换底（M5，mask 反转重绘背景，需 flux 8192）：
python core/vidance.py edit 图.jpg replace_bg --box "x1,y1,x2,y2" --engine flux --prompt "a sunny beach" -o out.png
```

### inpaint — 去水印/局部填补（cv TELEA 或 FLUX Fill）

```bash
# cv 引擎（默认，秒级，糊填补）：
python core/vidance.py edit 图.jpg inpaint --point x,y -o out.png
# flux 引擎（M5 生成式，mask 内画出 prompt 内容，~1min）：
python core/vidance.py edit 图.jpg inpaint --yolo --classes cat --engine flux --prompt "empty ground" -o out.png
# 改物种保姿态（M6 canny 联动，误伤降 10 倍）：
python core/vidance.py edit 图.jpg inpaint --yolo --classes cat --engine flux --prompt "a golden retriever puppy" --controlnet canny --controlnet-strength 0.55 -o out.png
```

### segment — 只要 mask

```bash
python core/vidance.py edit 图.jpg segment --point 311,175 -o mask.png        # 输出白=物体 黑=背景
```

### instruct — 指令式编辑（中文可用，无需 mask）

M8 Qwen-Image-Edit：一句话全局生效，与 mask 类编辑正交。

```bash
python core/vidance.py edit 图.jpg instruct --prompt "把猫换成金毛犬" -o out.png
python core/vidance.py edit 图.jpg instruct --prompt "把背景换成雪夜森林" -o out.png
python core/vidance.py edit 图.jpg instruct --prompt "给狗戴一顶红色圣诞帽" -o out.png
```

---

## 视频编辑（video）

SAM2 逐帧追踪（任意帧提示 → 双向传播覆盖全片）→ op 处理 → 重拼 mp4。提交后异步执行，WebUI 画布转圈轮询。

```bash
# 打码追踪（首帧点提示）
python core/vidance.py edit 视频.mp4 video --point "x,y" --op mosaic -o out.mp4
# 彩色多物体（每点独立追踪一色，两动物同框帧提示更准）
python core/vidance.py edit 视频.mp4 video --point "x1,y1;x2,y2" --op color --frame 30 -o out.mp4
# YOLO 自动找目标 → 框提示 → 双向追踪
python core/vidance.py edit 视频.mp4 video --yolo --frame 30 --op color -o out.mp4
# 背景虚化 / 抠主体（黑底）
python core/vidance.py edit 视频.mp4 video --point "x,y" --op blur_bg -o out.mp4
python core/vidance.py edit 视频.mp4 video --yolo --classes dog --op cutout -o out.mp4
```

op 一览：`mosaic`（打码）/ `blur_bg`（背景虚化）/ `cutout`（主体抠出，mp4 无 alpha 黑底）/ `color`（彩色多物体可视化）。

### v16.x VACE 生成式视频 inpaint（engine=vace）

SAM2 逐帧 mask → Wan2.1 VACE 视频级生成式重绘——移除/替换物体后画面由模型补全（非黑底/打码），时序一致。需 wan 8189 在线，~5-10 分钟，异步。

```bash
# 移除物体（物体区白=重绘，背景保留；VACE mask 白=重绘该区）
python core/vidance.py edit 视频.mp4 video --yolo --frame 0 --engine vace --mask-op remove --prompt "empty ground" -o out.mp4
# 只保留主体（keep=mask 反转，背景重绘）
python core/vidance.py edit 视频.mp4 video --yolo --frame 0 --engine vace --mask-op keep --prompt "a sunny park" -o out.mp4
# 框提示（YOLO 检不准时手动框）
python core/vidance.py edit 视频.mp4 video --box "x1,y1,x2,y2" --engine vace --prompt "empty ground"
```

要点：`--mask-op remove` 是默认（去掉 mask 内物体）；**VACE mask 语义（像素级实测确认）：mask 白(1)=重绘该区、黑(0)=保留**——remove 直接用 SAM mask（物体白=重绘），keep 才反转。验证口径：**像素级分区差异（狗区应大幅变化、背景应基本不变）+ YOLO 复检**，单靠 YOLO 会被背景重绘干扰误判（实测极性搞反时背景差异 66-101、狗区 28-37 相关 0.85+，YOLO 仍报 4/5 帧消失但狗肉眼可见）。修正后：狗区差异 36-54、背景 12-22，YOLO 4/5 帧消失（残影帧 conf 0.26）。输出 81 帧@16fps（4n+1 补齐，原 24fps 视频会慢放）。

---

## 生成式编辑 v16.x — 什么时候选哪个

| 想干什么 | 用什么 | 示例 |
|---------|--------|------|
| 去掉物体 + 补真实背景 | **M5** FLUX Fill | `edit 图.jpg inpaint --yolo --classes cat --engine flux --prompt "empty ground"` |
| 只去水印/小字（求快） | cv TELEA | `edit 图.jpg inpaint --point x,y` |
| 改物种但保留姿态轮廓 | **M6** +canny | 上例加 `--controlnet canny --controlnet-strength 0.55` |
| 换背景（生成式新场景） | **M5** invert | `edit 图.jpg replace_bg --box "..." --engine flux --prompt "a sunny beach"` |
| 全局改写（中文一句话） | **M8** instruct | `edit 图.jpg instruct --prompt "把猫换成金毛犬"` |
| 参考图生视频 | **M7** vace | `vace ref.png "a dog running on grass" --length 45` |
| **视频**移除物体（生成式补全） | **v16.x** engine=vace | `edit 视频.mp4 video --yolo --engine vace --prompt "empty ground"` |

### vace — 参考图生视频（单独命令）

```bash
python core/vidance.py vace ref.png "a dog running on grass" --length 45 -o out.mp4    # 45帧≈3s
python core/vidance.py vace ref.png "a dog running on grass"                           # 默认 81 帧≈5s
# ⚠️ CLI 默认 480×832 竖屏；要横屏显式传：--width 832 --height 480
```

---

## 新手常见坑

1. **WebUI 命令必须 `/` 前缀**：无 `/` 会被当自然语言发给 LLM 闲聊（如 `/edit 图.jpg visualize` ✓、`edit 图.jpg visualize` ✗）
2. **YOLO classes 铁律**：`--classes` 只认 COCO 80 类英文名（cat/dog/person/potted plant…），写中文不检出
3. **移除类操作用整框矩形 mask**（`--box` 或 `--yolo`）：SAM 点提示 mask 对大物体只盖部分，去不干净；做完用 YOLO 复检目标是否消失
4. **API 参数序与 CLI 相反**：HTTP 分发首 token 是命令名时自动与路径交换（`图.jpg instruct` 和 `instruct 图.jpg` 都通，但写路径在前最稳）
5. **编辑是异步 job**：提交立即返回 job_id，画布转圈 1-2 分钟（图像）/ 5-10 分钟（视频），agent 日志在左侧日志面板实时可见
6. **flux 引擎需要 8192 在线**：`--engine flux`/`instruct`/`--controlnet` 都走 flux 实例；cv 引擎不需要
7. **vace 尺寸坑**：CLI 默认 480×832 竖屏，API 默认 832×480 横屏，混用时显式传 `--width/--height`
8. **产出不覆盖**：已有路径自动加序号，放心反复跑

---

## API / 前端

```bash
# API（注意 args 里参数序：路径在前）
curl -X POST http://127.0.0.1:8894/api/tool/edit -H 'Content-Type: application/json' \
  -d '{"args":"output/test_inputs/scene_cat_dog.png instruct --prompt 把猫换成金毛犬"}'
# 返回 {job_id, poll...}，轮询：
curl http://127.0.0.1:8894/api/h3shot/{job_id}

# 前端 :8894/ui
/edit output/test_inputs/scene_cat_dog.png visualize      # 命令必须 / 前缀
/vace output/test_inputs/_vace_ref_dog.png "a dog running on grass"
/help edit                                                # 查看全部 19+ 条示例
```
