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

import os as _os
import sys as _sys
_ROOT = _os.path.abspath(__file__)
for _ in range(4):
    _ROOT = _os.path.dirname(_ROOT)
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
import json
import os
import urllib.request
import urllib.error

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), 'config', 'config.json')


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
    if isinstance(config.get('llm'), dict) and isinstance(config['llm'].get('models'), dict):
        base.setdefault('llm', {})['models'] = config['llm']['models']
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(base, f, ensure_ascii=False, indent=2)


class ModelRouter:
    TASK_TYPES = ('t2i', 'i2v', 't2v', 'script', 'review', 'translate')
    TASK_LABELS = {'t2i': '文生图', 'i2v': '图生视频', 't2v': '文生视频',
                   'script': '编剧', 'review': '审片', 'translate': '核实/翻译'}
    LLM_TASK_KEYS = {'script': 'script', 'review': 'review', 'translate': 'prompt_opt'}

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
        llm_models = (self.config.get('llm', {}).get('models') or {})
        result.append({'id': 'llm-ustc', 'name': 'USTC 网关（内置文本）', 'type': 'llm',
                       'base_url': self.config.get('llm', {}).get('base_url', ''),
                       'capabilities': ['chat', 'script', 'review', 'translate'],
                       'models': [{'id': v, 'for': k} for k, v in llm_models.items()],
                       'status': 'configured', 'builtin': True})
        for cp in self._custom:
            models = cp.get('models', [])
            caps = set()
            for m in models:
                caps.update(m.get('capabilities', []))
            if not caps:
                caps = {'chat', 'script', 'review', 'translate'}
            result.append({
                'id': cp['id'],
                'name': cp['name'],
                'type': 'api',
                'base_url': cp.get('base_url', ''),
                'has_api_key': bool(cp.get('api_key')),
                'models': models,
                'capabilities': sorted(caps | {'chat', 'script', 'review', 'translate'}),
                'status': 'configured' if cp.get('api_key') else 'unconfigured',
                'fallback': cp.get('fallback', True),
                'weight': cp.get('weight', 50),
                'builtin': False,
            })
        return result

    def get_active(self, task_type=None):
        if task_type and task_type in getattr(self, 'LLM_TASK_KEYS', {}):
            v = ((self.config.get('llm') or {}).get('models') or {}).get(
                self.LLM_TASK_KEYS[task_type], '')
            if v and ':' in v and not v.startswith('http'):
                pid, mn = v.split(':', 1)
                cust = next((c for c in self._custom if c['id'] == pid), None) or {}
                return {'id': pid, 'model': mn, 'name': cust.get('name', pid),
                        'base_url': cust.get('base_url', '')}
            return {'id': 'llm-ustc', 'model': v,
                    'name': 'USTC 网关（内置文本）', 'builtin': True}
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
        out = {tt: self._active.get(tt) for tt in self.TASK_TYPES}
        llm_models = (self.config.get('llm', {}) or {}).get('models', {})
        for tt, key in self.LLM_TASK_KEYS.items():
            v = llm_models.get(key, '')
            if v and ':' in v and not v.startswith('http'):
                pid, mn = v.split(':', 1)
                out[tt] = {'id': pid, 'model': mn}
            else:
                out[tt] = {'id': 'llm-ustc', 'model': v}
        return out

    def get_provider(self, task_type):
        return self.get_active(task_type)

    def set_active(self, task_type, provider_id, model=None):
        """切换活跃提供商，可选指定模型名；LLM 任务写 config.llm.models"""
        if task_type not in self.TASK_TYPES:
            raise ValueError(f'Unknown task type: {task_type}')
        all_ids = set(self._providers.keys()) | {c['id'] for c in self._custom} | {'llm-ustc'}
        if provider_id not in all_ids:
            raise ValueError(f'Unknown provider: {provider_id}')
        if task_type in self.LLM_TASK_KEYS:
            key = self.LLM_TASK_KEYS[task_type]
            llm = self.config.setdefault('llm', {})
            models = llm.setdefault('models', {})
            if provider_id == 'llm-ustc':
                model = (model or models.get(key)
                         or self.config.get('llm', {}).get('model') or 'default')
                models[key] = model
            else:
                cp = self._custom_by_id(provider_id)
                if not cp or not cp.get('api_key'):
                    raise ValueError('LLM 任务需带 Key 的 API 提供商')
                if not model:
                    cur = str(models.get(key) or '')
                    pm = cur.split(':', 1)
                    model = (pm[1] if len(pm) == 2 and pm[0] == provider_id
                             else (cp.get('models') or [{}])[0].get('id') or 'default')
                models[key] = '%s:%s' % (provider_id, model)
            save_config(self.config)
            return {'task_type': task_type, 'provider_id': provider_id, 'model': model}
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
            'fallback': provider_data.get('fallback', True),
            'weight': provider_data.get('weight', 50),
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
                for k in ('name', 'base_url', 'api_key', 'models', 'fallback', 'weight'):
                    if k in updates:
                        cp[k] = updates[k]
                self._mp['custom_providers'] = self._custom
                self.config['model_providers'] = self._mp
                save_config(self.config)
                return cp
        raise ValueError(f'Custom provider not found: {provider_id}')


    def import_from_config(self, path=None, text=None, overwrite_llm=False):
        """从本地 config.json（路径或粘贴文本）一键导入模型配置：
        - llm 段（base_url/api_key，overwrite_llm=True 时覆盖本机）
        - model_providers.custom_providers（按 id 新增/更新）
        返回 {imported:[id], llm: 'kept|overwritten', errors:[...]}"""
        errors, imported = [], []
        try:
            if text:
                src = json.loads(text)
            else:
                with open(path or CONFIG_PATH, encoding='utf-8') as f:
                    src = json.load(f)
        except Exception as e:
            return {'imported': [], 'llm': 'kept', 'errors': [str(e)[:150]]}
        smp = src.get('model_providers') or {}
        for cp in smp.get('custom_providers') or []:
            try:
                if not cp.get('id') or not cp.get('base_url'):
                    raise ValueError('缺 id/base_url')
                pid = cp['id']
                cur = self._custom_by_id(pid)
                fields = {k: cp[k] for k in ('name', 'base_url', 'api_key', 'models',
                                             'fallback', 'weight') if k in cp}
                fields['id'] = pid
                if cur:
                    self.update_provider(pid, fields)
                else:
                    self.add_provider(fields)
                imported.append(pid)
            except Exception as e:
                errors.append('%s: %s' % (cp.get('id', '?'), str(e)[:80]))
        slm = src.get('llm') or {}
        llm_state = 'kept'
        if overwrite_llm and slm.get('base_url') and slm.get('api_key'):
            self.config.setdefault('llm', {}).update(
                {'base_url': slm['base_url'], 'api_key': slm['api_key']})
            if slm.get('models'):
                self.config['llm'].setdefault('models', {}).update(slm['models'])
            save_config(self.config)
            llm_state = 'overwritten'
        return {'imported': imported, 'llm': llm_state, 'errors': errors}

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


