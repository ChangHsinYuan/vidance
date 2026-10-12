#!/usr/bin/env python3
"""v16 视频处理与编辑 — SAM2 分割 + 局部替换（M1 分割 / M2 inpaint / M3 视频传播）

单图编辑（M1/M2）：
  segment       任意图 → mask（点提示/自动主体）
  cutout        抠主体 → 透明 PNG
  replace_bg    换背景（纯色/模糊原图）
  mosaic        区域打码（像素化/模糊）
  inpaint       局部替换/去水印（SAM mask → cv2.inpaint，CPU 恒可用）

视频编辑（M3）：
  video         SAM2 视频传播：首帧点提示 → 逐帧 mask → 打码/换底/抠图 → 重拼 mp4

用法:
  python agents/post/tools/sam_edit.py segment 图.jpg --point 311,175 -o mask.png
  python agents/post/tools/sam_edit.py cutout 图.jpg -o cut.png                # 自动主体
  python agents/post/tools/sam_edit.py mosaic 图.jpg --point x,y --mode pixel
  python agents/post/tools/sam_edit.py inpaint 图.jpg --point x,y -o out.png  # 去水印/替换
  python agents/post/tools/sam_edit.py video in.mp4 --point x,y --op mosaic -o out.mp4
"""

import os as _os
import sys as _sys
_ROOT = _os.path.abspath(__file__)
for _ in range(4):
    _ROOT = _os.path.dirname(_ROOT)
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
import argparse
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np
from PIL import Image

FFMPEG = 'ffmpeg'
FFPROBE = 'ffprobe'

# 权重/配置（models/sam2/ 下，*.pt 已 gitignore）
_MODELS = {
    'small': ('sam2.1_hiera_small.pt', 'configs/sam2.1/sam2.1_hiera_s.yaml'),
    'tiny': ('sam2.1_hiera_tiny.pt', 'configs/sam2.1/sam2.1_hiera_t.yaml'),
    'base': ('sam2.1_hiera_base_plus.pt', 'configs/sam2.1/sam2.1_hiera_b+.yaml'),
}
_SAM2_SRC_CANDIDATES = [
    '/mnt/disk_sdb/zxy/sam2-src',        # 本仓永久位置（pip -e 装的就是它）
]
GPU_FALLBACK = True   # CUDA 建不出 context 时逐卡探测（同 v4 FunClip device='auto'）


# ────────────────────────── 模型加载 ──────────────────────────

def _pick_device(prefer: str = ''):
    """选卡：prefer 指定（cuda:N/cpu）> 逐卡探测显存最多且可用 > cpu。"""
    try:
        import torch
    except ImportError:
        return 'cpu'
    if prefer:
        return prefer
    if not torch.cuda.is_available():
        return 'cpu'
    best, best_free = None, -1
    for i in range(torch.cuda.device_count()):
        try:
            free, _total = torch.cuda.mem_get_info(i)
            if free > best_free:
                best, best_free = f'cuda:{i}', free
        except Exception:
            continue  # context 建不出（满卡）→ 跳过
    return best or 'cpu'


def load_predictor(size: str = 'small', device: str = '', video: bool = False):
    """SAM2 图像/视频 predictor（单例缓存）。size: tiny/small/base。"""
    cache_key = ('video' if video else 'image', size, device)
    if cache_key in load_predictor._cache:
        return load_predictor._cache[cache_key]

    src = None
    for c in _SAM2_SRC_CANDIDATES:
        if os.path.isdir(c):
            src = c
            break
    if src and src not in sys.path:
        sys.path.insert(0, src)

    from sam2.build_sam import build_sam2
    fname, cfg = _MODELS[size]
    ckpt = os.path.join(_ROOT, 'models', 'sam2', fname)
    if not os.path.isfile(ckpt):
        raise FileNotFoundError(f'SAM2 权重不存在: {ckpt}（下载 dl.fbaipublicfiles.com/segment_anything_2/092824/{fname}）')

    dev = _pick_device(device)
    t0 = time.time()
    model = build_sam2(cfg, ckpt, device=dev)
    if video:
        from sam2.build_sam import build_sam2_video_predictor
        pred = build_sam2_video_predictor(cfg, ckpt, device=dev)
    else:
        from sam2.sam2_image_predictor import SAM2ImagePredictor
        pred = SAM2ImagePredictor(model)
    load_predictor._cache[cache_key] = (pred, dev)
    print(f'[sam2] {size} 加载 {time.time()-t0:.1f}s device={dev}')
    return pred, dev


load_predictor._cache = {}


# ────────────────────────── M1: 分割 ──────────────────────────

def parse_points(spec):
    """'x,y x,y' 或 'x,y;x,y' → [(x,y), ...]"""
def parse_points(spec):
    """'x,y;x2,y2' 或 'x,y x2,y2' → [(x,y)]。"""
    pts = []
    for tok in (spec or '').replace(';', ' ').split():
        parts = tok.split(',')
        if len(parts) == 2:
            try:
                pts.append((int(float(parts[0])), int(float(parts[1]))))
            except ValueError:
                pass
    return pts


def parse_boxes(spec):
    """'x1,y1,x2,y2;x1,y1,x2,y2' → [(x1,y1,x2,y2)]。"""
    boxes = []
    for tok in (spec or '').replace(';', ' ').split():
        parts = tok.split(',')
        if len(parts) == 4:
            try:
                boxes.append(tuple(int(float(v)) for v in parts))
            except ValueError:
                pass
    return boxes


# ────────────────────────── YOLO 自动物体检测（Grounded-SAM 流程）──────────────────────────

_YOLO_WEIGHTS = [
    'models/yolo/yolov8s.pt',      # 主（vidance/models/yolo/）
    'yolov8s.pt',                  # 兜底（仓根，早期手工下载）
]


