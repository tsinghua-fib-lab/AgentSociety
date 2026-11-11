"""Agent skill content package.

中文：``agent/skills/`` 现在只承载 skill 内容目录（如 ``daily-guidance/`` ）。
skill 基础设施（registry / runtime / workspace_fs / hook_context）已下沉到
:mod:`agentsociety2.agent.base` 。
English: ``agent/skills/`` now only carries skill content directories
(e.g. ``daily-guidance/``). The skill infrastructure (registry / runtime /
workspace_fs / hook_context) has moved down into
:mod:`agentsociety2.agent.base`.

The skill runtime scans this directory by path (not by import), so keeping
this package importable is sufficient for built-in skill discovery.
"""
