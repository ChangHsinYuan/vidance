# v16（原 v19）视频处理编辑 — 设计与验证

> v16.x = v16 SAM2 基础 + 生成式编辑增强（M5 FLUX Fill / M6 Union ControlNet / M7 VACE / M8 Qwen-Image-Edit）。
> 本文为论文用汇总：方法脉络、参数、量化验证数据。

## 1. 方法脉络

```
                          ┌─ segment/cutout/replace_bg/mosaic/inpaint（cv2，秒级）
输入图/视频 ──► SAM2 分割 ─┤
                          └─ 生成式编辑（ComfyUI :8192/:8189，分钟级）
                               ├─ M5  FLUX.1 Fill（mask 内重绘 / 反转换底）
                               ├─ M6  + Union ControlNet canny（结构保持）
                               ├─ M7  Wan2.1 VACE（参考图→主体一致视频）
                               └─ M8  Qwen-Image-Edit 2509（整图指令式，中文可用）

分割提示：点提示 → 框提示（大物体更准）→ YOLO 自动框（Grounded-SAM）
视频：SAM2 memory attention 任意帧双向传播（prompt_frame）
```

**两层编辑语义正交**：mask 编辑（SAM 圈哪里改哪里）vs 指令编辑（M8，整图自然语言"把猫换成狗"）。

## 2. 模型与权重

| 模型 | 权重 | 大小 | 位置 | 服务 |
|------|------|------|------|------|
| SAM2 small | sam2_hiera_small | ~180M | transformers 在线 | 进程内（GPU 自动选卡） |
| YOLO | yolov8n | 6M | ultralytics | 进程内 |
| FLUX.1 Fill dev | flux1-fill-dev-fp8.safetensors | 11.9G | /mnt/dataset/zxy/FLUX-ComfyUI/diffusion_models/ | flux :8192 |
| Union ControlNet Pro | flux_shakker_labs_union_pro-fp8_e4m3fn | 3.3G | ComfyUI/models/controlnet/ | flux :8192 |
| Wan2.1 VACE 1.3B | wan2.1_vace_1.3B_fp16.safetensors | 4.3G | /mnt/dataset/zxy/Wan-ComfyUI/diffusion_models/ | wan :8189 |
| Qwen-Image-Edit 2509 | qwen_image_edit_2509_fp8_e4m3fn.safetensors | 20.4G | /mnt/dataset/zxy/FLUX-ComfyUI/diffusion_models/ | flux :8192 |
| Qwen2.5-VL-7B (text) | qwen_2.5_vl_7b_fp8_scaled.safetensors | 9.4G | /mnt/dataset/zxy/FLUX-ComfyUI/text_encoders/ | flux :8192 |

选型：Fill/VACE/Edit 均取 fp8 safetensors（原生 UNETLoader 免装节点，免 GGUF custom_nodes）；VACE text encoder 复用 umt5_xxl（wan2.1/2.2 共用）。

## 3. 关键参数

| 阶段 | 参数 | 值 | 说明 |
|------|------|-----|------|
| FLUX Fill | steps / guidance / cfg | 30 / 30.0 / 1.0 | 官方推荐；euler+simple；denoise=1.0 |
| Fill 换底 | mask 反转 | invert=True | 重绘 mask 外=背景 |
| Union ControlNet | type / strength | canny/lineart/anime_lineart/mlsd / 0.55 | cv2.Canny(100,200) 边缘图 |
| ControlNet 节点 | ControlNetApplyAdvanced | vae 必接 | 普通 Apply 报 "needs a VAE" |
| VACE | width×height / length / strength | 480×832 / 81@16fps / 1.0 | 4n+1 帧补齐；shift=8 |
| Qwen Edit | steps / cfg / 尺寸 | 20 / 2.5 / 16 倍数对齐 | TextEncodeQwenImageEditPlus(image1) |

## 4. 量化验证（测试产物 output/edit_demo/）

### 4.1 M5 FLUX Fill 生成式重绘
| 测试 | 指标 | 值 |
|------|------|-----|
| 去猫（最终 seed42） | YOLO cat | **0.92 → 无检出 ✅**（残留仅 dog 0.39 弱假阳性，木纹阴影误认） |
|  | 猫框内变化 | 69.3%（橙猫 RGB 173,88,65 → 木桌 141,95,63） |
|  | 猫框外变化 | **0.42%**（背景保留） |
| 换底 beach（狗反转 mask） | 背景变化 | **100%**（新色 RGB 104,137,142 海蓝） |
|  | 主体深内部（dist>8px，86% of mask） | 80% 像素不变 |
| 耗时 | 单次 Fill（1536×1024, 30 步） | ~40-60s |