COMFY_PORTS = {'flux': 8192, 'wan': 8189, 'h3': 8188, 'h3d': 8193,
               'hunyuan3d': 8193, 'sdxl': 8191, 'hunyuan': 8190}


class HealthMixin:
    """提供商连通性探测 + chat 多候选轮换（故障自动切下一个 fallback 候选）。"""

    def health(self):
        import time as _t
        out = []
        for p in self.list_providers():
            cp0 = self._custom_by_id(p['id']) or {}
            pid, item = p['id'], {'id': p['id'], 'name': p['name'],
                                  'builtin': p.get('builtin', True),
                                  'fallback': cp0.get('fallback', True)}
            url = None
            if p['type'] == 'comfyui':
                port = COMFY_PORTS.get(p.get('instance', ''))
                if port:
                    url = f'http://127.0.0.1:{port}/'
            elif p.get('base_url'):
                base = p['base_url'].rstrip('/')
                url = base if base.endswith('/models') else base + ('' if base.endswith('/v1') else '/v1') + '/models'
            item['url'] = url or ''
            t0 = _t.time()
            if not url:
                item.update(online=False, error='无地址')
            else:
                try:
                    req = urllib.request.Request(url)
                    key = (self._custom_by_id(pid) or {}).get('api_key')
                    if key:
                        req.add_header('Authorization', f'Bearer {key}')
                    resp = urllib.request.urlopen(req, timeout=5)
                    body = resp.read(4096).decode('utf-8', 'ignore')
                    n = ''
                    try:
                        n = len(json.loads(body).get('data', []))
                    except Exception:
                        pass
                    item.update(online=resp.status < 500, latency_ms=int((_t.time() - t0) * 1000),
                                models=n, error='')
                except Exception as e:
                    item.update(online=False, latency_ms=int((_t.time() - t0) * 1000),
                                error=type(e).__name__ + ': ' + str(e)[:80])
            out.append(item)
        return out

    def _custom_by_id(self, pid):
        return next((c for c in self._custom if c['id'] == pid), None)

    def chat_candidates(self):
        """候选顺序：当前激活(自定义API) → 其余启用 fallback 的自定义 API。"""
        cands = [c for c in self._custom
                 if c.get('api_key') and c.get('fallback', True) is not False]
        cands.sort(key=lambda c: -(c.get('weight') or 50))
        ucfg = self.config.get('llm', {})
        if ucfg.get('api_key') and ucfg.get('base_url'):
            um = (ucfg.get('models') or {}).get('script', 'deepseek-v4-flash-ascend')
            cands.insert(0, {'id': 'llm-ustc', 'name': 'USTC 网关',
                             'base_url': ucfg['base_url'], 'api_key': ucfg['api_key'],
                             'models': [{'id': um}]})
        return cands

    def chat_api(self, messages, model=None, temperature=0.7, max_tokens=1024):
        """OpenAI 兼容 chat，按候选顺序自动轮换，全失败返回各错误。"""
        tried, errors = [], []
        for cp in self.chat_candidates():
            if cp['id'] in tried:
                continue
            tried.append(cp['id'])
            base = cp.get('base_url', '').rstrip('/')
            if not base.endswith('/v1') and '/chat/completions' not in base and not base.endswith('chat/completions'):
                base = base + '/v1'
            url = base if base.endswith('chat/completions') else base + '/chat/completions'
            mdl = model or (cp.get('models') or [{}])[0].get('id', '') if not base.endswith('chat/completions') else model
            body = json.dumps({'model': model or (cp.get('models') or [{}])[0].get('id', ''),
                               'messages': messages, 'temperature': temperature,
                               'max_tokens': max_tokens}).encode()
            req = urllib.request.Request(url, data=body, headers={
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + cp.get('api_key', '')})
            try:
                d = json.loads(urllib.request.urlopen(req, timeout=120).read().decode())
                return {'ok': True, 'provider': cp['id'], 'provider_name': cp['name'],
                        'tried': tried,
                        'text': d['choices'][0]['message']['content'],
                        'model': d.get('model', '')}
            except Exception as e:
                errors.append({'provider': cp['id'], 'error': str(e)[:150]})
        return {'ok': False, 'tried': tried, 'errors': errors}


class _Patched(ModelRouter, HealthMixin):
    pass
ModelRouter = _Patched  # 对外类名不变，具备 health/chat_api
