# -*- coding: utf-8 -*-
"""多主题静态数据源。

只放纯数据，不 import 任何项目模块，避免循环依赖。
主题键（theme_id）用于 settings.json 持久化，尽量保持稳定。
"""

DEFAULT_THEME_ID = "sakura_campus"
DEFAULT_COLOR_MODE = "light"          # light / dark / system
DARK_OVERLAY = (10, 16, 32)           # #0A1020 深蓝黑遮罩
DANGER_COLOR = "#E54D4D"

# 9 套主题：每套提供浅色/深色关键色 + 统一主渐变。
# 其余 QSS 语义色由 ThemeManager 从这几个关键色派生，不在 UI 代码里硬编码。
THEME_DEFS = {
    "sakura_campus": {
        "name": "樱花校园",
        "gradient": ("#F2A6C0", "#D96A9C"),
        "light": {"bg": "#F6F2F5", "card": "#FFFFFF", "text": "#3A333F", "accent": "#E88CA6"},
        "dark": {"bg": "#1A1520", "card": "#262030", "text": "#E0E0E5", "accent": "#F2A6C0"},
    },
    "dusk_study": {
        "name": "暮灯书房",
        "gradient": ("#E0A26B", "#B97A45"),
        "light": {"bg": "#F5EFE7", "card": "#FFFDF9", "text": "#3D342B", "accent": "#C98A5B"},
        "dark": {"bg": "#1C1916", "card": "#282320", "text": "#EAE3D8", "accent": "#E0A26B"},
    },
    "galaxy": {
        "name": "银河星空",
        "gradient": ("#9D8FF7", "#5C50C9"),
        "light": {"bg": "#EDF1F8", "card": "#FFFFFF", "text": "#2B3140", "accent": "#7B6FE0"},
        "dark": {"bg": "#121420", "card": "#1C2030", "text": "#E4E8F5", "accent": "#8F82F2"},
    },
    "summer_sea": {
        "name": "碧海夏日",
        "gradient": ("#6FC3F0", "#2E7FB4"),
        "light": {"bg": "#ECF4F8", "card": "#FFFFFF", "text": "#2B3A42", "accent": "#4FA8D6"},
        "dark": {"bg": "#0F1A24", "card": "#172530", "text": "#DDEAF2", "accent": "#5FB8E8"},
    },
    "library": {
        "name": "文墨图书馆",
        "gradient": ("#E3C078", "#8F6626"),
        "light": {"bg": "#F4F0E8", "card": "#FFFFF6", "text": "#3A342A", "accent": "#B98A3E"},
        "dark": {"bg": "#1A1815", "card": "#242119", "text": "#EAE4D8", "accent": "#D9AE5E"},
    },
    "cloud_dawn": {
        "name": "云海晨昏",
        "gradient": ("#9ADACF", "#3E8A7D"),
        "light": {"bg": "#EEF3F2", "card": "#FFFFFF", "text": "#2F3A38", "accent": "#6FB8AC"},
        "dark": {"bg": "#12191B", "card": "#1B2426", "text": "#E2ECEA", "accent": "#8FD0C4"},
    },
    "neon_rain": {
        "name": "雨夜霓虹",
        "gradient": ("#8CA6F0", "#3E5AB0"),
        "light": {"bg": "#EEF0F4", "card": "#FFFFFF", "text": "#30343C", "accent": "#5E7BD8"},
        "dark": {"bg": "#0F1219", "card": "#181C26", "text": "#DEE4EF", "accent": "#7A95E8"},
    },
    "snow_winter": {
        "name": "雪境冬语",
        "gradient": ("#A0D0EA", "#3E7BA6"),
        "light": {"bg": "#F1F4F7", "card": "#FFFFFF", "text": "#333A42", "accent": "#6FA8C9"},
        "dark": {"bg": "#13181E", "card": "#1C232B", "text": "#E4EBF1", "accent": "#8FC2E0"},
    },
    "japanese_garden": {
        "name": "和风庭院",
        "gradient": ("#E08A7A", "#8F3A30"),
        "light": {"bg": "#F4F1EA", "card": "#FFFDF8", "text": "#3A352C", "accent": "#C25A4A"},
        "dark": {"bg": "#1A1612", "card": "#241E18", "text": "#EDE6DB", "accent": "#D97A6C"},
    },
}

THEME_ORDER = [
    "sakura_campus",
    "dusk_study",
    "galaxy",
    "summer_sea",
    "library",
    "cloud_dawn",
    "neon_rain",
    "snow_winter",
    "japanese_garden",
]


def theme_name(theme_id: str) -> str:
    return (THEME_DEFS.get(str(theme_id or "")) or THEME_DEFS[DEFAULT_THEME_ID])["name"]


def theme_accent(theme_id: str, mode: str) -> str:
    """返回某主题在浅/深色下的强调色。"""
    item = THEME_DEFS.get(str(theme_id or "")) or THEME_DEFS[DEFAULT_THEME_ID]
    mode = "dark" if str(mode) == "dark" else "light"
    return item[mode]["accent"]


def theme_gradient(theme_id: str):
    item = THEME_DEFS.get(str(theme_id or "")) or THEME_DEFS[DEFAULT_THEME_ID]
    return item["gradient"]
