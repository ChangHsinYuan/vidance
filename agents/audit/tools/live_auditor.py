#!/usr/bin/env python3
"""v20 生成中审核：latent 预览帧粗审（节流 + 早判）

与生成并行的止损闸：构图/主体/崩坏早判（latent 预览天然模糊，细节伪影
交给渲后 light/full 终审）。判定 fail → 上层 interrupt 换 seed 重生成。
"""
import base64
import io
import json

import numpy as np

# 预览帧无结构（全白/纯噪早期）时跳过不发 API（M0 实测 p001/p002 mean 238 全白）
MIN_FRAME_STD = 40.0
FAIL_SCORE = 4  # 综合分低于此值判死

SYSTEM = (
    '你是视频生成流水线的实时质检员。当前是扩散模型去噪中途的模糊预览帧，'
    '天然发糊发虚，这是正常的——不要因为模糊扣分。只需判断两件事：\n'
    '1. 画面主体与场景描述是否吻合（主体类型/大致动作/场景环境）\n'
    '2. 是否已出现不可挽回的崩坏（纯噪声块/花屏/诡异肢体融合/与描述完全无关的画面）\n'
    '若吻合且未崩坏即 pass（模糊不扣分）。输出严格 JSON：\n'
    '{"score": 8, "reason": "一句话依据", "fail": false}\n'
    'score 0-10 表示"这帧继续生成下去值得吗"，fail=true 表示应立即止损重来。'
)


def _png_data_url(png: bytes) -> str:
    """预览帧本身已是 ~512px PNG，无需缩放，直接转 data URL"""
    return 'data:image/png;base64,' + base64.b64encode(png).decode('ascii')


def frame_structured(png: bytes, min_std: float = MIN_FRAME_STD) -> bool:
    """帧是否有可判结构（全白/全黑早期帧 std 极低，直接跳过省 API）"""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(png)).convert('RGB')
        arr = np.asarray(img, dtype=np.float32)
        return float(arr.std()) >= min_std
    except Exception:
        return False


class LiveAuditor:
    """粗审节流器：每镜最多 max_reviews 次 API 调用，首审等 step>=min_step"""

    def __init__(self, max_reviews: int = 3, min_step: int = 4,
                 timeout: float = 60, model: str = None,
                 llm_client=None):
        self.max_reviews = max_reviews
        self.min_step = min_step
        self.timeout = timeout
        if model is None:  # 粗审是多模态调用，必须走 review 模型（script 默认无多模态）
            from agents.common.tools.llm import LLMClient
            model = LLMClient().models['review']
        self.model = model
        self._llm = llm_client
        self.reviews_used = 0
        self.history = []  # [{'step', 'verdict', 'score', 'reason', 'api'}]

    def review(self, frame: dict, scene_desc: str) -> dict:
        """frame = PreviewListener.latest_frame()；返回
        {'verdict': 'pass'|'fail'|'skip', 'score', 'reason', 'api': bool}"""
        if frame is None:
            return {'verdict': 'skip', 'score': None,
                    'reason': '尚无预览帧', 'api': False}
        step = frame.get('step', 0)
        if step < self.min_step:
            return {'verdict': 'skip', 'score': None,
                    'reason': f'step {step} 过早（<{self.min_step}）', 'api': False}
        if not frame_structured(frame['png']):
            return {'verdict': 'skip', 'score': None,
                    'reason': '帧无结构（早期全白/噪声）', 'api': False}
        if self.reviews_used >= self.max_reviews:
            return {'verdict': 'skip', 'score': None,
                    'reason': '粗审次数用尽（节流）', 'api': False}

        r = self._call_api(frame['png'], scene_desc)
        self.reviews_used += 1
        verdict = 'fail' if (r.get('fail') or
                             float(r.get('score', 10)) < FAIL_SCORE) else 'pass'
        out = {'verdict': verdict, 'score': r.get('score'),
               'reason': r.get('reason', ''), 'api': True}
        self.history.append({'step': step, **out})
        return out

    def _call_api(self, png: bytes, scene_desc: str) -> dict:
        if self._llm is None:
            from agents.common.tools.llm import LLMClient
            self._llm = LLMClient()
        content = [
            {'type': 'text', 'text': f'场景描述：{scene_desc}'},
            {'type': 'image_url', 'image_url': {'url': _png_data_url(png)}},
        ]
        messages = [{'role': 'system', 'content': SYSTEM},
                    {'role': 'user', 'content': content}]
        try:
            r = self._llm.chat_json(messages, model=self.model,
                                    temperature=0.2, timeout=self.timeout,
                                    retries=1)
        except Exception as e:
            return {'score': 10, 'reason': f'粗审 API 异常（放行不阻塞）: {e}',
                    'fail': False}
        if not isinstance(r, dict):
            return {'score': 10, 'reason': '粗审返回非 JSON（放行）', 'fail': False}
        r.setdefault('score', 10)
        r.setdefault('fail', False)
        r.setdefault('reason', '')
        return r

    def summary(self) -> dict:
        """落 meta 用：次数/fail 数/逐次记录"""
        fails = sum(1 for h in self.history if h['verdict'] == 'fail')
        return {'reviews': self.reviews_used, 'fails': fails,
                'history': self.history}


def load_cfg(config: dict) -> dict:
    """config['v20_live_audit'] 安全读取（缺省 = 关闭 + 合理默认）"""
    c = (config or {}).get('v20_live_audit') or {}
    return {
        'enabled': bool(c.get('enabled', False)),
        'max_reviews': int(c.get('max_reviews', 3)),
        'min_step': int(c.get('min_step', 4)),
        'timeout': float(c.get('timeout', 60)),
    }
