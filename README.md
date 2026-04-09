# ARAM Mayhem Helper

## 介绍

一个海克斯乱斗小帮手。
针对《英雄联盟》海克斯乱斗模式的辅助工具，为玩家提供符文选择建议。

**核心功能**:

- 通过OCR识别游戏中的符文选项
- 根据当前英雄和符文数据，智能推荐最优符文选择
- 支持命令行（CLI）和图形界面（GUI）两种交互方式

## 工作流程

1. **数据爬取**: 从OP.GG和Data Dragon API爬取英雄和符文数据
2. **英雄识别**: 通过League Client API获取当前游戏中的英雄
3. **符文识别**: 使用OCR识别屏幕上的符文选项
4. **智能推荐**: 基于算法模型，综合考虑表现和流行度，给出符文选择建议

## 安装说明

### 1. 安装 uv

uv 是一个快速的 Python 包管理器，推荐使用：

**Windows (PowerShell)**:

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**Linux/macOS**:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

或者使用 pip 安装：

```bash
pip install uv
```

### 2. 克隆项目

```bash
git clone https://github.com/DracoYus/aram_mayhem_helper.git
cd aram-mayhem-helper
```

### 3. 安装依赖

使用 uv 安装项目依赖：

```bash
uv sync
```

注册模块：

```bash
uv pip install -e .
```

### 4. 配置说明

配置文件位于 `config/config.toml`，可根据需要调整：

```toml
[crawler]
timeout = 30              # 请求超时时间（秒）
delay_second = 2           # 爬取延迟（秒）

[suggest]
immediate_select_weighted_sum_threshold = 0.6      # 快选阈值
immediate_select_precentage_threshold = 0.15         # 快选百分比阈值
consider_select_weighted_sum_threshold = 0.45       # 考虑阈值
consider_select_precentage_threshold = 0.3          # 考虑百分比阈值
```

## 使用说明

### 命令行模式 (CLI)

```bash
# 运行主程序（识别英雄并推荐符文）
uv run python -m aram_mayhem_helper.cli main

# 爬取英雄数据
uv run python -m aram_mayhem_helper.cli champion-crawler

# 爬取符文数据
uv run python -m aram_mayhem_helper.cli aram-augment-crawler
```

### 图形界面模式 (GUI)

```bash
uv run python -m aram_mayhem_helper.gui
```

GUI界面提供以下功能：

- **识别英雄**: 点击按钮识别当前游戏中的英雄
- **识别符文**: 点击按钮识别屏幕上的符文选项并显示推荐结果
- **实时日志**: 界面下方显示运行日志

## 技术栈

- **Python**: 3.12
- **OCR识别**: PaddleOCR 2.9.1
- **深度学习框架**: PaddlePaddle 2.6.2
- **HTTP请求**: requests
- **GUI框架**: tkinter
- **数据处理**: numpy
- **配置管理**: TOML
- **包管理**: uv
- **代码规范**: ruff

## 常见问题

### Q: OCR识别不准确怎么办？

A: 可以调整以下参数：

- 确保游戏窗口在前台且不被遮挡
- 检查屏幕分辨率是否与配置匹配
- 调整OCR识别区域的坐标（在 `ocr_tool.py` 中）

### Q: 爬取数据失败？

A: 可能的原因：

1. 网络连接问题（程序会自动重试3次）
2. API接口变更
3. 被反爬虫限制（可以增加 `delay_second` 配置）

## 许可证

本项目仅供学习和个人使用，请勿用于商业用途。

## 贡献

欢迎提交 Issue 和 Pull Request！

## 联系方式

- 作者: DracoYu
- 邮箱: <876319691@qq.com>
