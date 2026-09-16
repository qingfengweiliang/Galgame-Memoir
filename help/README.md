# Galgame Memoir

一个基于 PySide6 的本地 Galgame 信息管理工具，支持本地数据库管理、封面下载、批量导入、识图匹配等功能。

## 目录结构

```text
galgame整理/
├── Galgame Manager.exe      # ★ 双击这个启动（带图标、不弹黑框）
├── src/                     # 所有源代码
│   ├── main.py              # 程序入口：QApplication + 全局异常捕获 + 主窗口
│   ├── config.py            # 路径常量 / 设置读写 / 通用工具 / 图片工具
│   ├── database.py          # SQLite 数据库封装
│   ├── net.py               # 网络请求与各数据源 API
│   ├── workers.py           # 所有后台线程（QThread）
│   ├── theme_defs.py        # 9 套主题的静态色板数据源（纯数据）
│   ├── theme_manager.py     # 主题 / 深浅模式 / 自定义背景管理 + 背景图预处理缓存
│   ├── theme.py             # 主题样式与基础控件
│   ├── dialogs.py           # 所有对话框
│   ├── random_cg_api.py     # 随机 CG 图片接口层（无 UI：illlights → dmoe.cc → 本地 CG）
│   ├── random_cg_viewer.py  # 随机 CG 预览窗
│   ├── widgets.py           # 主窗口 MainWindow 与网格/悬浮预览
│   └── welcome.py           # 启动页：欢迎界面 + 渐入/离场动画 + 统计数字滚动
├── repair/                  # 环境修复 + 备用启动
│   └── repair.bat           # 检查 Python 3.9+ 与依赖，缺了就装，然后启动
├── launcher/                # exe 启动器源码（Launcher.cs + build_exe.bat，可自行重编译）
├── assets/                  # 应用图标（app_icon.png / app_icon.ico）
├── data/                    # 数据目录：数据库、设置、封面、截图、头像/背景预设
├── help/                    # 说明文档（本文件）
└── backup/                  # 回滚点 + 重构记录 + 备份说明
    ├── 重构记录与待办.md      # 每一轮改了什么
    ├── 备份说明.md            # 回滚点怎么用
    └── legacy/main_old.py    # 拆分前的单文件旧版（可删除）
```

## 文档位置

- 本说明：`help\README.md`
- 每轮改动记录：`backup\重构记录与待办.md`
- 回滚点用法：`backup\备份说明.md`

## 运行方式

### 方式一：双击 `Galgame Manager.exe`（推荐）

带图标、**不弹黑色控制台窗口**。它只做三件事：
1. 找一个可用的 Python（`pythonw.exe` → `pyw.exe` → `python.exe` → `py.exe`，并自动排除 Microsoft Store 的 0 字节假壳）；
2. 检查 `PySide6 / requests / pillow` 是否齐全；
3. 用 `pythonw.exe` 启动 `src\main.py`。

依赖缺失时会自动转到 `repair\repair.bat`，走**可见的**安装流程（能看到 pip 进度）。

### 方式二：双击 `repair\repair.bat`（首次装依赖 / 修复环境 / exe 不能跑时）

会自动检查 Python 3.9+ 与依赖，缺失时用清华镜像自动安装，然后启动程序。
（exe 发现依赖不全时也会自动调用它，所以这个文件别删。）

### 方式三：命令行运行

```bash
# 直接以脚本方式运行
python src/main.py

# 或以包模块方式运行（同样支持）
python -m src.main
```

## 依赖

```bash
pip install PySide6 requests pillow
```

## 模块说明

| 模块 | 职责 |
| --- | --- |
| `main.py` | 入口，创建 QApplication，初始化主题和数据库，启动主窗口 |
| `config.py` | 全局路径、设置读写、通用工具、图片缩略图工具 |
| `database.py` | SQLite 数据库封装，游戏/截图/评分等表结构与管理 |
| `net.py` | Bangumi、VNDB、Steam、SteamGridDB、AnimeTrace、SauceNAO 等网络请求 |
| `workers.py` | 所有后台 QThread 线程，避免网络/图片操作阻塞界面 |
| `theme_defs.py` | 9 套主题的静态色板数据源（每套 light/dark 的 bg/card/text/accent + 统一主渐变），纯数据、不依赖任何模块 |
| `theme_manager.py` | 主题 / 颜色模式 / 自定义背景的解算与背景图预处理缓存（压暗 15% + 遮罩，跟随系统深浅色） |
| `theme.py` | 全局 QSS 主题、自定义控件（TopComboBox、折叠分组、主题开关等） |
| `dialogs.py` | 添加/编辑/详情/批量导入/封面选择/识图/设置等对话框 |
| `random_cg_api.py` | 随机 CG 图片接口层（无 UI）：主图库请求 + illlights→dmoe.cc→本地 CG 三级降级，Pillow 解码后交给 UI |
| `random_cg_viewer.py` | 随机 CG 预览窗（PySide6 原生，独立窗口） |
| `widgets.py` | 主窗口、游戏网格、侧边栏、悬浮 CG 预览 |
| `welcome.py` | 启动页：Banner、最近添加 3 张 3:4 卡片、统计卡片（数字滚动）、随机台词、渐入/离场动画 |

## 数据目录

- `data/galgame.db`：SQLite 数据库
- `data/settings.json`：程序设置
- `data/covers/`：封面图片
- `data/screenshots/`：游戏截图
- `data/profile photo/`：**头像预设**（丢进这里的图片会出现在「设置 → 头像与桌宠」下面的一排缩略图里，点一下直接换成侧边栏头像）
- `data/wallpapers/`：**背景图预设**（丢进这里的图片会出现在「设置 → 外观」下面的一排缩略图里，点一下就会换成主界面背景）
- `data/user/`：自己用「浏览…」选的图（会自动收进这里，并缩到 1024 以内）

### 预设图片怎么用

1. 把图片直接放进 `data/profile photo/`（头像）或 `data/wallpapers/`（背景图）；
2. 打开「设置」，在对应分区下面就会看到那排缩略图；
3. **点一下那张缩略图**即可使用 —— 当前正在用的那张会有一圈强调色边框。

补充：

- **放进去就会自动出现**：设置页开着的时候往文件夹里丢图片，那一排会自己刷新（不用重开设置页）；
  旁边的「刷新」按钮也可以手动重扫。
- 只认图片格式（`.jpg .jpeg .png .gif .bmp .webp`）；以 `_` 或 `.` 开头的文件会被忽略
  （想临时藏起某张图，把文件名前面加个 `_` 即可）。按文件名排序。
- 设置里存的是**相对路径**，所以整个项目文件夹搬走或改名后预设依然有效。

`src/config.py` 中的 `BASE_DIR` 指向项目根目录（即 `src` 的上一级），所以移动源码不会导致数据目录变化。

## 注意事项

- `backup/legacy/main_old.py` 是拆分前的旧版单文件备份（模块化版本已稳定，可删除）。
- `backup/` 里是各轮 UI 改动前的回滚点（源文件 + 完整 diff + 预览图），详见 `backup/备份说明.md`。
- 部分 API（Bangumi、VNDB、Steam、识图等）可能需要代理或 API Key。
- SauceNAO API Key 请在“设置 → API / 令牌”中统一配置；识图窗口不再单独显示 Key 输入框。
- 识图 AnimeTrace 的模型列表会做缓存，避免每次搜索都额外请求一次模型接口。
- 第一次运行会自动创建数据库表结构。
