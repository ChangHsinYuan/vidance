#!/usr/bin/env python3
"""模型提供商路由 — 动态管理 API 提供商，按任务类型分发

用法:
  from utils.model_router import ModelRouter
  router = ModelRouter(config)
  router.add_provider({...})          # 添加自定义提供商
  router.remove_provider('my-api')    # 删除
  models = router.discover_models(url, key)  # 查询可用模型
  router.set_active('i2v', 'my-api', 'wan-3.0')  # 切换并指定模型
"""
import json
import os
import urllib.request
import urllib.error

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'config.json')


def load_config():
    from utils.config_loader import load_config as _load
    return _load()


def save_config(config):
    """只把 model_providers 段写回 config.json（基础配置）。

    不自定义保存整份 merged 配置，避免 config.local.json 的本地覆盖值
    （如 output_dir）被固化进仓库里的 config.json。
    """
    from utils.config_loader import load_base_config
    base = load_base_config()
    base['model_providers'] = config.get('model_providers', {})
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(base, f, ensure_ascii=False, indent=2)


class ModelRouter:
    TASK_TYPES = ('t2i', 'i2v', 't2v')
    TASK_LABELS = {'t2i': '文生图', 'i2v': '图生视频', 't2v': '文生视频'}

    def __init__(self, config=None):
        self.config = config or load_config()
        self._mp = self.config.setdefault('model_providers', {})
        self._active = self._mp.setdefault('active', {'t2i': 'local-flux', 'i2v': 'local-wan', 't2v': 'local-wan'})
        self._providers = self._mp.setdefault('providers', {})
        self._custom = self._mp.setdefault('custom_providers', [])

    def list_providers(self):
        """返回所有提供商（内置 + 自定义）"""
        result = []
        for pid, info in self._providers.items():
            entry = {
                'id': pid,
                'name': info.get('name', pid),
                'type': info.get('type', 'unknown'),
                'capabilities': info.get('capabilities', []),
                'status': info.get('status', 'unknown'),
                'builtin': True,
            }
            if info.get('type') == 'comfyui':
                entry['instance'] = info.get('instance', '')
            result.append(entry)
        for cp in self._custom:
            models = cp.get('models', [])
            caps = set()
            for m in models:
                caps.update(m.get('capabilities', []))
            result.append({
                'id': cp['id'],
                'name': cp['name'],
                'type': 'api',
                'base_url': cp.get('base_url', ''),
                'has_api_key': bool(cp.get('api_key')),
                'models': models,
                'capabilities': list(caps),
                'status': 'configured' if cp.get('api_key') else 'unconfigured',
                'builtin': False,
            })
        return result

    def get_active(self, task_type=None):
        if task_type:
            pid = self._active.get(task_type)
            if not pid:
                return None
            model = self._active.get(f'{task_type}_model')
            builtin = self._providers.get(pid)
            if builtin:
                return {'id': pid, 'model': builtin.get('model', ''), **builtin}
            custom = next((c for c in self._custom if c['id'] == pid), None)
            if custom:
                return {'id': pid, 'model': model or '', **custom}
            return None
        return {tt: self._active.get(tt) for tt in self.TASK_TYPES}

    def get_provider(self, task_type):
        return self.get_active(task_type)

    def set_active(self, task_type, provider_id, model=None):
        """切换活跃提供商，可选指定模型名"""
        if task_type not in self.TASK_TYPES:
            raise ValueError(f'Unknown task type: {task_type}')
        all_ids = set(self._providers.keys()) | {c['id'] for c in self._custom}
        if provider_id not in all_ids:
            raise ValueError(f'Unknown provider: {provider_id}')
        self._active[task_type] = provider_id
        if model:
            self._active[f'{task_type}_model'] = model
        self._mp['active'] = self._active
        self.config['model_providers'] = self._mp
        save_config(self.config)
        return {'task_type': task_type, 'provider_id': provider_id, 'model': model}

    def add_provider(self, provider_data):
        """添加自定义 API 提供商"""
        pid = provider_data.get('id')
        if not pid:
            raise ValueError('Provider id is required')
        if any(c['id'] == pid for c in self._custom):
            raise ValueError(f'Provider {pid} already exists')
        entry = {
            'id': pid,
            'name': provider_data.get('name', pid),
            'base_url': provider_data.get('base_url', ''),
            'api_key': provider_data.get('api_key', ''),
            'models': provider_data.get('models', []),
        }
        self._custom.append(entry)
        self._mp['custom_providers'] = self._custom
        self.config['model_providers'] = self._mp
        save_config(self.config)
        return entry

    def update_provider(self, provider_id, updates):
        """更新自定义提供商配置"""
        for cp in self._custom:
            if cp['id'] == provider_id:
                for k in ('name', 'base_url', 'api_key', 'models'):
                    if k in updates:
                        cp[k] = updates[k]
                self._mp['custom_providers'] = self._custom
                self.config['model_providers'] = self._mp
                save_config(self.config)
                return cp
        raise ValueError(f'Custom provider not found: {provider_id}')

    def remove_provider(self, provider_id):
        """删除自定义提供商"""
        before = len(self._custom)
        self._custom = [c for c in self._custom if c['id'] != provider_id]
        if len(self._custom) == before:
            raise ValueError(f'Custom provider not found: {provider_id}')
        for tt in self.TASK_TYPES:
            if self._active.get(tt) == provider_id:
                self._active[tt] = {'t2i': 'local-flux', 'i2v': 'local-wan', 't2v': 'local-wan'}[tt]
                self._active.pop(f'{tt}_model', None)
        self._mp['custom_providers'] = self._custom
        self._mp['active'] = self._active
        self.config['model_providers'] = self._mp
        save_config(self.config)
        return True

    def get_comfy_client(self, task_type):
        provider = self.get_provider(task_type)
        if not provider or provider.get('type') != 'comfyui':
            return None
        from utils.comfy_api import ComfyClient
        return ComfyClient(config=self.config, instance=provider.get('instance', 'wan'))

    def get_adapter(self, task_type):
        """返回对应 task_type 的 VendorAdapter（统一 t2i/i2v/t2v 接口）"""
        from utils.vendor import ComfyUIVendor, APIVendor
        provider = self.get_provider(task_type)
        if not provider:
            raise ValueError(f'No active provider for task type: {task_type}')
        if provider.get('type') == 'comfyui':
            return ComfyUIVendor(config=self.config, instance=provider.get('instance', 'wan'))
        return APIVendor(provider)

    def is_local(self, task_type):
        provider = self.get_provider(task_type)
        return provider is not None and provider.get('type') == 'comfyui'

    @staticmethod
    def discover_models(base_url, api_key):
        """尝试从 API 端点查询可用模型列表（OpenAI 兼容格式）"""
        url = base_url.rstrip('/')
        models = []
        errors = []

        for path in ('/v1/models', '/models', ''):
            try:
                req_url = f'{url}{path}' if path else url
                req = urllib.request.Request(req_url)
                if api_key:
                    req.add_header('Authorization', f'Bearer {api_key}')
                req.add_header('Accept', 'application/json')
                resp = urllib.request.urlopen(req, timeout=10)
                data = json.loads(resp.read().decode('utf-8'))

                if isinstance(data, dict) and 'data' in data:
                    for m in data['data']:
                        mid = m.get('id', '') if isinstance(m, dict) else str(m)
                        if mid:
                            models.append({'id': mid, 'capabilities': []})
                    return {'models': models, 'source': 'api'}
                elif isinstance(data, list):
                    for m in data:
                        mid = m.get('id', '') if isinstance(m, dict) else str(m)
                        if mid:
                            models.append({'id': mid, 'capabilities': []})
                    return {'models': models, 'source': 'api'}
            except Exception as e:
                errors.append(f'{path}: {e}')
                continue

        return {'models': [], 'source': 'none', 'errors': errors}


if __name__ == '__main__':
    router = ModelRouter()
    print('=== 所有提供商 ===')
    for p in router.list_providers():
        print(f"  {p['id']}: {p['name']} [{p['type']}] builtin={p.get('builtin')} caps={p.get('capabilities')}")
    print('\n=== 当前活跃 ===')
    for tt, pid in router.get_active().items():
        print(f'  {tt} -> {pid}')
