#!/usr/bin/env python3
"""Vendor 适配层 — 统一 text/image/video 生成接口

不同 provider（ComfyUI / SiliconFlow / 其他 API）实现相同协议，
Pipeline 和 FastLine 只需调用 adapter.t2i() / i2v() / t2v()，
不关心底层是本地节点还是云端 API。

用法:
  from utils.vendor import ComfyUIVendor, get_vendor
  vendor = ComfyUIVendor(config, instance='wan')
  result = vendor.t2v(prompt='a cat on the moon', output_path='out.mp4')

  # 通过 ModelRouter 自动选择:
  from utils.model_router import ModelRouter
  router = ModelRouter(config)
  vendor = router.get_adapter('t2v')
  result = vendor.t2v(prompt='...', output_path='out.mp4')
"""
import os
import random
import time
from abc import ABC, abstractmethod


class VendorAdapter(ABC):
    """所有 provider 的基类 — 统一生成接口"""

    name: str = 'base'

    @abstractmethod
    def t2i(self, prompt: str, output_path: str = None, seed: int = None,
            width: int = 1024, height: int = 1024, **kwargs) -> dict:
        """文生图 → {image_path, seed, params}"""

    @abstractmethod
    def i2v(self, prompt: str, image_path: str, output_path: str = None,
            seed: int = None, width: int = 1280, height: int = 704,
            length: int = 121, **kwargs) -> dict:
        """图生视频 → {video_path, seed, params}"""

    @abstractmethod
    def t2v(self, prompt: str, output_path: str = None, seed: int = None,
            width: int = 1280, height: int = 704, length: int = 121,
            **kwargs) -> dict:
        """文生视频 → {video_path, seed, params}"""

    def health(self) -> bool:
        """检查 provider 是否可用"""
        return True


class ComfyUIVendor(VendorAdapter):
    """ComfyUI 后端适配 — 包装现有 ComfyClient"""

    def __init__(self, config=None, instance='wan'):
        from utils.comfy_api import ComfyClient
        self._client = ComfyClient(config=config, instance=instance)
        self._instance = instance
        self.name = f'comfyui-{instance}'

    @property
    def client(self):
        return self._client

    def t2i(self, prompt: str, output_path: str = None, seed: int = None,
            width: int = 1024, height: int = 1024, **kwargs) -> dict:
        return self._client.generate_flux_t2i(
            prompt=prompt, seed=seed, width=width, height=height,
            steps=kwargs.get('steps', 20),
            guidance=kwargs.get('guidance', 3.5),
            cfg=kwargs.get('cfg', 1.0),
            output_path=output_path,
        )

    def i2v(self, prompt: str, image_path: str, output_path: str = None,
            seed: int = None, width: int = 1280, height: int = 704,
            length: int = 121, **kwargs) -> dict:
        return self._client.generate_i2v(
            prompt=prompt, image_path=image_path, seed=seed,
            width=width, height=height, length=length,
            steps=kwargs.get('steps', 20),
            cfg=kwargs.get('cfg', 5.0),
            fps=kwargs.get('fps', 24),
            negative_prompt=kwargs.get('negative_prompt'),
            output_path=output_path,
        )

    def t2v(self, prompt: str, output_path: str = None, seed: int = None,
            width: int = 1280, height: int = 704, length: int = 121,
            **kwargs) -> dict:
        return self._client.generate_t2v(
            prompt=prompt, seed=seed,
            width=width, height=height, length=length,
            steps=kwargs.get('steps', 20),
            cfg=kwargs.get('cfg', 5.0),
            fps=kwargs.get('fps', 24),
            negative_prompt=kwargs.get('negative_prompt'),
            output_path=output_path,
        )

    def health(self) -> bool:
        try:
            return self._client.wait_ready(timeout=5)
        except Exception:
            return False


