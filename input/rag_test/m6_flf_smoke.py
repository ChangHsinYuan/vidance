"""v18 M2-a 冒烟：Wan2.1 VACE 首尾帧驱动（control_video 序列 = 首帧→xfade→尾帧）。

用法: python input/rag_test/m6_flf_smoke.py [first.png last.png]   # 缺省 v3 kf_09/kf_10
输出: output/m6/flf_smoke/{control.mp4,out.mp4}
"""
import json
import os
import subprocess
import sys

_ROOT = os.path.abspath(__file__)
for _ in range(3):
    _ROOT = os.path.dirname(_ROOT)
sys.path.insert(0, _ROOT)

OUT = 'output/m6/flf_smoke'
os.makedirs(OUT, exist_ok=True)
W, H, FPS, LEN = 832, 480, 16, 81
XFADE = 1.2  # 秒（≈19 帧过渡带，首尾各留 ~60% 定帧）

first = sys.argv[1] if len(sys.argv) > 2 else 'output/m6/v3/kf/kf_09.png'
last = sys.argv[2] if len(sys.argv) > 2 else 'output/m6/v3/kf/kf_10.png'
ctrl = os.path.join(OUT, 'control.mp4')
outp = os.path.join(OUT, 'out.mp4')

# 1) 控制视频：首帧定帧 → xfade → 尾帧定帧（VACE 对灰色段做 0.5 填充也行，但 ramp 给运动引导）
if not os.path.isfile(ctrl):
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error',
                    '-loop', '1', '-t', '2.0', '-i', first,
                    '-loop', '1', '-t', '3.1', '-i', last,
                    '-filter_complex',
                    f'[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,'
                    f'crop={W}:{H},setsar=1,fps={FPS}[a];'
                    f'[1:v]scale={W}:{H}:force_original_aspect_ratio=increase,'
                    f'crop={W}:{H},setsar=1,fps={FPS}[b];'
                    f'[a][b]xfade=transition=fade:duration={XFADE}:offset=1.9,'
                    f'trim=duration={LEN / FPS:.3f}[v]',
                    '-map', '[v]', '-pix_fmt', 'yuv420p', '-c:v', 'libx264', ctrl], check=True)
    print(f'[控制] ✓ {ctrl}')
else:
    print(f'[控制] 已存在 {ctrl}')

# 2) 工作流：LoadVideo→GetVideoComponents→WanVaceToVideo(control_video)
PROMPT = ('a man in a torn long gown slowly walks along the tavern street, '
          'subtle natural motion, documentary style, black and white')
NEG = ('blurry, low quality, distorted, extra limbs, text, watermark, '
       'static image, no motion')
wf = {
    "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.1_vace_1.3B_fp16.safetensors", "weight_dtype": "default"}},
    "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan"}},
    "3": {"class_type": "VAELoader", "inputs": {"vae_name": "wan_2.1_vae.safetensors"}},
    "4": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["1", 0], "shift": 8.0}},
    "5": {"class_type": "CLIPTextEncode", "inputs": {"text": PROMPT, "clip": ["2", 0]}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["2", 0]}},
    "20": {"class_type": "LoadVideo", "inputs": {"file": "flf_smoke_control.mp4"}},
    "21": {"class_type": "GetVideoComponents", "inputs": {"video": ["20", 0]}},
    "8": {"class_type": "WanVaceToVideo", "inputs": {"positive": ["5", 0], "negative": ["6", 0],
                                                     "vae": ["3", 0], "width": W, "height": H,
                                                     "length": LEN, "batch_size": 1, "strength": 1.0,
                                                     "control_video": ["21", 0]}},
    "11": {"class_type": "KSampler", "inputs": {"model": ["4", 0], "seed": 42, "steps": 25, "cfg": 5.0,
                                                "sampler_name": "uni_pc", "scheduler": "simple",
                                                "positive": ["8", 0], "negative": ["8", 1],
                                                "latent_image": ["8", 2], "denoise": 1.0}},
    "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
    "13": {"class_type": "CreateVideo", "inputs": {"images": ["12", 0], "fps": FPS}},
    "14": {"class_type": "SaveVideo", "inputs": {"video": ["13", 0], "filename_prefix": "vidance/flf_smoke",
                                                 "format": "mp4", "codec": "auto"}},
}
os.makedirs('input/rag_test/tmp_flf', exist_ok=True)
wf_path = 'input/rag_test/tmp_flf/wan_vace_flf.json'
json.dump(wf, open(wf_path, 'w'), indent=1)
print(f'[工作流] ✓ {wf_path}')

# 3) 控制视频进 ComfyUI input 目录（本机直拷，绕过 upload API——LoadVideo 只认 input 目录）
import shutil
comfy_input = '/mnt/disk_sdb/zxy/ComfyUI/input'
os.makedirs(comfy_input, exist_ok=True)
ctrl_name = f'flf_smoke_control.mp4'
shutil.copy(ctrl, os.path.join(comfy_input, ctrl_name))
wf['20']['inputs']['file'] = ctrl_name
print(f'[部署] ✓ {comfy_input}/{ctrl_name}')

from agents.generator.tools.comfy_api import ComfyClient
c = ComfyClient(instance='wan')
if not c.wait_ready(timeout=60):
    raise SystemExit('ComfyUI not ready')
pid = c.queue_prompt(wf)
print(f'[排队] prompt_id={pid}，VACE 1.3B 81 帧 ~2-4min…')
outs = c.wait_result(pid)
info = outs.get('14', {}).get('videos') or outs.get('14', {}).get('images', [{}])[0]
print(f'[产出] {info}')
if info and info.get('filename'):
    c.download_file(info['filename'], info.get('subfolder', ''), info.get('type', 'output'), outp)
    sz = os.path.getsize(outp)
    print(f'[冒烟] ✓ {outp}（{sz / 1e6:.1f}MB）')
    subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                    '-show_entries', 'stream=width,height,nb_frames,codec_name',
                    '-of', 'csv=p=0', outp])
else:
    print('[冒烟] ✗ 无视频产出，工作流被拒——M2 降级路径启动')