def detect_objects(img, classes=None, conf=0.25, weights=''):
    """YOLO 自动物体检测（--yolo 模式）。

    classes: 类别名列表（COCO 80 类，如 ['cat','dog']）None=全部。
    Returns [(label, conf, (x1,y1,x2,y2))] 按置信度降序。
    """
    from ultralytics import YOLO
    w = weights
    if not w:
        for c in _YOLO_WEIGHTS:
            if os.path.exists(c):
                w = c
                break
    if not w or not os.path.exists(w):
        raise RuntimeError('找不到 YOLO 权重（models/yolo/yolov8s.pt），'
                           'bash deploy/download_weights.sh 下载')
    y = YOLO(w)
    img8 = np.ascontiguousarray(img[..., ::-1])  # RGB→BGR，负 stride 修复
    r = y(img8, conf=conf, verbose=False)[0]
    dets = []
    for b in r.boxes:
        label = r.names[int(b.cls)]
        if classes and label not in classes:
            continue
        x1, y1, x2, y2 = [int(v) for v in b.xyxy[0].tolist()]
        dets.append((label, float(b.conf), (x1, y1, x2, y2)))
    dets.sort(key=lambda t: -t[1])
    return dets


def segment_image(img, points=None, size='small', device=''):
    """单图分割。points: [(x,y)] 点提示；None → 自动主体（网格打点取最优掩膜并集）。

    Returns (mask_bool HxW, score float)
    """
    predictor, dev = load_predictor(size=size, device=device)
    predictor.set_image(img)
    h, w = img.shape[:2]

    if points:
        coords = np.array(points, dtype=np.float32)
        labels = np.ones(len(points), dtype=np.int64)
    else:
        # 自动主体：3x3 网格点提示，各自预测取 score 最高且面积合理的掩膜
        coords, labels = [], []
        for fy in (0.3, 0.5, 0.7):
            for fx in (0.3, 0.5, 0.7):
                coords.append((int(w * fx), int(h * fy)))
                labels.append(1)
        coords = np.array(coords, dtype=np.float32)
        labels = np.array(labels, dtype=np.int64)

    masks, scores, _ = predictor.predict(point_coords=coords, point_labels=labels)
    if len(masks) == 0:
        raise RuntimeError('SAM2 未产出掩膜')

    if points:
        best = int(np.argmax(scores))
        return masks[best].astype(bool), float(scores[best])

    # 自动：并集所有 score>0.7 的掩膜（多点同目标）——退化为最高分掩膜兜底
    good = [masks[i] for i in range(len(masks)) if scores[i] > 0.7]
    if not good:
        best = int(np.argmax(scores))
        return masks[best].astype(bool), float(scores[best])
    union = np.zeros(img.shape[:2], dtype=bool)
    for m in good:
        union |= m.astype(bool)
    return union, float(np.max(scores))


# ────────────────────────── M1: 编辑操作 ──────────────────────────

def cutout(img, mask, out_path):
    """抠主体 → 透明 PNG。"""
    rgba = np.dstack([img, np.where(mask, 255, 0).astype(np.uint8)])
    Image.fromarray(rgba, 'RGBA').save(out_path)
    return out_path


def replace_bg(img, mask, out_path, color=(16, 18, 27), blur=False):
    """换背景：纯色（默认深色）或高斯模糊原图。"""
    if blur:
        import cv2
        bg = cv2.GaussianBlur(img, (0, 0), 18)
    else:
        bg = np.zeros_like(img)
        bg[:] = color
    out = np.where(mask[..., None], img, bg)
    Image.fromarray(out.astype(np.uint8)).save(out_path)
    return out_path