class APIVendor(VendorAdapter):
    """OpenAI 兼容 API 后端适配（SiliconFlow / Replicate / 其他）

    支持两种 API 模式:
    - 图片生成: POST /v1/images/generations (同步)
    - 视频生成: POST /v1/video/submit + /v1/video/status (异步轮询)
    """

    def __init__(self, provider_config: dict):
        self.name = provider_config.get('id', 'api')
        self._base_url = provider_config.get('base_url', '').rstrip('/')
        self._api_key = provider_config.get('api_key', '')
        self._models = {m['id']: m for m in provider_config.get('models', [])}
        self._default_models = {}
        for m in provider_config.get('models', []):
            for cap in m.get('capabilities', []):
                if cap not in self._default_models:
                    self._default_models[cap] = m['id']

    def _headers(self):
        return {
            'Authorization': f'Bearer {self._api_key}',
            'Content-Type': 'application/json',
        }

    def _pick_model(self, task_type, kwargs):
        return kwargs.get('model') or self._default_models.get(task_type, '')

    def t2i(self, prompt: str, output_path: str = None, seed: int = None,
            width: int = 1024, height: int = 1024, **kwargs) -> dict:
        import json
        import urllib.request

        model = self._pick_model('t2i', kwargs)
        body = {
            'model': model,
            'prompt': prompt,
            'n': 1,
            'size': f'{width}x{height}',
        }
        if seed is not None:
            body['seed'] = seed

        req = urllib.request.Request(
            f'{self._base_url}/v1/images/generations',
            data=json.dumps(body).encode(),
            headers=self._headers(),
            method='POST',
        )
        resp = urllib.request.urlopen(req, timeout=120)
        data = json.loads(resp.read())

        img_url = data['data'][0].get('url', '')
        if not img_url and data['data'][0].get('b64_json'):
            import base64
            if output_path:
                os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
                with open(output_path, 'wb') as f:
                    f.write(base64.b64decode(data['data'][0]['b64_json']))
                return {'image_path': output_path, 'seed': seed, 'params': {'model': model}}
            raise RuntimeError('Got b64_json but no output_path to save to')

        if output_path and img_url:
            os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
            urllib.request.urlretrieve(img_url, output_path)
            return {'image_path': output_path, 'seed': seed, 'params': {'model': model}}

        return {'image_url': img_url, 'seed': seed, 'params': {'model': model}}

    def i2v(self, prompt: str, image_path: str, output_path: str = None,
            seed: int = None, width: int = 1280, height: int = 704,
            length: int = 121, **kwargs) -> dict:
        import base64
        import json
        import urllib.request

        model = self._pick_model('i2v', kwargs)
        with open(image_path, 'rb') as f:
            img_b64 = base64.b64encode(f.read()).decode()

        body = {
            'model': model,
            'prompt': prompt,
            'image': img_b64,
        }
        if seed is not None:
            body['seed'] = seed

        task_id = self._submit_video(body)
        return self._poll_video(task_id, output_path, seed, model)

    def t2v(self, prompt: str, output_path: str = None, seed: int = None,
            width: int = 1280, height: int = 704, length: int = 121,
            **kwargs) -> dict:
        import json
        import urllib.request

        model = self._pick_model('t2v', kwargs)
        body = {
            'model': model,
            'prompt': prompt,
        }
        if seed is not None:
            body['seed'] = seed

        task_id = self._submit_video(body)
        return self._poll_video(task_id, output_path, seed, model)

    def _submit_video(self, body: dict) -> str:
        import json
        import urllib.request

        req = urllib.request.Request(
            f'{self._base_url}/v1/video/submit',
            data=json.dumps(body).encode(),
            headers=self._headers(),
            method='POST',
        )
        resp = urllib.request.urlopen(req, timeout=60)
        data = json.loads(resp.read())
        return data.get('request_id') or data.get('task_id', '')

    def _poll_video(self, task_id: str, output_path: str, seed, model: str) -> dict:
        import json
        import urllib.request

        for _ in range(360):
            time.sleep(5)
            req = urllib.request.Request(
                f'{self._base_url}/v1/video/status',
                data=json.dumps({'request_id': task_id}).encode(),
                headers=self._headers(),
                method='POST',
            )
            resp = urllib.request.urlopen(req, timeout=30)
            data = json.loads(resp.read())
            status = data.get('status', '')

            if status in ('Succeed', 'Completed', 'completed'):
                video_url = data.get('output', {}).get('video_url', '')
                if not video_url:
                    results = data.get('data', {}).get('results', [])
                    if results:
                        video_url = results[0].get('url', '')
                if output_path and video_url:
                    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
                    urllib.request.urlretrieve(video_url, output_path)
                    return {'video_path': output_path, 'seed': seed, 'params': {'model': model, 'task_id': task_id}}
                return {'video_url': video_url, 'seed': seed, 'params': {'model': model, 'task_id': task_id}}

            if status in ('Failed', 'failed', 'Error'):
                raise RuntimeError(f'Video generation failed: {data}')

        raise TimeoutError(f'Video generation timed out for task {task_id}')

    def health(self) -> bool:
        try:
            import urllib.request
            req = urllib.request.Request(
                f'{self._base_url}/v1/models',
                headers=self._headers(),
            )
            urllib.request.urlopen(req, timeout=10)
            return True
        except Exception:
            return False


def get_vendor(config: dict, task_type: str) -> VendorAdapter:
    """根据 config['model_providers'] 的 active 设置，返回对应的 adapter"""
    from utils.model_router import ModelRouter
    router = ModelRouter(config)
    provider = router.get_provider(task_type)
    if not provider:
        raise ValueError(f'No active provider for task type: {task_type}')

    if provider.get('type') == 'comfyui':
        instance = provider.get('instance', 'wan')
        return ComfyUIVendor(config=config, instance=instance)

    return APIVendor(provider)
