# MinerU 4.1 对 PaperReader 的影响

调研日期为 2026-11-09。对照版本为 MinerU 4.0.0、PaperReader 已提交基线 4.0.12、引入自动加速的 4.1.0，以及当前工作树和后端虚拟环境使用的 4.1.7。本次使用上游发行记录、版本标签源码、已安装的 SDK 和仓库内已有批测，未重跑整批基准，另做了两次 Flash 局部页段冒烟测试。

**建议先交付 4.1.7 的 Basic + ONNX 自动选卡和 CPU 回退，BGE-M3 继续用 CPU。** 现有 Windows 批测中，这套组合把七篇论文的正文就绪时间从约 18 分钟降到约 9 分钟。质量改进优先验证脚注公式、阅读顺序和裁图，然后减少私有接口耦合。Standard 或 Advanced 可用于选定的难页，先测质量和资源开销再决定是否扩大使用范围。 [现有批测](../tmp/onnx-gpu/REPORT.md) · [FastEmbed 对照](../tmp/fastembed-gpu/REPORT.md)

## 版本差异

| 版本 | 与 PaperReader 有关的变化 |
| --- | --- |
| 4.0.0 | 已具备 Flash、Basic、Standard、Advanced 四档、本地 SDK、结构化结果及模型运行时分离。默认安装的小模型使用 ONNX CPU，VLM 可另走 llama.cpp/Vulkan。Python 支持 3.10–3.14。 [4.0.0 发布说明](https://github.com/opendatalab/MinerU/releases/tag/mineru-4.0.0-released) |
| 4.0.12 | 仍依赖普通 `onnxruntime`，发行说明已包含按类别版面阈值恢复。自部署 API 和 Router 已有 `/v1/tasks` 和 `/v1/file_parse` 便捷路由，共用旧的 parse-job ID 和流程。 [4.0.12 发布说明](https://github.com/opendatalab/MinerU/releases/tag/mineru-4.0.12-released) · [4.0.12 依赖声明](https://github.com/opendatalab/MinerU/blob/mineru-4.0.12-released/pyproject.toml) |
| 4.1.0 | Windows x64 新增 DirectML，Linux x86_64 新增 Vulkan 后端的 WebGPU；兼容 GPU 可自动加速 ONNX 小模型。新增硬件诊断和服务档位推荐。Python 最低版本升至 3.11。Tasks 和 file-parse 在沿用部分 URL 名称的同时更换了协议。 [4.1.0 发布说明](https://github.com/opendatalab/MinerU/releases/tag/mineru-4.1.0-released) · [4.1 迁移指南](https://opendatalab.github.io/MinerU/reference/migration_4_1/) · [运行时说明](https://opendatalab.github.io/MinerU/usage/tiers/) |
| 4.1.1–4.1.7 | Windows 多 GPU 识别、硬件诊断、PDF 文本、公式、版面及阅读顺序继续修补。4.1.7 的 DocVortex 要求为 `>=0.6.13,<0.7`，PaperReader 当前锁定 0.6.20。4.1.7 同时给 Doclib 的 HTTP 接口加入持久化令牌认证。 [发行记录](https://github.com/opendatalab/MinerU/releases) · [4.1.7 依赖声明](https://github.com/opendatalab/MinerU/blob/mineru-4.1.7-released/pyproject.toml) · [PaperReader 依赖](../backend/pyproject.toml) |

## 加速范围和实测

- DirectML 可用于兼容 Intel、AMD 和 NVIDIA GPU，安装在 Windows x64 上的 Python 包为 `onnxruntime-directml`。Linux x86_64 使用普通 ORT 加 `onnxruntime-ep-webgpu`。两条路径都可以回退 CPU。`model.onnx_device=auto|cpu|gpu` 或更高优先级的 `MINERU_MODEL_ONNX_DEVICE` 只控制 ONNX 路径。MinerU 优先选可识别的独显，在适用时用 OCR 识别模型为集显或未分类 GPU 校准；初次校准可能准备或下载权重。配置文件可保存自动选型结果。`mineru-kit hardware info --json` 读取诊断且不触发校准，`hardware detect --json` 可触发校准。 [运行时说明](https://opendatalab.github.io/MinerU/usage/tiers/) · [4.1.7 依赖声明](https://github.com/opendatalab/MinerU/blob/mineru-4.1.7-released/pyproject.toml)
- 版面、OCR **识别**、公式识别和表格 UNet 可走 GPU。普通 OCR **检测**在 Windows 仍走 CPU，印章检测、表格分类及 SLANet Plus 也走 CPU。公式识别 GPU 处理满 8 个的批次，尾部转 CPU。DirectML 会话要求顺序执行、关闭内存模式且同一会话的 `Run` 串行。上游约 2–3 倍的数据针对典型核心推理负载，端到端还受 PDF 渲染、CPU 阶段、裁图和建索引影响。 [运行时说明](https://opendatalab.github.io/MinerU/usage/tiers/) · [ONNX Runtime DirectML](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html) · [4.1.0 发布说明](https://github.com/opendatalab/MinerU/releases/tag/mineru-4.1.0-released)

已有整批对照走实际的解析和索引队列。原始数据位于本工作区的 `tmp/`。测试机为 i7-11800H + RTX 3060 Laptop 6 GiB，使用相同的七份 PDF（216 页）、本地模型和 FastEmbed CPU 设置，两组各跑一次并使用新文库。候选显式选择 GPU，独立探测确认该机自动模式也选择同一独显。 [基准方法与日志](../tmp/onnx-gpu/REPORT.md) · [结果汇总](../tmp/onnx-gpu/comparison.json)

| 指标 | 4.0.12 CPU | 4.1.7 DirectML |
| --- | ---: | ---: |
| 首篇正文就绪（含冷启动） | 250.7 秒 | 69.0 秒 |
| 七篇正文全部就绪 | 1,095.68 秒 | 523.21 秒（2.09 倍） |
| 七篇索引全部就绪 | 1,163.20 秒 | 602.95 秒（1.93 倍） |
| NVIDIA 整卡显存采样峰值 | 329 MiB | 4,452 MiB |
| 重排块 / 行内公式裁图 | 2,219 / 266 | 2,202 / 246 |
| 素材总数 | 544 | 520 |

两组均产出全部 216 页。显存峰值包含其他进程，每组只运行一次，且 MinerU 版本和设备一起改变。块和裁图数量差异需要逐页核对，无法从计数判断提取准确率。补齐 4.1.7 CPU 可分辨版本收益和设备收益。另一项对照中，BGE-M3 单独走 DirectML 可生成向量，和 MinerU 同时走 GPU 时整批在首篇索引阶段发生原生访问冲突 `0xC0000005`，随后出现 Windows 图形引擎超时 `0x141`。现有证据无法定位触发原因。 [解析与索引对照](../tmp/onnx-gpu/REPORT.md) · [FastEmbed 对照](../tmp/fastembed-gpu/REPORT.md)

## 解析质量

- 4.1.1 清理原生正文中 OCR 和回填后残留的 Unicode 私用区字符。4.1.6 保留脚注公式和公式编号，并去除同类别完全嵌套的重复文本框。4.1.7 在 4.1 分支恢复 ONNX 与 Torch 一致的按类别版面阈值，并按几何位置安放并入的图片区域。4.0.12 也有过同类阈值修复。这些变化值得在当前 Basic 流程的密集数学、双栏和脚注样本上复核。 [4.0.12](https://github.com/opendatalab/MinerU/releases/tag/mineru-4.0.12-released) · [4.1.1](https://github.com/opendatalab/MinerU/releases/tag/mineru-4.1.1-released) · [4.1.6](https://github.com/opendatalab/MinerU/releases/tag/mineru-4.1.6-released) · [4.1.7](https://github.com/opendatalab/MinerU/releases/tag/mineru-4.1.7-released)
- 4.1.4 改善数学定界符和普通美元符号的转义，还在 Standard/Advanced 的 PDF 文本模式里用 VLM 识别表外的行内公式切片，失败时按切片回退 MFR。后者需显式选择高阶档位，现有 Basic 不执行该 VLM 路径。Standard 仍用小模型做版面分析，并对公式、表格和需识别的文本使用 VLM。Advanced 将 VLM 用于更多步骤，包括版面分析，可生成图像说明和尝试解读图表，耗时和资源要求更高，质量增益随文档而变。当前桌面包还需要额外的 VLM 资产，例如 llama.cpp 的 GGUF 和 mmproj。 [4.1.4](https://github.com/opendatalab/MinerU/releases/tag/mineru-4.1.4-released) · [上游档位指南](https://github.com/opendatalab/MinerU/discussions/5709) · [模型来源](https://opendatalab.github.io/MinerU/usage/model_source/) · [PaperReader 模型目录](../backend/model_catalog.py)
- Flash 原生文本模式适合单独做预览或临时检索，校验后可为良好文本层的 PDF 提供更快首屏。它的双栏、复杂数学和表格能力有限，扫描件还需要 OCR。局部页段可用于用户指定的预览或难页对照。正式整篇结果要保留跨页续段、标题和段落的关系。 [上游档位指南](https://github.com/opendatalab/MinerU/discussions/5709) · [PaperReader PDF 转换](../backend/parse/pdf.py)

本机用 4.1.7 的 Flash 原生文本模式，在同一进程中分别读取有文本层的 `2210.03629v3.pdf` 和 `2510.05592v2.pdf` 的第 1、3 页。两次 `parse()` 加 `to_dict()` 分别耗时 2.35 和 1.76 秒，均返回原页索引 `[0, 2]` 并标记结果为非整篇。两份结果都未产出文档标题块，而已有 Basic 重排结果在相应页均有标题块，其中一篇两页只含 2 个图片块，而现有 Basic 经 PaperReader 转换后有 4 个图块。该小样本用于验证预览可行性，速度和质量仍需同条件比较。

## 集成边界

4.0.12 和 4.1.7 的 `parse()` / `parse_async()` 本地调用签名一致。PaperReader 的 `parse(path, tier='basic', ocr_mode='auto')` 仍是公开入口。局部 monkey patch 则直接依赖上游私有函数，覆盖三个表格处理阶段、窗口进度与取消、行内公式几何采集和 PDF 可见字符裁切。公开 `ParseResult` 提供页块、结构化输出及素材导出，但公开的行内公式 span 缺少独立 bbox，SDK 入口也未提供这些表格阶段的开关或逐窗口进度回调。Basic 的异步入口通过线程执行同步解析，应用的窗口回调和取消仍需要兼容层。HTTP 只给出任务和文件状态，接入前仍需解决现有逐窗口和公式裁图能力。 [4.1.7 分析入口](https://github.com/opendatalab/MinerU/blob/mineru-4.1.7-released/mineru/backend/analyze.py) · [4.0.12 SDK 源码](https://raw.githubusercontent.com/opendatalab/MinerU/mineru-4.0.12-released/mineru/parser/__init__.py) · [4.1.7 SDK 源码](https://raw.githubusercontent.com/opendatalab/MinerU/mineru-4.1.7-released/mineru/parser/__init__.py) · [输出协议](https://opendatalab.github.io/MinerU/reference/output_files/) · [运行时适配](../backend/parse/mineru_runtime.py) · [可见文本](../backend/parse/source.py)

如果将来引入服务边界，4.1 Tasks 接受 JSON 文件清单，使用按需 PUT 或 URL 输入，支持哈希预检、按文件结果和取消。旧 `/v1/uploads`、`/v1/parse/jobs` 已移除。同名 `/v1/file_parse` 是单独启动的 multipart 包装器，等待超时返回 `202` 后可查询已知任务，恢复范围受上游任务保留和重启限制。HTTP 取消能阻止发布迟到结果，已经开始且无法中断的推理可能继续。PaperReader 现有队列和文库可以继续拥有任务状态、解析产物、定位和索引；独立 HTTP 服务适合将来的可选远程工作节点或跨应用队列。 [4.1 迁移指南](https://opendatalab.github.io/MinerU/reference/migration_4_1/) · [Tasks API](https://opendatalab.github.io/MinerU/usage/tasks/) · [同步包装器](https://opendatalab.github.io/MinerU/usage/file_parse/)

## PaperReader 改进顺序

1. **落实 4.1.7 Windows 加速和回退。** 已提交基线依赖 4.0.12 / DocVortex 0.5.16，当前工作树及 `backend/.venv` 已用 4.1.7 / 0.6.20。继续使用现有 `uv.lock` 安装流程，Windows x64 使用 DirectML 1.24.4，FastEmbed 共享其 `onnxruntime` 模块并明确选择 CPU provider。uv 对 FastEmbed 的定向依赖排除防止同一环境安装第二个 ORT wheel，PyInstaller 已调整为收集 DirectML 发行元数据。在 worker 启动时统一应用 Auto/CPU/GPU 选项，变更后重启该 worker 以刷新缓存的选型和会话。记录各阶段实际 provider、CPU 回退原因和模型可用性。现有桌面包排除了 `mineru.kit` 和 `mineru.doclib`，开发和支持环境可用上游诊断命令，桌面内优先暴露实际会话状态。维持一个有界 Basic 解析 worker 和私有补丁所需的串行锁；额外 worker 先通过显存和稳定性测试。 [依赖声明](../backend/pyproject.toml) · [打包配置](../packaging/backend.spec) · [运行时适配](../backend/parse/mineru_runtime.py) · [FastEmbed 适配](../backend/rag/embedding.py)
2. **用同版本对照找到下一个瓶颈。** 固定文库输入、模型和输出路径，分别跑 4.0.12 CPU、4.1.7 CPU、4.1.7 GPU，重复并区分冷启动、首篇正文就绪、整批正文和整批索引。可用 `MINERU_PROFILE_STAGES=1` 记录上游推理分阶段耗时，应用补充排队、适配、裁图和就绪计时，以及峰值内存/显存、取消延迟。应用把 `MINERU_PROCESSING_WINDOW_SIZE` 默认设为 4，可从 4/8/16 页测起，再测渲染线程和窗口大小的交互。上游处理窗口默认 64 页。窗口变大会改变内存和取消响应，要按目标机器选择。 [运行时适配](../backend/parse/mineru_runtime.py) · [上游 CLI 参数](https://opendatalab.github.io/MinerU/usage/cli_tools/) · [上游耗时采集](https://github.com/opendatalab/MinerU/blob/mineru-4.1.7-released/mineru/utils/timing.py)
3. **缩小兼容层并固定 PaperReader 的输出契约。** 将 SDK 和私有补丁集中在一个兼容层，把源页对齐、标题和可见字符校验、PaperReader blocks 转换、素材及发布分开。现有转换会展开 list/index，丢掉 list 自身的跨页续接标记，也会把参考文献块归为普通段落，可先用样本验证保留这些结构对阅读和检索的影响。可直接使用 `ParseResult.pages` 或 `export_pages()` 副本，验证公开页序、几何和坐标，再替换重复读取。DocVortex 0.6.20 的 Hybrid PDF 路径仍会请求非 `visible_only` 快照，裁切补丁先保留，并用带裁切 Form 的样本向上游验证。Basic 保留行内公式几何钩子，匹配结合阅读顺序和 bbox，记录漏配，对缺 bbox 的 span 可用 LaTeX 渲染作为备选。局部重解析还需将钩子捕获的内部窗口页码映射到实际保留的原始页索引；当前以窗口起点加偏移作键，非连续页段可能找不到裁图，且损坏页可能被跳过。高阶 VLM 路径需要独立验收。 [运行时适配](../backend/parse/mineru_runtime.py) · [可见文本](../backend/parse/source.py) · [标题校验](../backend/parse/headings.py) · [块转换](../backend/parse/pdf.py) · [上游输出契约](https://opendatalab.github.io/MinerU/reference/output_files/)
4. **延后裁图并保护重解析后的引用。** 当前转换时每个素材都重新打开 PDF 并生成 PNG，可对普通清晰度和高清统一按需渲染和缓存，或在保留预渲染的前提下按页复用 PDF 句柄。继续保留正文图块和说明文字各自的来源框，并回归旋转与比例。DocVortex 0.6.20 在视觉容器和主体都带框时要求两者一致。公共 `PDFDocument.render_image()` 的实现是先渲染整页再裁切；替换现有区域渲染之前先按素材密度测内存和时间。按解析修订隔离素材缓存；旧产物保留可读，解析、素材、翻译和索引在新结果完整后切换。当前块 ID 含顺序号，上游调整阅读顺序会改变 ID。书签跳转已按页码和 bbox 重叠定位。优先复用这套逻辑，并核查书签状态匹配和添加去重等仍按 ID 比较的入口。按文档记录解析版本和档位，让重排格式变更可以按需重建，避免升级时自动把整个文库排进队列。 [裁图与块 ID](../backend/parse/pdf.py) · [来源框定位](../frontend/src/services/reflowGeometry.js)
5. **按样本扩展质量档位与结构化表格。** 先为文本层、双栏、扫描件、脚注公式、重复行内式、旋转页和跨页表格标注少量页面，对照文本完整性、阅读顺序、公式与编号、裁图及标题。表格可在指定文档或局部启用上游结构化识别，补齐模型并验证行列和合并单元格，再考虑 HTML/CSV 或索引文本；保留原图作为校对。Basic 继续作为桌面主流程，用户指定的复杂页可对照 Standard，仍有明确版面问题的页再测 Advanced。 [当前表格适配](../backend/parse/mineru_runtime.py) · [模型目录](../backend/model_catalog.py) · [上游档位指南](https://github.com/opendatalab/MinerU/discussions/5709)
6. **按故障和规模选择隔离方式。** 目前 `on_blocks` 在整篇 MinerU 推理和标题检查之后触发，末段要等待 `continues_prev` 确定后发布。需要更快预览时，先给 Flash 预览独立的状态。若部署中需要从 GPU 原生崩溃自动恢复，可把带兼容补丁的解析器放到持久本地子进程，主进程维持队列和产物的事务边界，按任务做受控的 CPU 重试。确有远程或多节点需求时再接 Tasks API，将其文件 ID、SHA-256、状态和取消映射到 PaperReader 自己的文档及源页定位。 [PaperReader 块发布](../backend/parse/pdf.py) · [FastEmbed 对照](../tmp/fastembed-gpu/REPORT.md) · [Tasks API](https://opendatalab.github.io/MinerU/usage/tasks/)

标题层级和跨页表格还有一个可选的上游后处理入口。`llm_aided` 可分别开启整篇标题层级校正和跨页表格单元格合并，默认关闭，启用时需配置兼容接口和凭据。可在书签、原生字体和表格结构证据不足的样本上试验，记录质量收益和额外延迟。 [4.1.7 后处理源码](https://github.com/opendatalab/MinerU/blob/mineru-4.1.7-released/mineru/backend/postprocess/llm_aided.py) · [4.1.7 配置源码](https://github.com/opendatalab/MinerU/blob/mineru-4.1.7-released/mineru/config.py)
