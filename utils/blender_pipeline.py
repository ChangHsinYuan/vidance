# -*- coding: utf-8 -*-
"""薄壳门面（v11 多智能体迁移后保持旧 import 兼容）：转发到 agents.generator.tools.blender_pipeline"""
from agents.generator.tools.blender_pipeline import *  # noqa: F401,F403
from agents.generator.tools.blender_pipeline import (  # noqa: F401
    bpy_build, render_frames, frames_to_mp4, scene_to_mp4, BlenderLine)
