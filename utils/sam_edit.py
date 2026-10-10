# -*- coding: utf-8 -*-
"""薄壳门面（v11 多智能体迁移后保持旧 import 兼容）：转发到 agents.post.tools.sam_edit"""
from agents.post.tools.sam_edit import *  # noqa: F401,F403
from agents.post.tools.sam_edit import (  # noqa: F401
    segment_image, cutout, replace_bg, mosaic, inpaint, video_edit, load_predictor,
    detect_objects, segment_from_boxes, parse_points, parse_boxes, inpaint_flux,
    qwen_edit)