def mosaic(img, mask, out_path, mode='pixel', strength=16):
    """区域打码：pixel 像素化 / blur 高斯。mask 外不动。"""
    import cv2
    small = cv2.resize(img, (max(1, img.shape[1] // strength), max(1, img.shape[0] // strength)),
                       interpolation=cv2.INTER_LINEAR)
    pix = cv2.resize(small, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
    blurred = cv2.GaussianBlur(img, (0, 0), strength)
    alt = pix if mode == 'pixel' else blurred
    out = np.where(mask[..., None], alt, img)
    Image.fromarray(out.astype(np.uint8)).save(out_path)
    return out_path


# ────────────────────────── M2: inpaint 局部替换 ──────────────────────────

def inpaint(img, mask, out_path, radius=6):
    """局部替换/去水印：cv2.inpaint TELEA（CPU 恒可用，快速）。

    大面积重绘质量有限——FLUX Fill 模型上线后可切 ComfyUI latent inpaint（可选）。
    """
    import cv2
    m = (mask.astype(np.uint8)) * 255
    # mask 膨胀 1 圈，覆盖边缘水印残迹
    m = cv2.dilate(m, np.ones((5, 5), np.uint8), iterations=1)
    out = cv2.inpaint(img, m, radius, cv2.INPAINT_TELEA)
    Image.fromarray(out).save(out_path)
    return out_path


# ────────────────────────── M5: FLUX.1 Fill 生成式重绘 ──────────────────────────

def inpaint_flux(img, mask, prompt, out_path, invert=False, steps=30, guidance=30.0,
                 controlnet='', controlnet_strength=0.5, host='', port=0, timeout=900):
    """FLUX.1 Fill 生成式局部重绘：SAM mask + prompt → 重绘区域内容（ComfyUI :8192）。

    invert=True 时重绘 mask 之外（replace_bg 生成式换底，如 "beach"）。
    controlnet='canny' → Union ControlNet 结构保持重绘（v16.x M6：改物种保持姿态轮廓）。
    flux 不可达/失败 → 抛 RuntimeError（调用方自行降级 cv2.inpaint）。
    """
    from agents.generator.tools.comfy_api import ComfyClient
    tmp_dir = os.path.dirname(out_path) or '.'
    ts = time.strftime('%H%M%S%f')
    img_png = os.path.join(tmp_dir, f'_fill_in_{ts}.png')
    mask_png = os.path.join(tmp_dir, f'_fill_mask_{ts}.png')
    canny_png = ''
    try:
        Image.fromarray(img).save(img_png)
        m = mask.astype(np.uint8)
        if invert:
            m = 1 - m
        Image.fromarray(m * 255).save(mask_png)
        kw = {}
        if host:
            kw['host'] = host
        if port:
            kw['port'] = port
        canny_path = None
        if controlnet == 'canny':
            import cv2
            g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            edges = cv2.Canny(g, 100, 200)
            canny_path = os.path.join(tmp_dir, f'_fill_canny_{ts}.png')
            Image.fromarray(edges).save(canny_path)
            canny_png = canny_path
        client = ComfyClient(instance='flux', **kw)
        r = client.generate_flux_fill(img_png, mask_png, prompt, steps=steps,
                                      guidance=guidance, canny_path=canny_path,
                                      canny_strength=controlnet_strength,
                                      output_path=out_path)
        print(f"[flux-fill] prompt_id={r['prompt_id']} seed={r['seed']} steps={steps} "
              f"guidance={guidance} controlnet={controlnet or 'none'}")
        return out_path
    finally:
        for t in (img_png, mask_png, canny_png):
            if not t:
                continue
            try:
                os.remove(t)
            except OSError:
                pass


# ────────────────────────── Qwen-Image-Edit 指令式编辑 ──────────────────────────

def qwen_edit(img_path, instruction, out_path, steps=20, cfg=2.5):
    """Qwen-Image-Edit 2509 指令式编辑：原图 + 自然语言指令（中文可用）→ 编辑图（flux :8192）。

    与 SAM mask 编辑正交：整图指令式修改（如"把猫换成狗"），无需 mask。
    flux 不可达/失败 → 抛 RuntimeError（调用方自行降级）。
    """
    from agents.generator.tools.comfy_api import ComfyClient
    client = ComfyClient(instance='flux')
    r = client.generate_qwen_edit(img_path, instruction, steps=steps, cfg=cfg,
                                  output_path=out_path)
    print(f"[qwen-edit] prompt_id={r['prompt_id']} seed={r['seed']} steps={steps} cfg={cfg}")
    return out_path


# ────────────────────────── 彩色多物体可视化 ──────────────────────────

# SAM demo 风格调色板（高饱和区分色）
PALETTE = [(255, 76, 76), (76, 195, 255), (120, 255, 96), (255, 200, 64),
           (196, 110, 255), (64, 240, 224), (255, 128, 220), (176, 255, 64)]


def _iou(a, b):
    inter = (a & b).sum()
    union = (a | b).sum()
    return inter / union if union else 0.0


def segment_multi(img, points=None, size='small', device='', grid=3, iou_dedupe=0.85):
    """彩色多物体分割：每个点一个独立物体，逐点预测去重。

    points None → grid x grid 网格自动打点。
    Returns (masks[list of bool HxW], scores[list of float])
    """
    predictor, _dev = load_predictor(size=size, device=device)
    predictor.set_image(img)
    h, w = img.shape[:2]

    if not points:
        points = [(int(w * (i + 1) / (grid + 1)), int(h * (j + 1) / (grid + 1)))
                  for j in range(grid) for i in range(grid)]

    masks, scores = [], []
    for pt in points:
        try:
            ms, ss, _ = predictor.predict(
                point_coords=np.array([pt], dtype=np.float32),
                point_labels=np.ones(1, dtype=np.int64))
        except Exception:
            continue
        best = int(np.argmax(ss))
        m = ms[best].astype(bool)
        if ss[best] < 0.5 or m.sum() < 16:
            continue  # 噪声/过小丢弃
        if any(_iou(m, kept) > iou_dedupe for kept in masks):
            continue  # 与已有物体重复
        masks.append(m)
        scores.append(float(ss[best]))
    return masks, scores


def visualize(img, masks, out_path, alpha=0.55, labels=None):
    """彩色多物体叠加（SAM demo 风格：每物体一色 + 半透明 + 边界描边）。

    labels: 类别名（YOLO 模式）→ 物体左上角画标签。
    """
    import cv2
    out = img.copy()
    for i, m in enumerate(masks):
        color = PALETTE[i % len(PALETTE)]
        out[m] = (out[m] * (1 - alpha) + np.array(color) * alpha).astype(np.uint8)
        # 边界描边（mask 边缘找轮廓）
        edges = m.astype(np.uint8) - cv2.erode(m.astype(np.uint8), np.ones((3, 3), np.uint8))
        out[edges.astype(bool)] = color
        if labels and i < len(labels):
            ys, xs = np.where(m)
            if len(ys):
                pos = (int(xs.min()), max(14, int(ys.min()) - 4))
                cv2.putText(out, labels[i], pos, cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                            (255, 255, 255), 2)
                cv2.putText(out, labels[i], pos, cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                            color, 1)
    Image.fromarray(out).save(out_path)
    return out_path


def segment_from_boxes(img, boxes, labels=None, size='small', device='', iou_dedupe=0.85):
    """框提示分割（Grounded-SAM：YOLO 框 → SAM2 精分割）：每框一个独立物体。

    boxes: [(x1,y1,x2,y2)]；labels: 对应类别名（None=自动编号）。
    Returns (masks[list of bool HxW], scores[list of float], labels[list of str])
    """
    predictor, _dev = load_predictor(size=size, device=device)
    predictor.set_image(img)
    if labels is None:
        labels = ['物体%d' % (i + 1) for i in range(len(boxes))]
    masks, scores, out_labels = [], [], []
    for box, label in zip(boxes, labels):
        try:
            ms, ss, _ = predictor.predict(
                box=np.array(box, dtype=np.float32))
        except Exception:
            continue
        best = int(np.argmax(ss))
        m = ms[best].astype(bool)
        if ss[best] < 0.5 or m.sum() < 16:
            continue
        if any(_iou(m, kept) > iou_dedupe for kept in masks):
            continue
        masks.append(m)
        scores.append(float(ss[best]))
        out_labels.append(label)
    return masks, scores, out_labels


def video_color(in_path, out_path, points, size='small', device='', alpha=0.55,
                on_frame=None, prompt_frame=0, boxes=None):
    """视频彩色多物体：每个点/框一个独立 obj_id 传播 → 逐帧彩色叠加（SAM demo 风格）。

    points: [(x,y)] 或 boxes: [(x1,y1,x2,y2)]（优先 box）。
    prompt_frame：提示帧索引（SAM2 支持任意帧提示，双向传播）。
    """
    import torch
    import cv2

    predictor, dev = load_predictor(size=size, device=device, video=True)

    tmpd = tempfile.mkdtemp(prefix='sam2vid_')
    fps = _probe_fps(in_path)
    subprocess.run([FFMPEG, '-y', '-i', in_path, '-vf',
                    'scale=trunc(iw/2)*2:trunc(ih/2)*2',
                    os.path.join(tmpd, '%06d.jpg'), '-q:v', '2'],
                   capture_output=True, text=True, timeout=300)
    names = sorted(f for f in os.listdir(tmpd) if f.endswith('.jpg'))
    if not names:
        raise RuntimeError('抽帧失败')

    with torch.inference_mode(), torch.autocast('cuda', dtype=torch.bfloat16,
                                                enabled=dev.startswith('cuda')):
        state = predictor.init_state(video_path=tmpd)
        f0 = cv2.imread(os.path.join(tmpd, names[min(prompt_frame, len(names) - 1)]))
        fh, fw = f0.shape[:2]
        # 优先框提示（每框一物体），否则每点一物体（obj_id 1..n）
        for k, (x1, y1, x2, y2) in enumerate(boxes or [], start=1):
            predictor.add_new_points_or_box(
                state, obj_id=k, frame_idx=prompt_frame,
                box=np.array([min(max(x1, 0), fw - 1), min(max(y1, 0), fh - 1),
                              min(max(x2, 0), fw - 1), min(max(y2, 0), fh - 1)],
                             dtype=np.float32))
        if not boxes:
            for k, (x, y) in enumerate(points, start=1):
                predictor.add_new_points_or_box(
                    state, obj_id=k, frame_idx=prompt_frame,
                    points=np.array([[(min(max(x, 0), fw - 1), min(max(y, 0), fh - 1))]],
                                    dtype=np.float32),
                    labels=np.ones((1, 1), dtype=np.int64))
        # 多物体传播：propagate 产出 (frame, [obj_ids], [logits])
        # 双向传播：提示帧向后 + 向前（reverse=True），覆盖全片
        masks_by_frame = {}
        for reverse in (False, True):
            for fo, obj_ids, logits in predictor.propagate_in_video(state,
                                                                    reverse=reverse):
                d = masks_by_frame.get(fo, {})
                for oi, oid in enumerate(obj_ids):
                    m = (logits[oi] > 0).cpu().numpy()
                    if m.ndim == 3:
                        m = m[0]
                    d[int(oid)] = m.astype(bool)
                masks_by_frame[fo] = d

    total = len(names)
    frames_src = {fo: os.path.join(tmpd, n) for fo, n in enumerate(names)}

    def _iter():
        for fo in range(total):
            img = cv2.cvtColor(cv2.imread(frames_src[fo]), cv2.COLOR_BGR2RGB)
            per_obj = masks_by_frame.get(fo) or {}
            out = img.copy()
            for oid, m in per_obj.items():
                if not m.any():
                    continue
                m = np.array(Image.fromarray(m.astype(np.uint8) * 255).resize(
                    (img.shape[1], img.shape[0]), Image.NEAREST)) > 127
                color = np.array(PALETTE[(oid - 1) % len(PALETTE)])
                out[m] = (out[m] * (1 - alpha) + color * alpha).astype(np.uint8)
                edges = m.astype(np.uint8) - cv2.erode(m.astype(np.uint8), np.ones((3, 3), np.uint8))
                out[edges.astype(bool)] = color
            yield out

    try:
        n = _encode_frames(_iter(), out_path, fps, total=total, on_frame=on_frame)
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)
    return {'output': out_path, 'frames': n, 'fps': fps,
            'objects': len(boxes or []) or len(points)}


# ────────────────────────── M3: 视频传播 ──────────────────────────

def _probe_fps(path):
    try:
        r = subprocess.run([FFPROBE, '-v', 'error', '-select_streams', 'v:0',
                            '-show_entries', 'stream=r_frame_rate', '-of', 'csv=p=0', path],
                           capture_output=True, text=True, timeout=30)
        num, den = r.stdout.strip().split('/')
        return int(num) / int(den) if int(den) else 24.0
    except Exception:
        return 24.0


def _encode_frames(frames_iter, out_path, fps, total=0, on_frame=None):
    """PNG 流 → mp4（image2pipe，同 v13/v15 blender_pipeline.frames_to_mp4 模式）。"""
    cmd = [FFMPEG, '-y', '-f', 'image2pipe', '-vcodec', 'png', '-framerate', str(fps),
           '-i', '-', '-vcodec', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
           out_path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE)
    n = 0
    try:
        for f in frames_iter:
            buf = _png_bytes(f)
            try:
                proc.stdin.write(buf)
            except BrokenPipeError:
                err = proc.stderr.read().decode('utf-8', 'ignore')[-400:]
                raise RuntimeError(f'ffmpeg 中途退出: {err}')
            n += 1
            if on_frame:
                on_frame(n, total)
    finally:
        if proc.stdin and not proc.stdin.closed:
            try:
                proc.stdin.close()
            except BrokenPipeError:
                pass
        rc = proc.wait()
    if rc != 0:
        err = proc.stderr.read().decode('utf-8', 'ignore')[-400:]
        raise RuntimeError(f'ffmpeg 退出码 {rc}: {err}')
    return n


def _png_bytes(arr):
    b = io.BytesIO()
    Image.fromarray(arr).save(b, format='PNG')
    return b.getvalue()


def video_edit(in_path, out_path, points, op='mosaic', size='small', device='',
               mode='pixel', strength=16, bg_color=(16, 18, 27), on_frame=None,
               prompt_frame=0, boxes=None):
    """SAM2 视频传播：点/框提示 → 逐帧 mask → op 处理 → 重拼 mp4。

    op: mosaic / blur_bg / cutout（cutout 输出 mp4 无 alpha，黑底）
    prompt_frame：提示帧索引（SAM2 支持任意帧提示，双向传播）。
    boxes: [(x1,y1,x2,y2)] 框提示（优先，obj_id=1）。
    """
    import torch
    import cv2
    from sam2.build_sam import build_sam2

    predictor, dev = load_predictor(size=size, device=device, video=True)

    # 抽帧到临时目录（jpeg 快）
    tmpd = tempfile.mkdtemp(prefix='sam2vid_')
    fps = _probe_fps(in_path)
    extract = subprocess.run([FFMPEG, '-y', '-i', in_path, '-vf',
                              'scale=trunc(iw/2)*2:trunc(ih/2)*2',
                              os.path.join(tmpd, '%06d.jpg'), '-q:v', '2'],
                             capture_output=True, text=True, timeout=300)
    names = sorted(f for f in os.listdir(tmpd) if f.endswith('.jpg'))
    if not names:
        raise RuntimeError(f'抽帧失败: {extract.stderr[-200:]}')

    # 推理（inference_state 上下文）
    with torch.inference_mode(), torch.autocast('cuda', dtype=torch.bfloat16,
                                                enabled=dev.startswith('cuda')):
        state = predictor.init_state(video_path=tmpd)
        # 提示帧加点/框提示（优先 box），obj_id=1
        frame0 = cv2.imread(os.path.join(tmpd, names[min(prompt_frame, len(names) - 1)]))
        fh, fw = frame0.shape[:2]
        if boxes:
            b = boxes[0]
            predictor.add_new_points_or_box(
                state, obj_id=1, frame_idx=prompt_frame,
                box=np.array([min(max(b[0], 0), fw - 1), min(max(b[1], 0), fh - 1),
                              min(max(b[2], 0), fw - 1), min(max(b[3], 0), fh - 1)],
                             dtype=np.float32))
        else:
            pts = np.array([[(min(max(x, 0), fw - 1), min(max(y, 0), fh - 1)) for x, y in points]],
                           dtype=np.float32)
            labels = np.ones((1, len(points)), dtype=np.int64)
            predictor.add_new_points_or_box(state, obj_id=1, frame_idx=prompt_frame,
                                            points=pts, labels=labels)

        # 传播（双向：提示帧向后 + 向前，覆盖全片）
        masks_by_frame = {}
        for reverse in (False, True):
            for fo, obj_ids, mask_logits in predictor.propagate_in_video(state,
                                                                        reverse=reverse):
                m = (mask_logits[0] > 0).cpu().numpy()
                if m.ndim == 3:
                    m = m[0]
                masks_by_frame[fo] = m.astype(bool)

    total = len(names)
    frames_src = {fo: os.path.join(tmpd, n) for fo, n in enumerate(names)}

    def _iter():
        for fo in range(total):
            img = cv2.imread(frames_src[fo])
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            m = masks_by_frame.get(fo)
            if m is None or not m.any():
                yield img
                continue
            m = np.array(Image.fromarray(m.astype(np.uint8) * 255).resize(
                (img.shape[1], img.shape[0]), Image.NEAREST)) > 127
            if op == 'mosaic':
                yield np.where(m[..., None],
                               cv2.resize(cv2.resize(img, (img.shape[1] // max(1, strength),
                                                                  img.shape[0] // max(1, strength))),
                                          (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST),
                               img).astype(np.uint8)
            elif op == 'blur_bg':
                bg = cv2.GaussianBlur(img, (0, 0), 18)
                yield np.where(m[..., None], img, bg).astype(np.uint8)
            elif op == 'cutout':
                out = img.copy()
                out[~m] = bg_color
                yield out
            else:
                yield img

    try:
        n = _encode_frames(_iter(), out_path, fps, total=total, on_frame=on_frame)
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)
    return {'output': out_path, 'frames': n, 'fps': fps, 'op': op}


# ────────────────────────── VACE 视频 inpaint（追踪 + 生成式重绘） ──────────────────────────

def video_masks(in_path, out_dir, points=None, boxes=None, prompt_frame=0, size='small',
                device='', yolo=False, classes=None, conf=0.25, max_frames=81):
    """SAM2 视频追踪 → 抽帧 + 逐帧 mask 落盘（VACE inpaint 的 control_video/control_masks）。

    frames（原帧 jpg）+ masks（物体区白 255 的 PNG）写 out_dir。
    返回 {frame_paths, mask_paths, fps, width, height, length}。
    length 取 4n+1 且 ≤ max_frames（VACE 1.3B 甜点 81）；超量均匀采样。
    yolo=True 时提示帧自动检测（Grounded-SAM）。
    """
    import torch
    import cv2

    predictor, dev = load_predictor(size=size, device=device, video=True)

    tmpd = tempfile.mkdtemp(prefix='sam2vace_')
    fps = _probe_fps(in_path)
    extract = subprocess.run([FFMPEG, '-y', '-i', in_path, '-vf',
                              'scale=trunc(iw/2)*2:trunc(ih/2)*2',
                              os.path.join(tmpd, '%06d.jpg'), '-q:v', '2'],
                             capture_output=True, text=True, timeout=300)
    names = sorted(f for f in os.listdir(tmpd) if f.endswith('.jpg'))
    if not names:
        raise RuntimeError(f'抽帧失败: {extract.stderr[-200:]}')

    # 帧数对齐 4n+1 且 ≤ max_frames（超量均匀采样）
    total = len(names)
    length = min(max_frames, total)
    length = ((length - 1) // 4) * 4 + 1
    if total > length:
        idxs = [round(i * (total - 1) / (length - 1)) for i in range(length)]
        idxs = sorted(set(idxs))
        length = len(idxs)
    else:
        idxs = list(range(length))

    # 采样帧单独落 track 目录（SAM2 只追踪选中的帧）+ 拷贝到 out_dir
    trackd = os.path.join(tmpd, 'track')
    os.makedirs(trackd)
    os.makedirs(out_dir, exist_ok=True)
    frame0 = None
    for i, src_i in enumerate(idxs):
        src = os.path.join(tmpd, names[src_i])
        dst = os.path.join(trackd, '%06d.jpg' % (i + 1))
        shutil.copyfile(src, dst)
        shutil.copyfile(src, os.path.join(out_dir, 'frame_%06d.jpg' % i))
        if frame0 is None:
            frame0 = dst

    fh, fw = cv2.imread(frame0).shape[:2]

    with torch.inference_mode(), torch.autocast('cuda', dtype=torch.bfloat16,
                                                enabled=dev.startswith('cuda')):
        state = predictor.init_state(video_path=trackd)
        pf = min(prompt_frame, length - 1)
        if boxes:
            b = boxes[0]
            predictor.add_new_points_or_box(
                state, obj_id=1, frame_idx=pf,
                box=np.array([min(max(b[0], 0), fw - 1), min(max(b[1], 0), fh - 1),
                              min(max(b[2], 0), fw - 1), min(max(b[3], 0), fh - 1)],
                             dtype=np.float32))
        elif points:
            pts = np.array([[(min(max(x, 0), fw - 1), min(max(y, 0), fh - 1)) for x, y in points]],
                           dtype=np.float32)
            labels = np.ones((1, len(points)), dtype=np.int64)
            predictor.add_new_points_or_box(state, obj_id=1, frame_idx=pf,
                                            points=pts, labels=labels)
        elif yolo:
            from agents.post.tools.sam_edit import detect_objects
            dets = detect_objects(cv2.cvtColor(cv2.imread(frame0), cv2.COLOR_BGR2RGB),
                                  classes=classes, conf=conf)
            if not dets:
                raise RuntimeError('YOLO 未检出目标（调低 --conf 或换 --frame）')
            b = dets[0][2]
            predictor.add_new_points_or_box(state, obj_id=1, frame_idx=pf, box=np.array(b, dtype=np.float32))
        else:
            raise RuntimeError('需要 --point/--box/--yolo 之一')

        masks_by_frame = {}
        for reverse in (False, True):
            for fo, obj_ids, mask_logits in predictor.propagate_in_video(state,
                                                                         reverse=reverse):
                m = (mask_logits[0] > 0).cpu().numpy()
                if m.ndim == 3:
                    m = m[0]
                masks_by_frame[fo] = m.astype(bool)

    mask_paths = []
    for i in range(length):
        m = masks_by_frame.get(i)
        if m is None:
            m = np.zeros((fh, fw), dtype=bool)
        Image.fromarray(m.astype(np.uint8) * 255).save(os.path.join(out_dir, 'mask_%06d.png' % i))
        mask_paths.append(os.path.join(out_dir, 'mask_%06d.png' % i))
    frame_paths = [os.path.join(out_dir, 'frame_%06d.jpg' % i) for i in range(length)]
    shutil.rmtree(tmpd, ignore_errors=True)
    return {'frame_paths': frame_paths, 'mask_paths': mask_paths, 'fps': fps,
            'width': fw, 'height': fh, 'length': length}


def video_inpaint_vace(in_path, out_path, points=None, boxes=None, prompt='empty ground',
                       op='remove', prompt_frame=0, size='small', device='', yolo=False,
                       classes=None, conf=0.25, steps=25, cfg=5.0, vace_strength=1.0,
                       negative_prompt=None, model='wan2.1_vace_1.3B_fp16.safetensors',
                       on_stage=None):
    """SAM2 追踪 + Wan2.1 VACE 生成式视频 inpaint（视频级移除/替换物体，wan 8189）。

    op: remove=去掉物体（物体区按 prompt 补全）
        keep=只保留主体（背景按 prompt 补全）
    prompt 描述重绘区内容（如 empty ground / green grass）。
    流程：SAM2 逐帧 mask → control_video 帧的重绘区先用 TELEA 预填充延展背景色
    （直接填灰模型会补出暗色，填原像素则物体泄漏成结构参考只"换皮"不消失）
    → control_masks=重绘区 → VACE 时序一致化补全。
    """
    import cv2
    from agents.generator.tools.comfy_api import ComfyClient

    def _stage(s):
        print(f'[vace-inpaint] {s}')
        if on_stage:
            on_stage(s)

    _stage('SAM2 逐帧 mask 提取中')
    workd = os.path.join(os.path.dirname(out_path) or '.', 'vace_inpaint_work')
    r = video_masks(in_path, workd, points=points, boxes=boxes, prompt_frame=prompt_frame,
                    size=size, device=device, yolo=yolo, classes=classes, conf=conf)
    try:
        _stage(f'VACE 生成中（{r["length"]} 帧 {r["width"]}x{r["height"]}，约 5-10 分钟）')
        # 时序背景板预填充：物体未遮挡该像素的帧取中位（≈真实背景），
        # 替代 TELEA 糊斑（TELEA 团块会被 VACE 当物体顺势画成新物体，如白鸭）
        frames_all = [np.array(Image.open(fp).convert('RGB')) for fp in r['frame_paths']]
        masks_all = [(np.array(Image.open(mp)) > 127) for mp in r['mask_paths']]
        fa = np.stack(frames_all).astype(np.float32)
        ma = ~np.stack(masks_all)  # True=可见（未被物体盖住）
        vis = ma.astype(np.float32)[:, :, :, None]
        cov = ma.mean(axis=0)  # 每像素背景可见率
        plate = np.where(cov[:, :, None] > 0.05, (fa * vis).sum(0) / np.maximum(vis.sum(0), 1), 0)
        _stage(f'背景板可见率中位 {np.median(cov) * 100:.0f}%')
        mask_pngs, ctrl_paths = [], []
        for i, (fp, mp) in enumerate(zip(r['frame_paths'], r['mask_paths'])):
            fr = frames_all[i]
            m = np.array(Image.open(mp))
            m = m if op == 'remove' else 255 - m
            m8 = (m > 127).astype(np.uint8)
            m8 = cv2.dilate(m8, np.ones((9, 9), np.uint8))
            filled = cv2.inpaint(fr[:, :, ::-1], m8, 5, cv2.INPAINT_TELEA)[:, :, ::-1]
            # 背景板可见像素优先（真实背景），不可见像素回退 TELEA
            ok = (cov > 0.05) & (m8 > 0)
            fr = fr.copy()
            fr[ok] = plate[ok].astype(np.uint8)
            fr[m8 > 0] = np.where(ok[:, :, None], fr, filled)[m8 > 0]
            cf = os.path.splitext(fp)[0] + '_ctrl.png'
            Image.fromarray(fr).save(cf)
            ctrl_paths.append(cf)
            inv = os.path.splitext(mp)[0] + '_inv.png'
            Image.fromarray((m8 * 255).astype(np.uint8)).save(inv)
            mask_pngs.append(inv)
        client = ComfyClient(instance='wan')
        res = client.generate_vace_inpaint(
            ctrl_paths, mask_pngs, prompt,
            width=r['width'], height=r['height'], length=r['length'],
            steps=steps, cfg=cfg, vace_strength=vace_strength, fps=16,
            negative_prompt=negative_prompt, model=model, output_path=out_path)
        print(f"[vace-inpaint] prompt_id={res['prompt_id']} seed={res['seed']} "
              f"length={r['length']} op={op}")
        return {'output': out_path, 'frames': r['length'], 'fps': 16, 'op': op,
                'seed': res['seed'], 'prompt_id': res['prompt_id']}
    finally:
        shutil.rmtree(workd, ignore_errors=True)


_PROPAINTER_SRC = '/mnt/disk_sdb/zxy/ProPainter'


def video_inpaint_propainter(in_path, out_path, points=None, boxes=None, op='remove',
                             prompt_frame=0, size='small', device='', yolo=False,
                             classes=None, conf=0.25, mask_dilation=8, fp16=True,
                             on_stage=None):
    """SAM2 追踪 + ProPainter 流传播视频 inpaint（光流传播，物体移除融合最自然）。

    op: remove=去掉物体（SAM mask 白=移除区）/ keep=只保留主体（mask 反转）。
    流程：SAM2 逐帧 mask → ProPainter（RAFT 双向光流补全 + 特征传播 + transformer），
    掩码区由前后帧光流传播内容填满——非生成式，不会长出新物体。
    前置：ProPainter 仓库在 _PROPAINTER_SRC 且 weights/ 下有三个 .pth
    （ProPainter.pth / raft-things.pth / recurrent_flow_completion.pth）。
    """
    import cv2

    def _stage(s):
        print(f'[propainter] {s}')
        if on_stage:
            on_stage(s)

    _stage('SAM2 逐帧 mask 提取中')
    workd = os.path.join(os.path.dirname(out_path) or '.', 'propainter_work')
    r = video_masks(in_path, workd, points=points, boxes=boxes, prompt_frame=prompt_frame,
                    size=size, device=device, yolo=yolo, classes=classes, conf=conf)
    try:
        framesd = os.path.join(workd, 'frames')
        os.makedirs(framesd)
        for fp in r['frame_paths']:
            shutil.copyfile(fp, os.path.join(framesd, os.path.basename(fp)))
        maskd = os.path.join(workd, 'masks')
        os.makedirs(maskd)
        for mp in r['mask_paths']:
            if op == 'keep':
                m = 255 - np.array(Image.open(mp))
                Image.fromarray(m).save(os.path.join(maskd, os.path.basename(mp)))
            else:
                shutil.copyfile(mp, os.path.join(maskd, os.path.basename(mp)))
        _stage(f'ProPainter 流传播中（{r["length"]} 帧 {r["width"]}x{r["height"]}）')
        tmp_out = os.path.join(workd, 'out')
        # ProPainter 子进程 cwd 在其仓库内，所有路径必须绝对化
        cmd = [sys.executable, os.path.join(_PROPAINTER_SRC, 'inference_propainter.py'),
               '-i', os.path.abspath(framesd), '-m', os.path.abspath(maskd),
               '-o', os.path.abspath(tmp_out),
               '--mask_dilation', str(mask_dilation),
               '--save_fps', str(int(round(r['fps'])))]
        if fp16 and not device.startswith('cpu'):
            cmd.append('--fp16')
        env = dict(os.environ)
        proc = subprocess.run(cmd, cwd=_PROPAINTER_SRC, env=env,
                              capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or '')[-2000:]
            raise RuntimeError(f'ProPainter 推理失败: {tail}')
        src = os.path.join(os.path.abspath(tmp_out),
                           os.path.basename(os.path.abspath(framesd)), 'inpaint_out.mp4')
        if not os.path.isfile(src):
            raise RuntimeError(f'ProPainter 未产出 {src}')
        os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
        shutil.copyfile(src, out_path)
        print(f"[propainter] {r['length']} 帧 @{r['fps']:.1f}fps op={op} "
              f"mask_dilation={mask_dilation}")
        return {'output': out_path, 'frames': r['length'], 'fps': r['fps'], 'op': op}
    finally:
        shutil.rmtree(workd, ignore_errors=True)


# ────────────────────────── CLI ──────────────────────────

def main():
    ap = argparse.ArgumentParser(description='v16 SAM2 分割 + 局部替换')
    ap.add_argument('cmd', choices=['segment', 'cutout', 'replace_bg', 'mosaic', 'inpaint', 'visualize', 'video', 'instruct'])
    ap.add_argument('input')
    ap.add_argument('-o', '--output')
    ap.add_argument('--point', help='点提示 x,y（可多个，空格分）', default='')
    ap.add_argument('--size', choices=['tiny', 'small', 'base'], default='small')
    ap.add_argument('--device', default='')
    ap.add_argument('--mode', default='pixel', help='mosaic 模式 pixel/blur')
    ap.add_argument('--strength', type=int, default=16)
    ap.add_argument('--bg', default='', help='replace_bg: hex 色（如 101827）或 blur')
    ap.add_argument('--op', default='mosaic', help='video: mosaic/blur_bg/cutout/color')
    ap.add_argument('--frame', type=int, default=0, help='video 提示帧索引（任意帧双向传播）')
    ap.add_argument('--box', default='', help='框提示 x1,y1,x2,y2（分号分隔多框；优先于 --point）')
    ap.add_argument('--yolo', action='store_true', help='YOLO 自动检测物体→框提示（Grounded-SAM）')
    ap.add_argument('--classes', default='', help='YOLO 类别过滤（逗号分隔，如 cat,dog）')
    ap.add_argument('--conf', type=float, default=0.25, help='YOLO 置信度阈值')
    ap.add_argument('--engine', choices=['cv', 'flux', 'vace', 'propainter'], default='cv',
                     help='inpaint/replace_bg 引擎：cv=TELEA（快速）/ flux=FLUX.1 Fill 生成式重绘 / vace=视频级 VACE（video 专用）/ propainter=视频级流传播（video 专用）')
    ap.add_argument('--prompt', default='', help='flux 引擎重绘内容描述（如 empty wooden floor）')
    ap.add_argument('--steps', type=int, default=30, help='flux Fill 采样步数')
    ap.add_argument('--guidance', type=float, default=30.0, help='flux Fill guidance（官方推荐 30）')
    ap.add_argument('--cfg', type=float, default=2.5, help='Qwen Edit CFG（instruct 用）')
    ap.add_argument('--controlnet', default='', choices=['', 'canny'],
                     help='flux 联动 ControlNet：canny=结构保持重绘（v16.x M6）')
    ap.add_argument('--controlnet-strength', type=float, default=0.5, help='ControlNet 强度')
    ap.add_argument('--mask-op', dest='mask_op', default='remove', choices=['remove', 'keep'],
                     help='vace 引擎：remove=去掉物体（mask 反转）/ keep=只保留主体')
    a = ap.parse_args()

    out = a.output or os.path.join(
        os.path.dirname(os.path.dirname(_ROOT)) and 'output',
        f"edit_{time.strftime('%Y%m%d_%H%M%S')}.{'mp4' if a.cmd == 'video' else 'png'}")
    out = a.output or out

    if a.cmd == 'video':
        pts = parse_points(a.point)
        boxes = parse_boxes(a.box)
        labels = None
        if a.yolo:
            import cv2 as _cv2
            probe = _cv2.VideoCapture(a.input)
            probe.set(_cv2.CAP_PROP_POS_FRAMES, max(0, a.frame))
            ok, fr = probe.read()
            if not ok:
                ap.error('提示帧读取失败（--frame 超出视频帧数？）')
            dets = detect_objects(fr[:, :, ::-1], classes=(a.classes.split(',') if a.classes else None),
                                  conf=a.conf)
            boxes = [d[2] for d in dets]
            labels = [d[0] for d in dets]
            print(f'[yolo] {len(boxes)} 个物体: '
                  + ', '.join(f'{d[0]}({d[1]:.2f})' for d in dets[:8]))
            if not boxes:
                ap.error('YOLO 未检出目标（调低 --conf 或换提示帧）')
        if not pts and not boxes:
            ap.error('video 需要 --point x,y / --box x1,y1,x2,y2 / --yolo')
        if a.engine == 'vace':
            if not a.prompt:
                ap.error('vace 引擎需要 --prompt 描述重绘区内容（如 empty ground）')
            r = video_inpaint_vace(a.input, out, pts, boxes=boxes or None,
                                   prompt=a.prompt, op=getattr(a, 'mask_op', None) or 'remove',
                                   prompt_frame=a.frame, size=a.size, device=a.device,
                                   yolo=bool(a.yolo),
                                   classes=(a.classes.split(',') if a.classes else None),
                                   conf=a.conf, steps=a.steps, cfg=a.cfg)
            print(f"✅ {r['output']}（{r['frames']} 帧 @{r['fps']:.1f}fps op={r['op']} seed={r['seed']}）")
            return
        if a.engine == 'propainter':
            r = video_inpaint_propainter(a.input, out, pts, boxes=boxes or None,
                                         op=getattr(a, 'mask_op', None) or 'remove',
                                         prompt_frame=a.frame, size=a.size, device=a.device,
                                         yolo=bool(a.yolo),
                                         classes=(a.classes.split(',') if a.classes else None),
                                         conf=a.conf)
            print(f"✅ {r['output']}（{r['frames']} 帧 @{r['fps']:.1f}fps op={r['op']}）")
            return
        if a.op == 'color':
            r = video_color(a.input, out, pts, size=a.size, device=a.device,
                            prompt_frame=a.frame, boxes=boxes or None)
            print(f"✅ {r['output']}（{r['frames']} 帧 @{r['fps']:.1f}fps, {r['objects']} 物体彩色）")
            return
        r = video_edit(a.input, out, pts, op=a.op, size=a.size, device=a.device,
                       mode=a.mode, strength=a.strength, prompt_frame=a.frame,
                       boxes=boxes or None)
        print(f"✅ {r['output']}（{r['frames']} 帧 @{r['fps']:.1f}fps op={r['op']}）")
        return

    if a.cmd == 'instruct':
        if not a.prompt:
            ap.error('instruct 需要 --prompt 编辑指令（如 把猫换成狗）')
        qwen_edit(a.input, a.prompt, out, steps=a.steps, cfg=a.cfg)
        print(f'✅ {out}')
        return
    img = np.array(Image.open(a.input).convert('RGB'))
    pts = parse_points(a.point)
    boxes = parse_boxes(a.box)
    labels = None
    if a.yolo:
        classes = a.classes.split(',') if a.classes else None
        dets = detect_objects(img, classes=classes, conf=a.conf)
        boxes = [d[2] for d in dets]
        labels = [d[0] for d in dets]
        print(f'[yolo] {len(boxes)} 个物体: '
              + ', '.join(f'{d[0]}({d[1]:.2f})' for d in dets[:8]))
    if a.cmd == 'visualize':
        if boxes:
            masks, scores, labels = segment_from_boxes(img, boxes, labels=labels,
                                                       size=a.size, device=a.device)
        else:
            masks, scores = segment_multi(img, points=pts or None, size=a.size, device=a.device)
            labels = ['物体%d' % (i + 1) for i in range(len(masks))]
        print(f'[sam2] 彩色多物体: {len(masks)} 个物体, scores '
              + ', '.join(f'{s:.2f}' for s in scores))
        visualize(img, masks, out, labels=labels)
        print(f'✅ {out}')
        return
    if boxes:
        masks, scores, _ = segment_from_boxes(img, boxes, size=a.size, device=a.device)
        if not masks:
            raise RuntimeError('SAM2 框提示未产出掩膜')
        mask = masks[0]
        score = scores[0]
    else:
        mask, score = segment_image(img, points=pts or None, size=a.size, device=a.device)
    print(f'[sam2] mask score={score:.3f} coverage={mask.mean():.3f}')

    if a.cmd == 'segment':
        Image.fromarray(mask.astype(np.uint8) * 255).save(out)
    elif a.cmd == 'cutout':
        cutout(img, mask, out)
    elif a.cmd == 'replace_bg':
        if a.engine == 'flux':
            inpaint_flux(img, mask, a.prompt or 'clean empty background', out,
                         invert=True, steps=a.steps, guidance=a.guidance)
        elif a.bg == 'blur':
            replace_bg(img, mask, out, blur=True)
        elif a.bg:
            c = a.bg.lstrip('#')
            col = tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) if len(c) >= 6 else (16, 18, 27)
            replace_bg(img, mask, out, color=col)
        else:
            replace_bg(img, mask, out)
    elif a.cmd == 'mosaic':
        mosaic(img, mask, out, mode=a.mode, strength=a.strength)
    elif a.cmd == 'inpaint':
        if a.engine == 'flux':
            if not a.prompt:
                ap.error('flux 引擎需要 --prompt 描述重绘内容（如 empty wooden floor）')
            inpaint_flux(img, mask, a.prompt, out, steps=a.steps, guidance=a.guidance,
                         controlnet=a.controlnet, controlnet_strength=a.controlnet_strength)
        else:
            inpaint(img, mask, out)
    print(f'✅ {out}')


if __name__ == '__main__':
    main()
