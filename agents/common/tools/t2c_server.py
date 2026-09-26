"""t2c 自然语言 → Vidance 命令 翻译服务

加载 t2c/model（mt5-small 微调），输入中文口语，输出 Vidance CLI 命令。
默认 CPU 推理即可；api_server 以进程内单例方式调用 `translate(text)`。

也可独立起 HTTP 服务（便于调试）：
    python utils/t2c_server.py --port 9881
    curl -X POST http://127.0.0.1:9881/translate -d '{"text":"帮我auto生成城市夜景"}'
"""

import os as _os
import sys as _sys
_ROOT = _os.path.abspath(__file__)
for _ in range(4):
    _ROOT = _os.path.dirname(_ROOT)
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
import os
import threading

_MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), 't2c', 'model')

_lock = threading.Lock()
_tok = None
_net = None
_device = None


def _load():
    global _tok, _net, _device
    if _net is not None:
        return
    with _lock:
        if _net is not None:
            return
        import torch
        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
        _device = 'cuda' if torch.cuda.is_available() else 'cpu'
        dtype = torch.float16 if _device == 'cuda' else torch.float32
        _tok = AutoTokenizer.from_pretrained(_MODEL_DIR)
        _net = AutoModelForSeq2SeqLM.from_pretrained(
            _MODEL_DIR, torch_dtype=dtype).to(_device).eval()


def translate(text: str) -> str:
    """中文口语 → Vidance 命令字符串（失败返回空串）。"""
    if not text or not text.strip():
        return ''
    try:
        _load()
        import torch
        inputs = _tok(text, return_tensors='pt', max_length=256,
                      truncation=True).to(_device)
        with torch.no_grad():
            out = _net.generate(**inputs, max_new_tokens=128, num_beams=5,
                                early_stopping=True)
        return _tok.decode(out[0], skip_special_tokens=True).strip()
    except Exception as e:
        print(f'  ⚠ [t2c] 翻译失败: {e}')
        return ''


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='t2c 翻译服务')
    ap.add_argument('text', nargs='?', help='中文输入，不给则交互模式')
    ap.add_argument('--port', type=int, default=None, help='起 HTTP 服务（可选）')
    a = ap.parse_args()

    if a.port:
        from fastapi import FastAPI
        from pydantic import BaseModel
        import uvicorn

        app = FastAPI(title='Vidance t2c')

        class Req(BaseModel):
            text: str

        @app.post('/translate')
        def _tr(req: Req):
            return {'text': req.text, 'command': translate(req.text)}

        @app.get('/health')
        def _h():
            return {'status': 'ok', 'model': _MODEL_DIR}

        uvicorn.run(app, host='127.0.0.1', port=a.port)
    elif a.text:
        print(translate(a.text))
    else:
        print(f't2c 交互模式（模型: {_MODEL_DIR}），q 退出')
        while True:
            try:
                t = input('> ').strip()
            except (EOFError, KeyboardInterrupt):
                break
            if t.lower() in ('q', 'quit', 'exit'):
                break
            if t:
                print(' ', translate(t))
