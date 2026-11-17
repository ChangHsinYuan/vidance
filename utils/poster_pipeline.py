# -*- coding: utf-8 -*-
"""薄壳门面（v11 多智能体迁移后保持旧 import 兼容）：转发到 agents.generator.tools.poster_pipeline"""
from agents.generator.tools.poster_pipeline import *  # noqa: F401,F403
from agents.generator.tools.poster_pipeline import (  # noqa: F401
    compose_poster, generate_plates, cutout_creatures, gradient_bg, PosterLine)
