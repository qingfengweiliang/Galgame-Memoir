<img width="2044" height="1277" alt="29adc5fe-ef0c-4b81-bd07-0cafe9b5c6eb" src="https://github.com/user-attachments/assets/28847f2f-bd4b-4cdc-8638-14f90a00db50" /><img width="2044" height="1277" alt="image" src="https://github.com/user-attachments/assets/27b587eb-f9bd-4c2c-b582-33baeb2631c7" /># Galgame Memoir — V1.0

<img width="2044" height="1277" alt="9ced521a-9cef-48a8-88e7-10e6f968d56b" src="https://github.com/user-attachments/assets/3f718714-a41b-4447-9731-30423e6150be" />


一个基于 **Python / PySide6（Qt6）** 的本地 Galgame 信息管理与收藏记录工具。
完全离线单机运行：游戏信息管理、收藏与状态记录、数据库、CG 管理、随机 CG、悬浮 CG、
多主题（**9 套主题 × 浅色/深色，共 18 张背景**）、欢迎页与启动动画、图片识别（AI 识图）、
Bangumi / VNDB / Steam / SteamGridDB / AnimeTrace / SauceNAO 自动识别与信息填充。

- **当前版本：V1.0**
- 详细说明见 [`help/README.md`](help/README.md)（该文档为历史版本，部分内容可能已过时，以本 README 为准）

## 目录结构

```text
Galgame Manager/
├── Galgame Manager.exe                     # ★ 双击启动（C# 启动器，文件元数据 1.0.0.0）
├── src/                                    # 全部源代码（15 个 .py）
│   ├── main.py  config.py  database.py  net.py  workers.py
│   ├── theme.py  theme_defs.py  theme_manager.py
│   ├── dialogs.py  widgets.py  welcome.py
│   └── cg_library.py  random_cg_api.py  random_cg_viewer.py  __init__.py
├── assets/                                 # 应用图标 + 9 套主题背景（浅/深色，共 18 张）
│   ├── app_icon.png  app_icon.ico
│   └── themes/{主题名}_{浅色|深色}.jpg
├── Galgame Manager环境检测工具/            # 环境检测工具 v1.2
│   ├── Galgame Manager环境检测工具.exe     # 无黑框启动器
│   ├── 环境检测工具.ps1                    # 图形界面主程序（v1.2）
│   ├── setup_env.ps1                       # 一键测速 / 装依赖 / 启动前校验（内部版本 1.0）
│   └── 启动器源码/Launcher.cs  build_exe.bat
├── launcher/                               # 主启动器源码（Launcher.cs + AssemblyInfo.cs + build_exe.bat）
├── repair/repair.bat                       # 环境修复 + 备用启动
├── help/README.md                          # 详细说明文档（历史版本，可能已过时）
├── data/                                   # 本地数据（不上传，仅保留 .gitkeep）
├── backup/                                 # 回滚点已清理归档（仅保留 README.md）
├── python安装包/                            # 本地离线 Python 安装包（不上传）
└── requirements.txt
```

## 版本

| 对象 | 版本 | 说明 |
| --- | --- | --- |
| Galgame Memoir | **V1.0** | 当前对外版本 |
| 环境检测工具（环境检测工具.ps1） | **v1.2** | 图形界面工具 |
| setup_env.ps1 | 1.0 | 工具内部脚本版本 |
| Galgame Manager.exe | 1.0.0.0 | exe 文件元数据 |
| Galgame Manager环境检测工具.exe | 0.0.0.0 | exe 文件元数据 |
| Python | ≥ 3.9 | 本地捆绑 3.14.7（`python安装包/`，不上传） |

> `Galgame Manager环境检测工具.exe` 的文件元数据为 0.0.0.0（该启动器源码未声明版本信息）；
> **不影响使用，仅文件元数据差异**。

## 运行方式

1. **双击 `Galgame Manager.exe`**（推荐；需 .NET Framework 4.x，Win10/11 自带）
2. **双击 `repair\repair.bat`**：首次安装依赖 / 修复环境 / exe 不能跑时
3. **命令行**：`python src\main.py`

首次运行会自动创建 `data\` 目录与数据库表结构；`data\settings.json` 缺失时按默认值运行。

## 依赖

```text
PySide6-Essentials
requests
pillow
```

安装：`pip install -r requirements.txt`

## 环境检测工具（v1.2）

图形界面的"一键环境检测 / 安装"工具，双击 `Galgame Manager环境检测工具.exe` 使用。

- **一键安装**：自动测速选最快镜像源 → 补齐缺失依赖 → 启动前校验
- **仅检测**：只看不改
- **测速**：只测主站 + 备用镜像速度
- **启动程序**：优先 `Galgame Manager.exe`，否则用 `pythonw` 起 `src\main.py`
- 检测项：Python ≥ 3.9、PySide6 / requests / pillow（可选 darkdetect）、.NET Framework 4.x、
  VC++ 运行库、中文字体、网络连通性、CG 根目录、API Key 是否已填写
- **不会**：安装/升级/卸载 Python、改 PATH、改源码、覆盖 `data\settings.json` 或 `data\galgame.db`

> 工具会自动向上查找项目根（同时含 `src\main.py` 与 `data\`），因此放在子目录里也能正常使用。

## 数据目录（本地，不上传）

- `data/galgame.db`：SQLite 数据库（首次运行自动建表）
- `data/settings.json`：程序设置（**含 API Key / Token，绝不提交**）
- `data/covers/`：封面图片
- `data/screenshots/`：游戏截图
- `data/profile photo/`：头像预设
- `data/wallpapers/`：背景图预设
- `data/user/`：自己选的图（自动收进这里）

## GitHub 备份说明

本仓库只保存 **完整功能代码 + 必要配置/文档 + 必要的小型固定资源**，不包含：

- 个人数据（`data/`：数据库、设置、封面、截图、预设图）
- 本地回滚点（旧备份已归档到本地 `归档\backup\`，仓库只保留 `backup/README.md`）
- 离线安装包（`python安装包/`）
- Python 缓存（`__pycache__/`、`*.pyc`）
- API Key / Token / 密码 / Cookie / 私钥等敏感信息
- 给 AI 的提示词 / 操作记录文档（见 `.gitignore` 末条）
