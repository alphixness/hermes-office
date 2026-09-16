"""Hermes 办公室 —— agent 侧入口。

这是一个**纯 UI 插件**：桌面端面板在 ``desktop/plugin.js``，插件后端路由在
``dashboard/plugin_api.py``（挂在 /api/plugins/hermes-office/ 下）。它不注册任何工具、
钩子、provider，所以 ``register()`` 是空的 —— 这里存在的意义只是让插件包的
agent 侧契约成立（官方 doctor 会检查这个文件）。
"""
from __future__ import annotations


def register(ctx) -> None:  # noqa: ARG001 - 纯 UI 插件，不占用任何 agent 能力
    """No-op：不注册工具 / 钩子 / provider。"""
    return None