### 4.2 M6 Union ControlNet (canny) 结构保持
| 测试 | 无 ControlNet | canny 0.55 |
|------|--------------|-----------|
| mask 外误伤 | 5.187% | **0.494%（10 倍提升）** |
| mask 内重绘 | 100% | 99.9%（猫→金毛） |

### 4.3 M7 VACE 参考图生视频
| 测试 | 指标 | 值 |
|------|------|-----|
| 方法直调（81 帧） | 输出 | 85 帧@16fps 5.3s 480×832 |
|  | 主体一致性 | **YOLO dog 0.92-0.95 全程在场**；帧 0 与参考图亮度相关 0.831 |
| CLI 端到端（41 帧） | 输出 | 45 帧 2.8s，帧 44 dog 0.91 |

### 4.4 v16 SAM2 基础（保留证据）
- 彩色多物体：8_visualize_color.png / 10_cat_dog_color.png（点）/ 12（YOLO）/ 16_plants_box.png（框，17.5%→46% 覆盖）
- 视频双向传播：cat_dog_fight_edit.mp4 121/121 帧通过（着色 32.9-37.2% 稳定）
- 四操作单测：2_cutout / 3_mosaic / 4_inpaint / 5_replace_bg

### 4.5 M8 Qwen-Image-Edit（代码就绪，权重已下 20.4G+9.4G+0.25G，待测）

## 5. 已知问题与教训

1. **SAM mask 对大物体只盖部分**（首测 18 去猫失败根因）：mask coverage 3.8% vs 猫框 8.3% → 未 mask 部分保持原物。修复：整框矩形 mask 或 box∪SAM 并集；**移除类验证必须 YOLO 复检目标物消失**
2. **Fill 内容感知残留**：旁边有真狗时，木纹阴影被 YOLO 误认成狗（0.39-0.86，seed 方差大）；换 prompt（no animals）无稳定改善，属模型行为
3. **SetUnionControlNetType type 合法值**为组合串（'canny/lineart/anime_lineart/mlsd'），单写 'canny' 不在列表
4. **ControlNetApply 需 VAE**：Union pro 走 ControlNetApplyAdvanced（vae optional 但必须接）
5. **SAM set_image 需 uint8**：float 数组触发 TorchScript TypeError
6. 首帧亮相关低（0.11）是运动镜头正常现象，主体在场用 YOLO 验证
7. 本机多模态模型不支持看图 → 视觉验证全走像素统计 + YOLO 复检

## 6. 代码地图

| 文件 | 内容 |
|------|------|
| agents/post/tools/sam_edit.py | 全部编辑操作 + inpaint_flux（M5/M6）+ qwen_edit（M8）+ CLI |
| agents/generator/tools/comfy_api.py | ComfyClient + generate_flux_fill / generate_vace_video / generate_qwen_edit |
| utils/workflows/flux_fill.json | M5 Fill workflow（InpaintModelConditioning noise_mask） |
| utils/workflows/flux_fill_canny.json | M6 联动（ControlNetApplyAdvanced + SetUnionControlNetType） |
| utils/workflows/wan_vace.json | M7 VACE（WanVaceToVideo reference_image） |
| utils/workflows/qwen_edit.json | M8 指令编辑（TextEncodeQwenImageEditPlus） |
| core/vidance.py | edit 子命令（--engine cv|flux/--prompt/--controlnet）+ vace 子命令 + instruct op |
| core/api_server.py | /api/tool/edit（含 flux 分发）+ /api/tool/vace（异步） |
| utils/sam_edit.py | 薄壳门面（向后兼容） |

CLI：
```bash
python core/vidance.py edit inpaint 图.jpg --box "434,437,739,835" --engine flux \
  --prompt "a wooden kitchen table surface" -o out.png          # M5 mask 内重绘
python core/vidance.py edit replace_bg 图.jpg --box "..." --engine flux \
  --prompt "a sunny beach" -o out.png                            # M5 生成式换底
python core/vidance.py edit inpaint 图.jpg --box "..." --engine flux \
  --prompt "a golden retriever puppy" --controlnet canny \
  --controlnet-strength 0.55 -o out.png                          # M6 结构保持
python core/vidance.py vace ref.png "a dog running on grass" \
  --length 81 -o out.mp4                                         # M7 VACE
python core/vidance.py edit instruct 图.jpg \
  --prompt "把猫换成狗" -o out.png                                # M8 指令编辑
```
