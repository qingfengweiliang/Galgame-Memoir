# -*- coding: utf-8 -*-
"""
============================================================
 Galgame Memoir  (完全离线单机运行)
============================================================

【需要安装的第三方库】
    pip install PySide6 requests pillow

【运行方式】
    python src/main.py    （或双击根目录的 Galgame Manager.exe；依赖/环境异常时用 repair\repair.bat）

【代码结构】（源码统一放在 src/ 目录）
    - src/main.py      入口：QApplication + 全局异常捕获 + 启动主窗口
    - src/config.py    路径常量 / 设置读写 / 通用工具 / 图片工具
    - src/database.py  SQLite 数据库封装
    - src/net.py       网络请求与各数据源 API（Bangumi/VNDB/Steam/SteamGridDB/识图）
    - src/workers.py   所有后台线程（QThread）
    - src/theme.py     主题样式与基础控件（TopComboBox/折叠分组/主题开关等）
    - src/dialogs.py   所有对话框（添加/编辑/详情/批量导入/封面/识图/设置）
    - src/widgets.py   主窗口 MainWindow 与网格 / 悬浮 CG 预览

【数据目录】
    - data/           数据库、设置、封面、截图等数据仍保存在项目根目录
============================================================
"""

import os
import sys
import traceback

# 兼容两种启动方式：
#   1) python src/main.py
#   2) python -m src.main
# 都先把 src/ 加入 sys.path，保证扁平导入（import config 等）可以找到模块。
if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QMessageBox

from config import ensure_directories, DB_PATH, APP_NAME
from database import Database
from theme import _apply_theme, _apply_bg, app_icon
from theme_manager import theme_manager
from widgets import MainWindow


# ============================================================
# 入口
# ============================================================
def _global_excepthook(exc_type, exc_value, exc_tb):
    """捕获所有未处理异常，弹窗提示，避免程序无声闪退。"""
    msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        app = QApplication.instance()
        if app is not None:
            QMessageBox.critical(
                None, "程序出错",
                "程序发生了未处理的异常：\n\n%s" % msg)
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def main():
    sys.excepthook = _global_excepthook
    ensure_directories()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())
    # Windows 任务栏图标：让窗口图标与任务栏图标一致
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("GalgameMemoir")
        except Exception:
            pass
    try:
        app.setStyle("Fusion")
    except Exception:
        pass
    theme_manager.start_system_listener()
    _apply_theme()

    db = None
    try:
        db = Database(DB_PATH)
    except Exception as exc:
        QMessageBox.critical(None, "数据库错误",
                             "无法创建/打开数据库：\n%s" % exc)
        return

    win = MainWindow(db)
    win.setWindowIcon(app_icon())
    win.show()
    _apply_bg()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
