#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v21 M3 失败自诊断（2026-11-05）
error 文本 → 可执行的修复提示（点名到服务/命令）。规则按顺序命中，可多条。
CLI:  python core/diagnose.py "Connection refused 8189"
"""
import re

# 端口 → 服务名 + 启动命令（与 start_services.sh / deploy README 对齐）
PORT_SERVICES = {
    8188: ('H3 ref2va (custom/h3shot)', './start_services.sh start h3'),
    8189: ('Wan T2V/I2V (auto/quick)', './start_services.sh start wan'),
    8190: ('HunyuanVideo', './start_services.sh start hunyuan'),
    8192: ('FLUX 生图', './start_services.sh start flux'),
    8193: ('Hunyuan3Dv2', './start_services.sh start h3d'),
    9880: ('TTS 双引擎', './start_services.sh start tts'),
    8894: ('Vidance API', './start_services.sh start api'),
}

RULES = [
    # (正则, 提示模板列表; {port_hint} 由端口规则补)
    (r'connection refused|connectionerror|max retries|failed to establish|connection reset|err 111',
     ['ComfyUI/TTS 服务未启动或端口不对：按端口号启动对应服务（8188 h3 / 8189 wan / 8192 flux / 8193 h3d / 9880 tts）']),
    (r'cuda out of memory|outofmemoryerror|torch\.cuda\.outofmemory|\bOOM\b|显存不足',
     ['GPU 显存不足：nvidia-smi 看占用，关掉其他占卡服务，或换空闲卡（CUDA_VISIBLE_DEVICES）、降分辨率/帧数']),
    (r'401|403|unauthorized|invalid[_ ]api[_ ]key|authentication',
     ['LLM/图源 API key 无效或过期：python core/vidance.py init 重新填写（--show 查看当前配置）']),
    (r'connection timeout.*(speech\.platform|bing)|edge.*timeout|speech\.platform\.bing',
     ['edge-tts 外网不通：改用本地音色 cosy-*（--voice cosy-default），或恢复外网']),
    (r'no space left|磁盘(空间)?(不足|已满)|disk.*(full|quota)',
     ['磁盘空间不足：python core/vidance.py clean --keep 5（或 UI ⚙→系统→清理）清旧任务产物']),
    (r'address already in use|端口.*(占用|冲突)|bind.*failed',
     ['端口被占用：ss -tlnp | grep <端口> 找到占用进程，换端口（--port）或停掉占用者']),
    (r'websockets 库不可用|no module named websockets',
     ['运行环境缺 websockets 依赖：容器场景重 build 镜像（docker build -f deploy/Dockerfile），裸机 pip install websockets']),
    (r'filenotfounderror.*ffmpeg|ffmpeg.*not found|command not found.*ffmpeg',
     ['ffmpeg 未安装：apt install ffmpeg 或 conda install ffmpeg']),
    (r'model.*(not found|不存在|加载失败)|checkpoint.*(missing|corrupt)|safetensors.*not found',
     ['模型文件缺失：对照 deploy/download_weights.sh 清单补权重；HF 模型确认 HF_HOME 指向的缓存盘']),
    (r'timeout \(7200s\)|subprocess.*timeout',
     ['任务超 2 小时被杀：常因上游服务卡死（审片 API 慢/生成队列积压），查该任务 scheduler.log 定位卡在哪一步']),
    (r'exit code (?!0)\d+',
     ['子进程非零退出：看任务 scheduler.log（GET /api/tasks/{id}/log 或 output/<task_id>/scheduler.log）找首个 traceback']),
]


def diagnose(error_text, extra=None):
    """error 文本 → ['💡 提示1', ...]；无命中返回 []（extra: 附加提示，直接附在末尾）。"""
    if not error_text:
        return []
    t = str(error_text).lower()
    hints = []
    for pat, tips in RULES:
        if re.search(pat, t, re.IGNORECASE):
            for tip in tips:
                hints.append(tip)
    # 端口点名：文本里出现已知端口 → 给对应服务的启动命令
    for m in set(re.findall(r'\b(8188|8189|8190|8192|8193|9880|8894)\b', str(error_text))):
        port = int(m)
        name, cmd = PORT_SERVICES[port]
        hints.append(f'端口 {port} = {name}，启动：{cmd}')
    if extra:
        hints.extend(extra)
    # 去重保序
    seen, out = set(), []
    for h in hints:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


if __name__ == '__main__':
    import sys
    text = sys.argv[1] if len(sys.argv) > 1 else 'error'
    for h in diagnose(text):
        print(h)
    if not diagnose(text):
        print('(无命中规则)')
