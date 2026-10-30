#!/usr/bin/env python3
"""LLM 客户端 — 调用 USTC LLM API（文本 + 多模态）

用法:
  from utils.llm import LLMClient
  client = LLMClient()
  script = client.script_write("一只猫在月球上跳舞")
  review = client.review_shot(scene_desc, [frame1_path, frame2_path])
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
import base64
import io
import urllib.request
import urllib.error
from PIL import Image

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), 'config', 'config.json')


def load_config():
    from utils.config_loader import load_config as _load
    return _load()


_LIVE_CB = None


def set_live(cb):
    """全局 LLM 流式回显开关：设置后所有 chat/chat_json 系调用走 SSE 流式并逐 delta
    回调 cb(delta)。CLI 传 print 回调即打字机输出；任务子进程 stdout 进 scheduler.log，
    日志面板轮询即见。传 None 关闭。
    """
    global _LIVE_CB
    _LIVE_CB = cb


class LLMClient:
    def __init__(self, config=None):
        self.config = config or load_config()
        llm_cfg = self.config['llm']
        self.base_url = llm_cfg['base_url']
        self.api_key = llm_cfg['api_key']
        self.models = llm_cfg['models']

    def _refresh(self):
        """config.json 被手改/面板切换后自动重读（mtime 变化才读盘）。"""
        try:
            import os
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))), 'config', 'config.json')
            mt = os.path.getmtime(path)
            if getattr(self, '_cfg_mt', None) != mt:
                self.config = load_config()
                llm_cfg = self.config['llm']
                self.base_url, self.api_key = llm_cfg['base_url'], llm_cfg['api_key']
                self.models = llm_cfg['models']
                self._cfg_mt = mt
        except Exception:
            pass

    def _resolve(self, model):
        """模型名可为 'provider_id:模型名' 前缀 → 路由到对应自定义 API。返回(url,key,model)。"""
        if model and ':' in model and not model.startswith('http'):
            pid, mname = model.split(':', 1)
            for cp in (self.config.get('model_providers', {}) or {}).get('custom_providers', []):
                if cp.get('id') == pid and cp.get('api_key'):
                    base = cp.get('base_url', '').rstrip('/')
                    if base and not base.endswith('/v1'):
                        base += '/v1'
                    return base, cp['api_key'], mname or 'default'
        return self.base_url, self.api_key, model

    def chat(self, messages: list, model: str = None, temperature: float = 0.7,
             max_tokens: int = 4096, timeout: int = 300, retries: int = 2) -> str:
        """调用 LLM 文本对话，返回 assistant 回复文本（超时自动重试）。

        set_live() 启用全局回显后自动走 SSE 流式并逐 delta 回调（CLI/日志面板可见）。
        """
        if _LIVE_CB is not None:
            return self.chat_stream(messages, model=model, temperature=temperature,
                                    max_tokens=max_tokens, timeout=timeout,
                                    on_chunk=_LIVE_CB)
        return self._chat_plain(messages, model=model, temperature=temperature,
                                max_tokens=max_tokens, timeout=timeout, retries=retries)

    def _chat_plain(self, messages: list, model: str = None, temperature: float = 0.7,
                    max_tokens: int = 4096, timeout: int = 300, retries: int = 2) -> str:
        """非流式 chat 原始实现（超时自动重试）。"""
        self._refresh()
        model = model or self.models['script']
        base_url, api_key, model = self._resolve(model)
        payload = {
            'model': model,
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens,
        }
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        last_err = None
        for attempt in range(retries + 1):
            req = urllib.request.Request(
                f'{base_url}/chat/completions',
                data=data,
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {api_key}',
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    result = json.loads(resp.read())
                content = result['choices'][0]['message']['content']
                if content is None:
                    raise RuntimeError('LLM returned None content')
                return content
            except urllib.error.HTTPError as e:
                raise RuntimeError(f'LLM API {e.code}: {e.read().decode()}')
            except Exception as e:
                last_err = e
                if attempt < retries:
                    import time
                    time.sleep(3)
        raise last_err

    def chat_stream(self, messages: list, model: str = None, temperature: float = 0.7,
                    max_tokens: int = 4096, timeout: int = 300, on_chunk=None) -> str:
        """流式调用 LLM（OpenAI SSE），逐 delta 回调 on_chunk(delta)；返回完整文本。

        失败自动回退非流式 chat。
        """
        self._refresh()
        model = model or self.models['script']
        base_url, api_key, model = self._resolve(model)
        payload = {
            'model': model,
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens,
            'stream': True,
        }
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(
            f'{base_url}/chat/completions',
            data=data,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
            },
        )
        out = []
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                for raw in resp:
                    line = raw.decode('utf-8', 'ignore').strip()
                    if not line.startswith('data:'):
                        continue
                    body = line[5:].strip()
                    if body == '[DONE]':
                        break
                    try:
                        delta = json.loads(body)['choices'][0]['delta'].get('content')
                    except Exception:
                        continue
                    if delta:
                        out.append(delta)
                        if on_chunk:
                            try:
                                on_chunk(delta)
                            except Exception:
                                pass
            text = ''.join(out)
            if text:
                return text
        except Exception:
            pass
        return self._chat_plain(messages, model=model, temperature=temperature,
                                max_tokens=max_tokens, timeout=timeout)

    def chat_json(self, messages: list, model: str = None,
                  temperature: float = 0.7, timeout: int = 300, retries: int = 0,
                  max_tokens: int = 16384) -> dict:
        """调用 LLM 并解析 JSON 结果（提取 ```json 代码块或直接解析）

        v17 M4：解析失败时带报错重试（把畸形输出+错误信息回喂 LLM 让其自修），默认 2 次。
        max_tokens 默认 16384：推理模型 reasoning+完整 JSON 易超 4096，截断→content None。
        """
        last_err = None
        last_text = ''
        for i in range(retries + 1 + 2):  # 用户 retries + 解析重试 2 次
            text = (last_text if i and last_text else
                    self.chat(messages, model=model, temperature=temperature,
                              timeout=timeout, retries=retries, max_tokens=max_tokens))
            try:
                return self._extract_json(text)
            except (json.JSONDecodeError, ValueError) as e:
                last_err, last_text = e, text
                print(f'  [json] parse failed ({e}), retry {i + 1}/2 with error feedback...')
                messages = messages + [
                    {'role': 'assistant', 'content': text},
                    {'role': 'user', 'content':
                        f'你的输出不是合法 JSON（错误：{e}）。\n'
                        '请重新输出，严格 JSON 格式，不要加任何解释文字或 markdown 代码块。'},
                ]
        raise ValueError(f'LLM JSON parse failed after retries: {last_err}')

    # v17 M4：常见畸形修复（尾逗号/单引号/裸键/Python 字面量/智能引号/代码块残留）
    _RE_TRAILING = __import__('re').compile(r',\s*([}\]])')
    _RE_PY_LIT = __import__('re').compile(r'\b(True|False|None)\b')

    @classmethod
    def _repair_json(cls, text: str) -> str:
        text = text.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
        text = cls._RE_PY_LIT.sub(lambda m: {'True': 'true', 'False': 'false', 'None': 'null'}[m.group(1)], text)
        text = cls._RE_TRAILING.sub(r'\1', text)
        return text

    @classmethod
    def _extract_json(cls, text: str) -> dict:
        """从 LLM 回复中提取 JSON（支持 ```json 代码块和裸 JSON + 畸形修复）"""
        text = text.strip()
        if text.startswith('```'):
            lines = text.split('\n')
            lines = [l for l in lines if not l.startswith('```')]
            text = '\n'.join(lines)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1:
                cand = text[start:end + 1]
                try:
                    return json.loads(cand)
                except json.JSONDecodeError:
                    return json.loads(cls._repair_json(cand))
            return json.loads(cls._repair_json(text))

    @staticmethod
    def _image_to_base64(path: str, max_size: int = 512) -> str:
        """读取图片并转为 base64 data URL，自动缩放到 max_size 内以减少 payload"""
        img = Image.open(path)
        if img.mode in ('RGBA', 'P', 'LA', 'PA'):
            img = img.convert('RGB')
        w, h = img.size
        scale = min(1.0, max_size / max(w, h))
        if scale < 1.0:
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=85)
        data = base64.b64encode(buf.getvalue()).decode('ascii')
        return f'data:image/jpeg;base64,{data}'

    def script_write(self, concept: str, character_desc: str = None,
                     target_duration: float = None, style_hint: str = None,
                     five_dim_guide: dict = None, rag_context: str = None) -> dict:
        """概念→分镜脚本 JSON（v1: 含角色锚 + 每镜 camera 角度 + 背景描述）

        Args:
            target_duration: 目标总时长（秒）。None 时默认 2-5 镜短片，
                指定时按每镜~4s 动态计算镜头数（解锁长片）。
            style_hint: SKILL 文风指令（注入 system prompt，如"治愈系短片剧本：…"）。
            five_dim_guide: 五维提示词模板（SKILL/templates/*.yaml 的 five_dim_guide 段），
                注入 system prompt 约束每镜 five_dim 的词汇域（M5a）。
            rag_context: RAG 检索的参考资料文本（utils/rag.py，M5b）——
                长文档相关片段，编剧从中取材但不照抄。
        """
        char_section = ''
        if character_desc:
            char_section = (
                f'  "character": {{\n'
                f'    "desc": "{character_desc}"\n'
                f'  }},\n'
            )
        else:
            # M6-R-N：无 --character 时也必须产出主角色（小说路线：人物卡=外观唯一来源）
            char_section = (
                '  "character": {\n'
                '    "desc": "主角外貌中文描述（具体可画：性别年龄体型/发色发型/五官特征/'
                '肤色/常规着装/配饰）。若参考资料含人物卡，外貌必须严格按人物卡，不要重新发明",\n'
                '  },\n'
            )
        if target_duration:
            n_shots = max(2, round(target_duration / 4))
            shot_range = f'{max(2, n_shots - 2)}-{n_shots + 2}'
            shot_instruction = f'创作一个约{shot_range}个镜头的分镜脚本，总时长约{target_duration:.0f}秒。'
        else:
            shot_instruction = '创作一个2-5个镜头的短片分镜脚本。'

        fd_section = ''
        if isinstance(five_dim_guide, dict) and five_dim_guide:
            lines = [f'    - {k}: {str(v).strip()}' for k, v in five_dim_guide.items()
                     if str(v or '').strip()]
            if lines:
                fd_section = ('五维提示词模板（每镜 five_dim 字段在此词汇域内填写）：\n'
                              + '\n'.join(lines) + '\n')

        rag_section = ''
        if rag_context and str(rag_context).strip():
            rag_section = ('参考资料（来自用户文档，可取材事实/数据/细节，不要照抄原句）：\n'
                           f'{str(rag_context).strip()}\n')

        system = (
            f'你是视频编剧。根据用户给出的中文概念，{shot_instruction}\n'
            + (f'文风要求：{str(style_hint).strip()}\n' if style_hint else '')
            + fd_section
            + rag_section
            + '输出严格JSON格式，不要加任何解释文字。\n'
            'JSON schema:\n'
            '{\n'
            f'{char_section}'
            '  "title": "标题",\n'
            '  "concept": "原始概念",\n'
            '  "style": "英文风格描述，如 cinematic, warm sunset tone, 35mm film grain",\n'
            '  "shots": [\n'
            '    {\n'
            '      "id": 1,\n'
            '      "scene_desc": "中文场景描述，详细描述画面内容（含角色动作）",\n'
            '      "narration": "中文旁白文本，字数与时长匹配（中文约4字/秒）",\n'
            '      "speaker": "旁白 或 角色名（该句由谁说出；默认旁白，角色台词才标角色名）",\n'
            '      "background_desc": "中文背景描述，只描述环境不含角色",\n'
            '      "duration": 5,\n'
            '      "camera": {\n'
            '        "yaw": 0,\n'
            '        "pitch": 15,\n'
            '        "fov": 35,\n'
            '        "distance": 0,\n'
            '        "desc": "镜头描述，如 wide shot, slow pan"\n'
            '      },\n'
            '      "five_dim": {\n'
            '        "visual": "画面主体与环境的具象描述（人物/物体/色调/光线质感）",\n'
            '        "motion": "动作与节奏（主体动作、镜头运动速度、情绪节奏）",\n'
            '        "camera": "运镜语言（推拉摇移/景别变化，英文如 slow dolly-in, rack focus）",\n'
            '        "audio": "听觉设计（旁白情绪、环境音、BGM 氛围，中文一句话）",\n'
            '        "narrative": "本镜在整片叙事中的作用（铺垫/转折/高潮/收束，一句话）"\n'
            '      },\n'
            '      "slowmo": {"multiplier": 2, "mode": "slowmo"},\n'
            '      "transition_out": "rife"\n'
            '    }\n'
            '  ]\n'
            '}\n'
            '要求：\n'
            '- 每镜3-5秒（duration字段）\n'
            '- narration字数 = duration × 4（±20%），如5秒约20字\n'
            '- 分镜铁律（优先级从高到低）：台词/旁白零删改语义 > 出场人物前后一致 > 只描述动作与状态（不写心理活动）\n'
            '- 旁白超过20字时必须拆成多个镜头（每镜换视角/景别），不许一个镜头念长段\n'
            '- 黄金6秒：第1镜必须3秒内出主体（不要空镜开场过久）\n'
            '- scene_desc只写画面内容与动作，禁止写光影/色调词汇（光影由背景与风格统一承担，特殊光照写进five_dim.visual）；具体禁止：月光、阳光、灯光、烛光、阴影、逆光、霞光、辉光、明亮、昏暗等词——手持物（提灯/蜡烛）本身可以写\n'
            '- 连续动作写"起始凝固态"（如"剑举至头顶即将劈下"而非"剑已劈落"），供首帧驱动\n'
            '- scene_desc要具体，包含主体、动作、环境\n'
            '- background_desc只描述场景环境，不包含角色\n'
            '- camera.yaw是绕角色旋转的水平角度（0=正面，90=右侧，180=背面，270=左侧）\n'
            '- camera.pitch是俯仰角度（0=平视，正值俯视，负值仰视，范围-30到30）\n'
            '- camera.fov是视野角度（35=窄角特写，50=标准，70=广角）\n'
            '- camera.distance填0即可（自动取景）\n'
            '- 不同镜头用不同yaw角度展示角色多角度\n'
            '- 镜头之间有叙事逻辑\n'
            '- slowmo: 可选，对需要慢动作的镜头设置。multiplier为帧倍率（2=2倍慢放），mode为"slowmo"（慢放）或"smooth"（高帧率平滑）。不需要慢动作的镜头省略此字段\n'
            '- transition_out: 此镜头到下一镜头的过渡方式。"rife"=光流插帧（默认，适合相邻场景），"crossfade"=交叉淡化（适合场景跳跃），"cut"=硬切（适合强对比）。最后一镜可省略\n'
            '- five_dim: 五维结构化视频提示词（必填）。visual/motion/camera 会被拼进 T2V 生成 prompt，要具体可执行；audio/narrative 供编排与审片参照。camera 维与外层 camera 字段保持一致语义'
        )
        messages = [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': f'概念：{concept}'},
        ]
        script = self.chat_json(messages, model=self.models['script'],
                                temperature=0.7, timeout=480, retries=2)
        # 结构校验：chat_json 只保证合法 JSON，不保证含 title/shots（E2E 实测缺字段崩 pipeline）
        if not (script.get('title') and script.get('shots')):
            try:
                print('  [script] 缺 title/shots 字段，回喂重问一轮...')
                messages = messages + [
                    {'role': 'assistant', 'content': json.dumps(script, ensure_ascii=False)},
                    {'role': 'user', 'content':
                        '你的输出缺少必需字段 "title" 和/或 "shots"。'
                        '请重新输出完整JSON：必须含 "title"（字符串）与 "shots"（分镜数组）。'},
                ]
                s2 = self.chat_json(messages, model=self.models['script'],
                                    temperature=0.3, timeout=480, retries=1)
                if s2.get('title') and s2.get('shots'):
                    script = s2
            except Exception:
                pass
        return self._scrub_scene_desc_lighting(script)

    # S4 分镜铁律：scene_desc 禁光影词。prompt 层约束对 flash 模型不稳（两轮验证
    # 违例 2/9、3/9），改为代码层检测 + 一轮 LLM 定向修复（Toonflow fix-loop 模式）。
    _SCENE_LIGHTING_WORDS = ('月光', '阳光', '灯光', '烛光', '阴影', '逆光', '霞光',
                             '辉光', '光影', '明亮', '昏暗', 'light', 'shadow', 'glow')

    def _scrub_scene_desc_lighting(self, script: dict) -> dict:
        """检测 scene_desc 光影违例并 LLM 修复一轮；失败保留原文（非致命）。"""
        shots = script.get('shots') or []
        bad = [{'i': i, 'scene_desc': s.get('scene_desc') or ''}
               for i, s in enumerate(shots)
               if any(w in (s.get('scene_desc') or '') for w in self._SCENE_LIGHTING_WORDS)]
        if not bad:
            return script
        try:
            system = (
                '你是分镜表审核员。把给定 scene_desc 中的光影/色调词汇全部去除，'
                '只保留人物、动作、道具、环境事实；动作语义不许变；手持物（提灯/蜡烛等）保留。\n'
                '输出严格JSON：{"fixed": [{"i": 序号, "scene_desc": "修改后"}]}'
            )
            messages = [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': json.dumps(bad, ensure_ascii=False)},
            ]
            r = self.chat_json(messages, model=self.models['script'],
                               temperature=0.1, timeout=180, retries=1)
            fixed = {f.get('i'): f.get('scene_desc', '') for f in (r.get('fixed') or [])
                     if isinstance(f, dict) and f.get('scene_desc')}
            n = 0
            for i, desc in fixed.items():
                if 0 <= i < len(shots) and not any(
                        w in desc for w in self._SCENE_LIGHTING_WORDS):
                    shots[i]['scene_desc'] = desc
                    n += 1
            if n:
                print(f'  [s4-scrub] scene_desc 光影词修复 {n}/{len(bad)} 镜')
        except Exception:
            pass
        return script

    def consistency_anchors(self, script: dict) -> dict:
        """剧本→全局一致性锚点（M6.1，BigBanana consistencyAnchors 精简版）

        一次 LLM 调用产出全片统一的美术方向：style_anchor 是一段文字锚点，
        后续每个镜头/场景提示词生成时强制注入——风格漂移从逐镜博弈变单点约束。
        失败返回 {}（非致命，流水线继续）。
        """
        shots_summary = '\n'.join(
            f"- shot{s.get('id')}: {str(s.get('scene_desc', ''))[:60]}"
            for s in (script.get('shots') or [])[:10])
        system = (
            '你是美术指导。根据剧本设定全片统一的视觉方向，保证多镜头生成时风格不漂移。\n'
            '输出严格JSON，不要加任何解释文字。\n'
            'JSON schema:\n'
            '{\n'
            '  "style_anchor": "一段英文统一风格锚点（色调+质感+光影+画风的浓缩描述，'
            '将被注入每个镜头的画面prompt，30词以内）",\n'
            '  "color": "主色调与色彩约束（英文，含主色/辅色/禁止色）",\n'
            '  "lighting": "光源方向与光质（英文，如 golden hour backlight, soft diffused）",\n'
            '  "mood": "情绪基调关键词（英文，3-5个词）"\n'
            '}\n'
            '要求：锚点必须具体可执行（避免 vague 的 beautiful/high quality），'
            '与剧本整体氛围一致'
        )
        messages = [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content':
                f'标题：{script.get("title", "")}\n'
                f'整体风格：{script.get("style", "")}\n'
                f'分镜概要：\n{shots_summary}'},
        ]
        try:
            r = self.chat_json(messages, model=self.models['prompt_opt'], temperature=0.3)
            return r if isinstance(r, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _anchors_block(anchors: dict) -> str:
        """一致性锚点→提示词注入段（M6.1 内部助手）"""
        if not isinstance(anchors, dict) or not anchors:
            return ''
        lines = [f'- {k}: {str(v).strip()}' for k, v in anchors.items() if str(v or '').strip()]
        if not lines:
            return ''
        return ('全片一致性锚点（必须融入，保证跨镜头风格统一）：\n' + '\n'.join(lines) + '\n')

    def optimize_prompt(self, scene_desc: str, style: str, five_dim: dict = None,
                        ref_frame: bool = False, anchors: dict = None) -> str:
        """中文场景描述→英文 video_prompt（M5a 五维融入；M6.1 ref_frame 外观解耦+anchors）"""
        fd_block, fd_rule = '', ''
        if isinstance(five_dim, dict) and five_dim:
            parts = []
            for key, tag in (('visual', 'Visual'), ('motion', 'Motion'), ('camera', 'Camera')):
                v = str(five_dim.get(key) or '').strip()
                if v:
                    parts.append(f'[{tag}] {v}')
            if parts:
                fd_block = '五维结构化提示：\n' + '\n'.join(parts) + '\n'
                fd_rule = ('- 五维提示必须全部融入prompt：[Visual]=画面主体与环境，'
                           '[Motion]=动作与节奏，[Camera]=运镜语言（直接用其英文术语）\n')
        ref_rule = ''
        if ref_frame:
            ref_rule = (
                '- 首帧参考图已包含角色完整外观：prompt 中不要描述角色的服装/毛色/五官等'
                '外观细节，用简短代称指代角色（如 the girl, the fox），只描述其动作、姿态、'
                '表情倾向与和环境的互动\n')
        anchors_block = self._anchors_block(anchors)
        anchors_rule = ('- 一致性锚点必须融入风格词（保证跨镜头统一）\n' if anchors_block else '')
        system = (
            '你是视频生成prompt优化器。将中文场景描述翻译为英文的video generation prompt。\n'
            '要求：\n'
            '- 保留所有视觉细节（主体、动作、环境、光线）\n'
            '- 加入风格修饰词（来自style字段）\n'
            + fd_rule
            + ref_rule
            + anchors_rule
            + '- 英文，不超过100词\n'
            '- 不要加任何解释，只输出prompt文本'
        )
        user = (f'{anchors_block}{fd_block}场景描述：{scene_desc}\n风格：{style}'
                if (anchors_block or fd_block)
                else f'场景描述：{scene_desc}\n风格：{style}')
        messages = [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user},
        ]
        return self.chat(messages, model=self.models['prompt_opt'], temperature=0.5).strip()

    def optimize_character_prompt(self, character_desc: str) -> str:
        """中文角色描述→英文 FLUX character_prompt（正面站立、纯色背景、角色参考图）"""
        system = (
            '你是角色设计prompt优化器。将中文角色描述翻译为英文的FLUX image generation prompt。\n'
            '要求：\n'
            '- 保留角色所有外观细节（物种、毛色/肤色、服装、配饰、体型）\n'
            '- 角色必须是自然站立姿态（standing upright on the ground, natural pose），绝不能躺倒、侧卧或悬浮在空中\n'
            '- 固定后缀：standing upright on the ground, full body, front view, plain white background, high detail, character reference sheet\n'
            '- 英文，不超过80词\n'
            '- 不要加任何解释，只输出prompt文本'
        )
        messages = [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': f'角色描述：{character_desc}'},
        ]
        return self.chat(messages, model=self.models['prompt_opt'], temperature=0.5).strip()

    def optimize_costume_prompts(self, base_look: str, costumes: list) -> list:
        """衣橱系统（BigBanana 借鉴）：Base Look 锁脸/体型，N 套服装只变穿着。

        costumes: [{'name': '出场长衫', 'desc': '中文服装描述'}, ...]
        返回 [{'name', 'prompt'}]——Base Look 特征全保留，仅替换服装段（换衣不换脸）。
        """
        system = (
            '你是角色服装设计prompt优化器。给定角色的 Base Look（锁定脸型/发式/体型/种族等'
            '不可变特征）和多套服装描述，为每套服装生成英文 FLUX prompt。\n'
            '规则：\n'
            '1. 每条 prompt 必须完整复述 Base Look 的不可变特征（脸型/胡须/发型/体型/年龄感），'
            '确保跨服装角色同一张脸（换衣不换脸）\n'
            '2. 只替换服装/配饰/状态段为对应 costume 描述\n'
            '3. 固定后缀：standing upright on the ground, full body, front view, '
            'plain white background, high detail, character reference sheet\n'
            '4. 英文，每条不超过 90 词\n'
            f'输出 JSON: {{"outfits": [{{"name": "服装名", "prompt": "..."}}, ...]}}，只输出 JSON')
        msgs = [{'role': 'system', 'content': system},
                {'role': 'user', 'content': json.dumps(
                    {'base_look': base_look, 'costumes': costumes}, ensure_ascii=False)}]
        r = self.chat_json(msgs, model=self.models['prompt_opt'], temperature=0.3)
        outfits = r.get('outfits') or []
        assert len(outfits) == len(costumes), f'衣橱条数不齐: {len(outfits)}/{len(costumes)}'
        return outfits

    def optimize_character_multiview_prompts(self, character_desc: str) -> dict:
        """中文角色描述→英文 FLUX 三视图 prompt（正面/侧面/背面）

        Returns:
            {'front': str, 'left': str, 'back': str}
        """
        system = (
            '你是角色设计prompt优化器。将中文角色描述翻译为英文的FLUX image generation prompt，生成三个视角。\n'
            '要求：\n'
            '- 三个视角的角色必须是同一个人，外观完全一致（相同服装、发型、体型、配色）\n'
            '- 保留角色所有外观细节（物种、毛色/肤色、服装、配饰、体型）\n'
            '- 角色必须是自然站立姿态，绝不能躺倒或悬浮\n'
            '- 固定后缀：standing upright on the ground, full body, plain white background, high detail, character reference sheet\n'
            '- front view / left side view / back view 分别对应正面、左侧、背面\n'
            '- 英文，每个prompt不超过80词\n'
            '- 输出JSON格式：{"front": "...", "left": "...", "back": "..."}\n'
            '- 不要加任何解释'
        )
        messages = [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': f'角色描述：{character_desc}'},
        ]
        result = self.chat(messages, model=self.models['prompt_opt'], temperature=0.3)
        import json
        try:
            return json.loads(result)
        except Exception:
            base = self.optimize_character_prompt(character_desc)
            return {
                'front': base,
                'left': base.replace('front view', 'left side view'),
                'back': base.replace('front view', 'back view'),
            }

    def optimize_character_turnaround_prompt(self, character_desc: str) -> str:
        """角色四视图设定图 prompt（M6-S3，Toonflow art_character.md 移植）。

        单图承载 人像特写+正/侧/后视图 四格并排——比三张图省 2 次生图，
        且单图内天然一致性（同一次生成）。FLUX 文字渲染弱，模板强调"图中不要文字"。
        """
        system = (
            '你是角色设计prompt优化器。将中文角色描述翻译为英文的FLUX image generation prompt，'
            '生成角色四视图设定图（character turnaround sheet）。\n'
            'Toonflow 式模板（方括号段按角色描述填充，其余固定）：\n'
            '[性别/物种] character turnaround sheet, four-panel lineup on one image:\n'
            'head-and-shoulders close-up + front view + side view + back view,\n'
            '[五官/毛色特征，由角色描述自然推导]，[整体气质]，\n'
            '[肤色/毛色]，[身高体型体态]，[发色发长/头部特征]，[常规着装，柔和低饱和色调]，\n'
            'full body head to toe completely visible, no cropping, natural standing pose,\n'
            'same character identical appearance across all four panels,\n'
            'plain neutral light background, soft even lighting, no harsh shadows,\n'
            'high detail, character design sheet, no text in image\n'
            '要求：\n'
            '- 保留角色所有外观细节（物种、毛色/肤色、服装、配饰、体型）\n'
            '- 不预设五官（由角色描述推导）；着装为日常默认态\n'
            '- 四格必须是同一角色（面部/发型/服装/配色完全一致）\n'
            '- 英文，不超过110词，单段输出\n'
            '- 不要加任何解释，只输出prompt文本'
        )
        messages = [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': f'角色描述：{character_desc}'},
        ]
        return self.chat(messages, model=self.models['prompt_opt'], temperature=0.4).strip()

    def optimize_scene_prompt(self, character_desc: str, scene_desc: str,
                              style: str, anchors: dict = None) -> str:
        """角色+场景描述→英文 FLUX 场景图 prompt（角色自然融入场景，站立姿态）

        M6.1：character_desc 应传角色 canonical 英文 prompt（唯一外观来源），
        指令要求逐字保留其外观关键词不得自由发挥（Toonflow 防文字漂移）；
        anchors 为全片一致性锚点（M6.1）。
        """
        anchors_block = self._anchors_block(anchors)
        anchors_rule = ('- 一致性锚点必须融入（保证跨镜头风格统一）\n' if anchors_block else '')
        system = (
            '你是场景图生成prompt优化器。将角色描述和场景描述组合为英文的FLUX image generation prompt。\n'
            '要求：\n'
            '- 角色自然融入场景中（角色是画面主体之一，但场景环境完整呈现）\n'
            '- 角色外观细节必须逐字保留自角色描述（它是唯一外观来源），不得改写、增删或自由发挥\n'
            '- 角色必须是自然姿态（如站立、行走、跳跃），与场景互动，绝不能躺倒或无故悬浮\n'
            '- 保留场景所有环境细节（地形、天空、光线、建筑）\n'
            '- 加入风格修饰词（来自style字段）\n'
            + anchors_rule
            + '- 英文，不超过100词\n'
            '- 不要加任何解释，只输出prompt文本'
        )
        messages = [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content':
                f'{anchors_block}角色描述：{character_desc}\n场景描述：{scene_desc}\n风格：{style}'},
        ]
        return self.chat(messages, model=self.models['prompt_opt'], temperature=0.5).strip()

    def optimize_background_prompt(self, background_desc: str, style: str,
                                   anchors: dict = None) -> str:
        """中文背景描述→英文 FLUX background_prompt（无角色；M6.1 anchors 注入）"""
        anchors_block = self._anchors_block(anchors)
        anchors_rule = ('- 一致性锚点必须融入（保证跨镜头风格统一）\n' if anchors_block else '')
        system = (
            '你是背景生成prompt优化器。将中文场景环境描述翻译为英文的FLUX image generation prompt。\n'
            '要求：\n'
            '- 只描述环境（地形、天空、建筑、植物、光线、天气），不包含任何角色或人物\n'
            '- 加入风格修饰词（来自style字段）\n'
            + anchors_rule
            + '- 固定后缀：no character, no person, empty scene, cinematic\n'
            '- 英文，不超过60词\n'
            '- 不要加任何解释，只输出prompt文本'
        )
        messages = [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': f'{anchors_block}背景描述：{background_desc}\n风格：{style}'},
        ]
        return self.chat(messages, model=self.models['prompt_opt'], temperature=0.5).strip()

    def optimize_fastline_prompt(self, narration: str, concept: str) -> str:
        """旁白/概念 → 英文无字单帧画面 prompt（供 fastline FLUX 生图）。

        强约束：忠实呈现旁白主体（物种/物件/场景），可加风格，不含文字/字幕。
        """
        system = (
            '你是短视频单帧画面prompt优化器。把中文旁白/概念翻译成英文的FLUX image generation prompt。\n'
            '要求：\n'
            '- 忠实保留旁白里的主体和关键元素（如"青蛙""旅行""键盘""西装"等，物种/物件/场景不能丢、不能替换成别的）\n'
            '- 可补充风格与氛围词（cinematic, high detail, 横图感）\n'
            '- 不要出现任何文字/字幕/logo（silent, no text）\n'
            '- 英文，不超过80词\n'
            '- 只输出prompt文本，不加解释\n'
            f'- 整体概念背景：{concept}'
        )
        messages = [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': f'旁白/概念：{narration}'},
        ]
        return self.chat(messages, model=self.models['prompt_opt'], temperature=0.5).strip()

    def select_lut(self, concept: str, script: dict, available_styles: list) -> str:
        """根据脚本内容自动选择最佳 LUT 调色风格。

        Args:
            concept: 用户概念描述
            script: 编剧脚本 dict（含 title, shots）
            available_styles: 可用 LUT 风格列表

        Returns:
            选中的风格名（如 'cinematic'）
        """
        style_descs = {
            'cinematic': '青橙色调，经典电影感，适合冒险/剧情/史诗',
            'warm': '暖金色调，温馨柔和，适合日常/治愈/家庭',
            'cool': '冷蓝色调，清冷神秘，适合夜景/科幻/悬疑',
            'vintage': '复古褪色，怀旧质感，适合回忆/纪录片/复古',
            'vivid': '高饱和高对比，鲜艳夺目，适合旅游/风景/广告',
            'soft': '柔和 pastel，淡雅梦幻，适合童话/浪漫/治愈',
        }
        options = '\n'.join(
            f'- {s}: {style_descs.get(s, s)}' for s in available_styles
        )

        system = (
            '你是视频调色师。根据视频概念和分镜内容，选择最合适的调色风格。\n'
            f'可选风格：\n{options}\n'
            '只输出风格名称（如 cinematic），不要加任何解释。'
        )
        shots_summary = '; '.join(
            f"镜头{s['id']}：{s.get('scene_desc', '')}" for s in script.get('shots', [])
        )
        messages = [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': f'概念：{concept}\n标题：{script.get("title", "")}\n分镜：{shots_summary}'},
        ]
        result = self.chat(messages, model=self.models['prompt_opt'], temperature=0.3).strip().lower()
        # 验证返回值
        for style in available_styles:
            if style in result:
                return style
        return available_styles[0]

    def select_bgm_mood(self, concept: str, script: dict, available_moods: list) -> str:
        """根据脚本内容自动选择最佳 BGM 配乐风格。

        Args:
            concept: 用户概念描述
            script: 编剧脚本 dict
            available_moods: 可用 BGM 风格列表

        Returns:
            选中的风格名（如 'calm'）
        """
        mood_descs = {
            'calm': '平静冥想，低频和声，适合治愈/日常/自然',
            'uplifting': '振奋向上，大调琶音，适合冒险/励志/旅行',
            'mysterious': '神秘悬疑，小二度不协和，适合悬疑/探索/夜景',
            'dramatic': '戏剧紧张，低频脉冲，适合战斗/紧张/冲突',
            'playful': '活泼俏皮，五声音阶跳跃，适合童趣/搞笑/轻松',
        }
        options = '\n'.join(
            f'- {m}: {mood_descs.get(m, m)}' for m in available_moods
        )

        system = (
            '你是视频配乐师。根据视频概念和分镜内容，选择最合适的配乐风格。\n'
            f'可选风格：\n{options}\n'
            '只输出风格名称（如 calm），不要加任何解释。'
        )
        shots_summary = '; '.join(
            f"镜头{s['id']}：{s.get('scene_desc', '')}" for s in script.get('shots', [])
        )
        messages = [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': f'概念：{concept}\n标题：{script.get("title", "")}\n分镜：{shots_summary}'},
        ]
        result = self.chat(messages, model=self.models['prompt_opt'], temperature=0.3).strip().lower()
        for mood in available_moods:
            if mood in result:
                return mood
        return available_moods[0]

    def select_effects(self, script: dict, available_effects: list,
                       available_transitions: list) -> dict:
        """LLM 自动选每镜特效 + 镜头间转场（v5）。

        Args:
            script: 编剧脚本 dict（含 title, shots，每镜含 scene_desc/情绪）
            available_effects: 可用镜头内特效列表
            available_transitions: 可用 xfade 转场列表

        Returns:
            {'shots': [{'id':..,'effect':..}, ...], 'transitions': [kind, ...]}
            shots 长度 = 分镜数；transitions 长度 = shots-1
        """
        from utils.effects import EFFECTS, XFADE_KINDS
        eff_options = ' '.join(sorted(EFFECTS if available_effects is None else available_effects))
        tr_options = ' '.join(XFADE_KINDS if available_transitions is None else available_transitions)
        shots = script.get('shots', [])
        system = (
            '你是剪辑师。根据每个分镜的内容和情绪，为每个镜头选一个镜头内特效（强调/情绪表达），'
            '并为每两个镜头之间选一个 xfade 转场。\n'
            f'特效可选: {eff_options}\n'
            f'转场可选: {tr_options}\n'
            '规则：平淡连贯的叙事镜尽量用 none；爆点/紧张用 punch_in/glitch/freeze_zoom；'
            '闪回/回忆用 flash；情绪用 grain_vignette；进门/位移用 wipe；'
            '转场首选 fade/slideleft/wipe 等简单自然的，少用炫技。\n'
            '输出JSON：{"shots":[{"id":1,"effect":"none"}...],"transitions":["fade",...]}，'
            'transitions 长度 = 镜头数-1。只输出JSON。'
        )
        shots_summary = '; '.join(
            f"镜头{s.get('id')}:{s.get('scene_desc','')}|{s.get('emotion','')}" for s in shots)
        messages = [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': f'标题:{script.get("title","")}\n{shots_summary}'},
        ]
        result = self.chat_json(messages, model=self.models['prompt_opt'],
                                temperature=0.3, timeout=60, retries=1)
        shots_eff, trans = [], []
        sl = result.get('shots') if isinstance(result, dict) else None
        for s in sl or []:
            e = str(s.get('effect', 'none') or 'none')
            if e not in EFFECTS:
                e = 'none'
            shots_eff.append(e)
        tl = result.get('transitions') if isinstance(result, dict) else None
        for k in tl or []:
            trans.append(str(k) if str(k) in XFADE_KINDS else 'fade')
        # 对齐长度
        while len(shots_eff) < len(shots):
            shots_eff.append('none')
        shots_eff = shots_eff[:len(shots)]
        while len(trans) < max(0, len(shots) - 1):
            trans.append('fade')
        return {'shots': shots_eff[:len(shots)], 'transitions': trans[:max(0, len(shots)-1)]}

    def assess_completeness(self, prompt: str) -> dict:
        """6 维完整度评估（v6）：判断概念是否信息齐全。

        Returns:
            {complete: bool, dimensions: {subject,spot,emotion,style,duration,shot: 0/1},
             missing: [缺失项..], questions: [追问建议..]}
            chat_json 解析，异常兜底当 complete（不阻塞流水线）。
        """
        dims = ['subject', 'scene', 'emotion', 'style', 'duration', 'shot']
        dim_cn = {
            'subject': '主体/主角', 'scene': '场景/环境', 'emotion': '情绪基调',
            'style': '视觉风格', 'duration': '目标时长', 'shot': '镜头感/运镜',
        }
        system = (
            '你是短视频需求澄清助理。判断用户给的概念在 6 个维度上是否信息足够，列出缺失项和需要追问的问题。\n'
            '维度：subject(主体/主角)、scene(场景/环境)、emotion(情绪基调)、'
            'style(视觉风格)、duration(目标时长)、shot(镜头感/运镜)。\n'
            '规则：\n'
            '- subject/scene/emotion 是内容类，缺失必须追问；\n'
            '- subject/scene/emotion 需要【明确描述】才算已具备；仅从名词隐含推测'
            '（如"灯塔"隐含海边、"猫"隐含室内）不算已具备；\n'
            '- style/duration/shot 也需要补齐：缺失时列入 missing 并给出提示问题'
            '（如建议视觉风格/目标时长/运镜方式）；\n'
            '- 若用户说"随便"算不缺。\n'
            '输出JSON：{"dimensions":{"subject":1,"scene":0,...},"missing":["场景/环境"],'
            '"questions":["大概是什么场景？"]}。subject/scene/emotion 必须有缺失项追问。'
        )
        try:
            r = self.chat_json([
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': f'概念：{prompt}'},
            ], model=self.models['prompt_opt'], temperature=0.1, timeout=60, retries=1)
        except Exception:
            return {'complete': True, 'dimensions': dict.fromkeys(dims, 1),
                    'missing': [], 'questions': []}
        dims_map = r.get('dimensions', {}) if isinstance(r, dict) else {}
        vals = {d: (1 if dims_map.get(d) else 0) for d in dims}
        missing = [str(m) for m in (r.get('missing') or []) if m]
        questions = [str(q) for q in (r.get('questions') or []) if q]
        # 关键维度缺必给追问
        for d in ('subject', 'scene', 'emotion'):
            if not vals.get(d) and not any(dim_cn[d] in m for m in missing):
                vals[d] = 0
        # 全 6 维都齐才 complete：prompt 靠多轮追问变长变详细，style/duration/shot 也纳入追问
        complete = all(vals.values())
        return {'complete': complete, 'dimensions': vals,
                'missing': missing, 'questions': questions}

    def describe_character(self, image_path: str, name: str = None) -> str:
        """多模态：看角色三视图→英文详细外观描述（供 FLUX T2I prompt 用）"""
        name_hint = f' This character is called "{name}".' if name else ''
        system = (
            'You are a character designer. Look at the character reference sheet (three-view / turnaround)'
            f' and write a detailed English description of the character\'s appearance.{name_hint}\n'
            'Include: species/type, body shape and proportions, skin/fur/color, facial features, '
            'clothing (style, color, texture, condition), accessories, and any distinctive features.\n'
            'Output ONLY the English description text, no JSON, no explanation, no markdown. '
            'Keep it under 120 words.'
        )
        content = [
            {'type': 'text', 'text': 'Describe this character in detail for an image generation prompt.'},
            {'type': 'image_url', 'image_url': {'url': self._image_to_base64(image_path)}},
        ]
        messages = [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': content},
        ]
        return self.chat(messages, model=self.models['review'], temperature=0.3, timeout=120, retries=1).strip()

    def combine_scene_prompt(self, char_descs: list, scene_setting: str,
                              shot_desc: str, style: str = '') -> str:
        """角色描述+全局场景+镜头描述→英文 FLUX T2I prompt（多角色场景图）"""
        char_section = '\n'.join(f'Character {i+1}: {d}' for i, d in enumerate(char_descs))
        system = (
            'You are an image generation prompt writer. Combine character descriptions, scene setting,'
            ' and shot description into a single English FLUX image generation prompt.\n'
            'Requirements:\n'
            '- All characters must appear in the scene with correct spatial positions as described\n'
            '- Preserve every character appearance detail from the descriptions\n'
            '- Describe the environment, lighting, and camera angle precisely\n'
            '- English, under 150 words\n'
            '- Output ONLY the prompt text, no explanation'
        )
        user_text = (
            f'{char_section}\n\n'
            f'Scene setting: {scene_setting}\n'
            f'Shot description: {shot_desc}\n'
            f'Style: {style}' if style else ''
        )
        messages = [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user_text},
        ]
        return self.chat(messages, model=self.models['prompt_opt'], temperature=0.5).strip()

    def review_shot(self, scene_desc: str, frame_paths: list,
                    model: str = None, character_ref: str = None) -> dict:
        """多模态审片：关键帧+场景描述→{score, dimensions, feedback, pass}

        v1: 若提供 character_ref，增加 character_consistency 维度（5维打分）。"""
        model = model or self.models['review']
        n_dims = 5 if character_ref else 4
        char_dim = (
            '\n5. character_consistency: 角色与参考图的一致性（外观/服装/毛色/体型）'
            if character_ref else ''
        )
        char_instr = (
            '\n第一张图是角色参考图，请对比后续关键帧中角色与参考图的一致性。'
            if character_ref else ''
        )
        system = (
            f'你是视频审片专家。根据给定的场景描述和关键帧截图，按{n_dims}个维度打分（每维1-10）：\n'
            '1. consistency: 画面内容与场景描述的匹配度\n'
            '2. quality: 画质（清晰度、色彩、构图）\n'
            '3. motion: 运动自然度、流畅度\n'
            '4. artifact: 无明显AI生成痕迹（畸形、融合、闪烁等）'
            f'{char_dim}\n'
            f'综合分={n_dims}维均值。≥7分通过。{char_instr}\n'
            '输出严格JSON格式：\n'
            '{"score": 8, "dimensions": {"consistency": 8, "quality": 9, "motion": 7, '
            '"artifact": 8' + (', "character_consistency": 8' if character_ref else '') +
            '}, "feedback": "具体反馈", "pass": true}'
        )
        content = [{'type': 'text', 'text': f'场景描述：{scene_desc}\n请按{n_dims}维度打分'}]
        if character_ref:
            b64 = self._image_to_base64(character_ref)
            content.append({'type': 'image_url', 'image_url': {'url': b64}})
        for path in frame_paths:
            b64 = self._image_to_base64(path)
            content.append({'type': 'image_url', 'image_url': {'url': b64}})

        messages = [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': content},
        ]
        r = self.chat_json(messages, model=model, temperature=0.3, timeout=180, retries=2)
        # LLM 可能漏输出字段，规范化（防 pipeline KeyError）
        if isinstance(r, dict):
            r.setdefault('score', 7)
            r.setdefault('dimensions', {})
            r.setdefault('feedback', '')
            r.setdefault('pass', float(r.get('score', 7)) >= 7)
        return r

    def assess_image_relevance(self, image_path: str, query: str,
                               model: str = None, threshold: float = 7.0) -> dict:
        """多模态判断图片与 query(概念/热点) 的相关性，返回 {score(1-10), pass, reason}。

        用于"爬图+相关性校验"：过滤必应/搜索返回的不相关图（防止图与旁白错位），
        只保留相关图，不够再由 FLUX 补足。
        """
        model = model or self.models['review']
        system = (
            '你是图片选材专家。判断给定图片与文字主题的相关性，输出1-10分的匹配度。\n'
            f'≥{threshold}分才算相关（能直接用来配这条主题画面）。\n'
            '仅输出JSON：{"score": 8, "pass": true, "reason": "一句话理由"}'
        )
        content = [{'type': 'text', 'text': f'主题：{query}\n判断该图与主题的相关性并打分。'}]
        content.append({'type': 'image_url',
                        'image_url': {'url': self._image_to_base64(image_path)}})
        messages = [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': content},
        ]
        try:
            r = self.chat_json(messages, model=model, temperature=0.3, timeout=120, retries=1)
        except Exception as e:
            # 视觉评审失败时保守放行（不影响主流程）
            return {'score': threshold, 'pass': True, 'reason': f'评审失败放行: {e}'}
        score = float(r.get('score', threshold)) if isinstance(r, dict) else threshold
        return {
            'score': score,
            'pass': score >= threshold,
            'reason': (r.get('reason', '') if isinstance(r, dict) else ''),
        }

    def review_character(self, character_ref: str, preview_paths: list) -> dict:
        """角色锚质量审查：参考图+多角度预览→{score, pass, feedback}
        """
        system = (
            '你是3D角色质量审查专家。根据角色参考图和多角度3D渲染预览，评估3D重建质量。\n'
            '按4个维度打分（每维1-10）：\n'
            '1. completeness: 角色完整性（无残缺、无悬浮碎片）\n'
            '2. multi_angle: 多角度稳定性（不同角度角色不崩坏）\n'
            '3. fidelity: 与参考图的一致性（外观/颜色/形态匹配）\n'
            '4. pose: 姿态自然度（角色应自然站立在地面上，而非躺倒、侧卧或悬浮在空中）\n'
            '综合分=四维均值。≥6分通过。\n'
            '输出严格JSON格式：\n'
            '{"score": 7, "dimensions": {"completeness": 7, "multi_angle": 7, '
            '"fidelity": 7, "pose": 7}, "feedback": "具体反馈", "pass": true}'
        )
        content = [{'type': 'text', 'text': '第一张是角色参考图，其余是多角度3D渲染预览，请评估3D重建质量。'}]
        b64 = self._image_to_base64(character_ref)
        content.append({'type': 'image_url', 'image_url': {'url': b64}})
        for path in preview_paths[:2]:
            b64 = self._image_to_base64(path)
            content.append({'type': 'image_url', 'image_url': {'url': b64}})

        messages = [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': content},
        ]
        r = self.chat_json(messages, model=self.models['review'], temperature=0.3, timeout=180, retries=2)
        if isinstance(r, dict):
            r.setdefault('score', 6)
            r.setdefault('dimensions', {})
            r.setdefault('feedback', '')
            r.setdefault('pass', float(r.get('score', 6)) >= 6)
        return r

    def scout_topics(self, hot_topics: list, account_type: str = '',
                     n_candidates: int = 5) -> list:
        """热点→视频概念候选排序（scout 选题）

        Args:
            hot_topics: 爬虫抓取的热点列表 [{title, source, heat, snippet}]
            account_type: 账号定位（如"影视解说"/"萌宠"/"情感"/"科技科普"）
            n_candidates: 生成候选数

        Returns:
            [{concept, angle, reason, predicted_score, source_topic}] 按 predicted_score 降序
        """
        topics_text = '\n'.join(
            f'{i+1}. [{t["source"]}] {t["title"]}'
            f'{" (热度:" + str(t["heat"]) + ")" if isinstance(t.get("heat"), (int, float)) and t["heat"] > 0 else ""}'
            f'{" — " + t["snippet"][:60] if t.get("snippet") else ""}'
            for i, t in enumerate(hot_topics[:30])
        )

        account_desc = f'账号定位：{account_type}' if account_type else '账号定位：通用短视频'
        system = (
            '你是短视频选题专家。根据当前热点话题，为指定账号生成视频概念候选。\n'
            f'{account_desc}\n'
            '要求：\n'
            '- 每个概念必须是一个可以直接用于视频生成的简短中文描述（一句话，如"一只猫在月球上跳舞"）\n'
            '- 概念要结合热点，但不能只是复述热点，要有创意角度（如拟人化、反转、科普、情感共鸣）\n'
            '- 概念要适合 AI 视频生成（有画面感、角色明确、场景清晰）\n'
            '- predicted_score 1-10 分，评估该概念的传播潜力（热点关联度+创意度+画面感）\n'
            '- angle 是创意角度的一句话说明\n'
            '- reason 是选题理由\n'
            '- source_topic 是关联的热点标题\n'
            f'- 生成 {n_candidates} 个候选，按 predicted_score 从高到低排列\n'
            '- 输出 JSON 数组：\n'
            '[{"concept":"...","angle":"...","reason":"...","predicted_score":8,"source_topic":"..."}]'
        )
        messages = [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': f'当前热点：\n{topics_text}'},
        ]
        result = self.chat_json(messages, model=self.models['script'],
                                temperature=0.7, timeout=60, retries=1)
        if isinstance(result, list):
            return sorted(result, key=lambda x: x.get('predicted_score', 0), reverse=True)
        return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='LLM client test')
    parser.add_argument('--concept', default='一只猫在月球上跳舞', help='Concept for script')
    args = parser.parse_args()

    client = LLMClient()
    print(f'=== 编剧: {args.concept} ===')
    script = client.script_write(args.concept)
    print(json.dumps(script, ensure_ascii=False, indent=2))
    print(f'\n=== Prompt优化: {script["shots"][0]["scene_desc"]} ===')
    vp = client.optimize_prompt(script['shots'][0]['scene_desc'], script['style'])
    print(vp)
