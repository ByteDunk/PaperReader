# 论文阅读器

基于 Vue 3、FastAPI 和 Tauri 2 的本地论文阅读工具，提供 PDF 阅读、内容重排、翻译、语义搜索和 AI 助手。

## 功能

- 导入和管理 PDF 论文，查看原文、解析后的重排内容与译文。
- 使用书签、多面板布局和阅读设置组织阅读过程。
- 使用本地解析与嵌入模型进行文档处理和语义检索。
- 连接支持 Responses 流式接口的模型服务，进行翻译和论文问答。
- 提供 Windows 桌面应用打包脚本和内置使用教程。

## 开发环境

以下命令在项目根目录的 PowerShell 中执行。

- Python：建议使用 3.12。
- Node.js：`^20.19.0 || >=22.12.0`，版本要求见 `frontend/package.json`。
- 桌面开发和打包另需 Rust MSVC 工具链、Visual Studio C++ 构建工具、Windows SDK 和 WebView2 Runtime。

## 安装与配置

```powershell
py -3.12 -m venv backend/.venv
./backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
npm.cmd --prefix frontend ci
Copy-Item .env.example .env
```

已有 `.env` 时保留现有文件。可在应用的“设置 → API 设置”中填写 API 地址、模型名称和 API Key，或编辑 `.env`。配置模板见 `.env.example`。翻译和 AI 问答会调用所配置的外部模型服务。

解析和语义搜索还需要本地模型；模型权重不存放在 Git 仓库中。首次使用桌面应用时按启动界面提示下载。浏览器开发模式可先运行：

```powershell
./backend/.venv/Scripts/python.exe -m backend.model_download
```

按提示输入 `download` 开始下载。模型目录、文件大小与固定版本记录在 `backend/model_catalog.py`。

## 运行

浏览器开发模式：

```powershell
./start.ps1
```

脚本会分别启动后端和前端窗口，访问 `http://127.0.0.1:5173`。默认后端端口为 `8000`。在对应窗口按 `Ctrl+C` 停止服务。

也可在两个终端中分别执行：

```powershell
# 终端一：项目根目录
./backend/.venv/Scripts/python.exe -m uvicorn backend.main:create_app --factory --reload --reload-dir backend --host 127.0.0.1 --port 8000
```

```powershell
# 终端二
cd frontend
npm.cmd run dev
```

桌面开发模式（在项目根目录执行）：

```powershell
npm.cmd --prefix frontend run desktop:dev
```

## 检查与 Windows 打包

```powershell
npm.cmd --prefix frontend run build
./backend/.venv/Scripts/python.exe -m pip install pytest
./backend/.venv/Scripts/python.exe -m pytest packaging/tests -q
```

安装打包依赖后生成 Windows 便携包：

```powershell
./backend/.venv/Scripts/python.exe -m pip install -r packaging/requirements-build.txt
./build.ps1
```

构建中间产物位于 `.build/`，最终输出位于 `release/`，均不提交到 Git。

## 项目结构

```text
backend/            FastAPI 接口、论文管理、解析、翻译、RAG 和 AI 助手
frontend/           Vue 界面及 Tauri 桌面外壳
packaging/          Windows 打包脚本、测试与模型声明
.env.example        配置模板（不含凭据）
start.ps1           浏览器开发模式启动脚本
build.ps1           Windows 打包入口
```

## 本地数据与第三方资源

`.env`、PDF、模型、资料库、临时目录和构建产物已通过 `.gitignore` 排除。浏览器模式默认将资料库保存在 `backend/data/library/`。

第三方模型声明见 `packaging/model-notices/`。模型和依赖的许可由各自权利人规定。
