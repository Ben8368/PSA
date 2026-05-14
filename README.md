# PSA — Photoshop COM Automation Tool

> 基于 Python + win32com 的 Photoshop 文字图层批量自动化修改工具

> **项目状态：MVP 已交付 · 不再迭代**
>
> 本项目的核心算法已交付至 [MediaTools](https://github.com/Ben8368/MediaTools)，对方已完成移植。
> 本项目作为稳定 MVP 存档，不再进行功能迭代。最终版本：**v1.5.4**（2026-05-13）

---

## 项目交付 Delivery

本项目专为 [MediaTools](https://github.com/Ben8368/MediaTools) 重写核心自适应排版算法，替代其原有文字修改引擎。交付日期：**2026-05-13**。

### 交付内容

| 类别 | 文件 | 说明 |
|------|------|------|
| 核心模块 | `psa_models.py` | 数据模型（TextLayerRecord, AdaptedParams） |
| | `psa_utils.py` | COM 底层工具函数和异常类 |
| | `psa_logger.py` | 结构化日志写入器 |
| | `psa_fonts.py` | 字体索引构建和字重解析匹配 |
| | `psa_scanner.py` | 文档扫描（含智能对象递归） |
| | `psa_lab.py` | 空白实验室文档管理 |
| | `psa_algorithm.py` | 自适应算法核心（Phase 1/2/3 + Width Precheck） |
| | `psa_applier.py` | 工单应用引擎 |
| | `psa_so_handler.py` | 智能对象递归处理 |
| 适配器包 | `psa_mediatools_adapter/__init__.py` | 4 个公开 API（scan/apply/run/verify-font） |
| | `psa_mediatools_adapter/_bridge.py` | PhotoshopConnector 桥接层 |

共计 11 个文件，约 2,500 行 Python 代码。所有文件均 < 500 行。

### 对接文档

- `docs/MediaTools_对接方案.md` — 架构设计与替换范围
- `docs/MediaTools_对接操作说明.md` — 逐步操作指南

---

## Core Capabilities 核心能力

### 自适应排版算法 Adaptive Algorithm

三阶段迭代 + REFINE 真实渲染验证，使换字体/换文案后的文字高度收敛至原始值：

| Phase | 迭代次数 | 方法 | 调整目标 |
|-------|---------|------|---------|
| Phase 1 | ≤10 轮 | Binary Search [1, 500] pt | 字号（粗收敛） |
| Phase 2 | ≤5 轮 | 多行：leading+size 交替；单行：size 微调 | 字号+行间距（精收敛） |
| Width Precheck | 3 轮 | 宽度溢出预缩放（ratio > 1.3 时触发） | 字号（防溢出） |
| Phase 3 | ≤5 轮 | Tracking binary search + size fallback | 字间距（宽度匹配） |
| REFINE | 3-5 轮 | 真实渲染验证，按比例修正 | 字号+行间距（最终校验） |

### Smart Object 嵌套支持

- 最多 **3 层**嵌套 SO 递归处理
- `fileReference@|@layer_path` **复合主键**去重，同名不同源 SO 不误合并
- 每层 SO 独立 `LabDocument`，**分辨率隔离**（DPI 与 SO 文档一致）
- SO 边界动态扩边：`max(1.2, size_ratio * 1.1)`，上限 3.0x

### 伪粗体 FauxBold 处理

- REFINE 放宽收敛阈值（4px vs 普通 2px）和迭代次数（8 轮 vs 5 轮）
- 解决伪粗体图层字体变更后边界框震荡导致的假阴性

### 三层宽度兜底 Width Protection

- **Level 1**：Phase 2 后宽度预检查，ratio > 1.3 时预缩放字号并回跑 Phase 2
- **Level 2**：tracking 触底 -100 后 3 轮二分搜索字号，下限 80% 原始字号
- **Level 3**：触 80% 地板锁定并 WARNING，放弃宽度匹配以保证可读性

### 其他特性

- **"保一条"安全策略**：各阶段早退时追加一次额外迭代，防边界震荡假收敛
- **激进早退迭代**：各阶段"最多 N 轮 + 早退"，实际运行速度提升约 30-40%
- **装饰性单英文字符跳过**：单个 ASCII 字母图层自动跳过，中文单字不受影响
- **字体名空格容错**：`resolve_font` 支持去空格回退搜索（如 "NotoSans" → "Noto Sans"）
- **字重自动匹配**：无需指定字重，按数值距离最近原则选取可用字重
- **A+B Scale Calibration**：Method A 进入算法前校准变换图层；Method B 真实渲染验证 + REFINE
- **全程日志**：每次运行生成带时间戳的 `.log` 文件，记录每次迭代详情

---

## Architecture 项目架构

```
C:\PSA\
├── psa.py              CLI 入口，子命令路由 (scan / apply / run)
├── psa_models.py       数据模型 (TextLayerRecord, AdaptedParams)
├── psa_utils.py        COM 底层工具函数和异常类
├── psa_fonts.py        字体索引构建和字重解析匹配
├── psa_logger.py       结构化日志写入器
├── psa_scanner.py      文档扫描（含智能对象递归）
├── psa_lab.py          空白实验室文档管理
├── psa_algorithm.py    自适应算法核心 (Phase 1/2/3 + Width Precheck)
├── psa_applier.py      工单应用引擎
├── psa_so_handler.py   智能对象递归处理
├── psa_mediatools_adapter/   MediaTools 适配器包
│   ├── __init__.py     4 个公开 API
│   └── _bridge.py      PhotoshopConnector 桥接
└── debug_mirror.py     调试工具：每行独立倒序的文案生成
```

### Module Dependencies 模块依赖

```
psa.py (CLI)
  ├── psa_scanner.py
  │     ├── psa_models.py
  │     └── psa_utils.py
  ├── psa_applier.py
  │     ├── psa_models.py
  │     ├── psa_utils.py
  │     ├── psa_fonts.py
  │     ├── psa_lab.py
  │     │     ├── psa_models.py
  │     │     ├── psa_utils.py
  │     │     └── psa_algorithm.py
  │     │           └── psa_utils.py
  │     └── psa_so_handler.py
  │           ├── psa_models.py
  │           ├── psa_utils.py
  │           └── psa_lab.py
  └── psa_logger.py (standalone)

psa_mediatools_adapter/__init__.py
  ├── psa_models.py, psa_utils.py, psa_logger.py
  ├── psa_fonts.py, psa_scanner.py, psa_applier.py
  └── psa_mediatools_adapter/_bridge.py
```

### Apply 核心流程

```
apply_workorder()
  └─ _process_layer(app, doc, record, lab, in_so)  ← 统一处理直接层和 SO 层
       ├─ 定位图层 (find_layer_by_id / find_layer_by_path)
       ├─ Method A: scale calibration (Lab 中用原文案测 scale)
       ├─ lab.find_adapted_params()  ← Phase 1+2+3 自适应
       ├─ _apply_to_text_layer()     ← 写回属性
       ├─ SO 边界防护 (expand_so_canvas, in_so only)
       └─ Method B: verify + REFINE (≤5轮真实渲染验证)
```

---

## Adaptive Algorithm 自适应算法详解

### 设计思路

换字体/文案后，同样的字号在新字体下渲染高度不同，且多行文案的高度还受行间距影响。算法目标是：**使新文字图层的 bounding box 高度（px）收敛至原始图层的高度**，以高度优先，不考虑宽度（文案长度可变）。

所有测试在**空白实验室文档**（1000×1000，DPI 与目标文档一致）中进行，避免被其他图层遮挡或影响。每个文字图层用完后删除，下一个图层复用同一个实验室文档。

### 字重预处理 Weight Preprocessing

在进入迭代前，先确定字重。通过 `app.Fonts` 枚举安装字体，按 PostScript 名后缀（`-Bold`、`-SemiBold` 等）提取字重关键词和数值（100–900），然后找与目标字重最接近的可用字重。

```
精确关键词匹配优先 → 无精确匹配时按数值距离最近原则选取
```

### Phase 1：快速收敛 Binary Search（≤10 轮）

目标：快速逼近目标高度的量级。

```
lo = 1.0,  hi = 500.0
for i in 1..10:
    mid = (lo + hi) / 2
    ti.Size = mid
    h = layer.Bounds[bottom] - layer.Bounds[top]
    if h < target_h: lo = mid
    else:            hi = mid
```

- 单行/多行均适用
- 始终保持 `UseAutoLeading = True`，不调行间距
- Early exit：搜索区间 < 2pt 或高度差 < 4%

### Phase 2：精确收敛 Precision（≤5 轮）

#### 多行文案 multiline

交替调整行间距和字号：

```
UseAutoLeading = False
Leading = Size × 1.2

for prec_iter in 1..5:
    if |h - target_h| < threshold: break
    # Sub-A: 二分法搜索行间距 [Size×0.8, Size×2.5] × 5次
    # Sub-B: 若仍未收敛，微调字号 ±3%，重新锚定行间距
```

#### 单行文案 singleline

字号微调二分法（±5% 范围，5 次二分 × 5 轮）：

```
for prec_iter in 1..5:
    if |h - target_h| < threshold: break
    lo_s = Size × 0.95;  hi_s = Size × 1.05
    for _ in 1..5:
        mid_s = (lo_s + hi_s) / 2
        ti.Size = mid_s
        if get_h() < target_h: lo_s = mid_s else: hi_s = mid_s
```

### Width Precheck 宽度预检查

Phase 2 完成后，若新文案宽度 > 原始宽度 × 1.3，预缩放字号并回跑简化 Phase 2（3 轮），字号下限 80%。

### Phase 3：字间距自适应 Tracking（≤5 轮）

```
for track_iter in 1..5:
    # Step 1: 二分法搜索 tracking [current-50, current+50] × 7次
    # Step 2: tracking 无效时缩小字号 5% 重试
    # 边界保护：多行文案中字号缩小若破坏 leading > 3px，停止调整
    if |new_w - orig_w| < 5.0: break
```

- Tracking 范围：-100 ~ 200
- 宽度硬底线：80% 原始字号

### REFINE 真实渲染验证

自适应写回真实图层后，读取实际渲染的 bounds，与期望值比对。偏差 ≥ 2px 时进入 REFINE：

```
for refine_iter in 1..5:
    diff = real_h - original_bounds_h
    if |diff| < 2.0: break
    ratio = original_bounds_h / real_h
    params.size_pt *= ratio
    if not auto_leading: params.leading_pt *= ratio
```

### 收敛阈值 Convergence Thresholds

| 场景 | Phase 2 阈值 | 最终阈值 |
|------|-------------|---------|
| 普通图层 | `max(1.0, target_h × 0.005)` | `max(2.0, target_h × 0.008)` |
| 伪粗体 | `max(2.0, target_h × 0.01)` | `max(2.0, target_h × 0.01)` |

### 写回顺序 Writeback Order

```
1. ti.Font        ← 先设字体
2. ti.Size        ← 再设字号
3. ti.UseAutoLeading / ti.Leading
4. ti.Tracking
5. ti.Contents    ← 最后写文案（触发 PS 重新排版）
```

---

## Smart Object Processing 智能对象处理

### 进入方式

PS COM 没有直接的"进入智能对象"API，通过执行 ExtendScript 触发：

```javascript
var idplacedLayerEditContents = stringIDToTypeID("placedLayerEditContents");
executeAction(idplacedLayerEditContents, new ActionDescriptor(), DialogModes.NO);
```

执行后 `app.ActiveDocument` 即变为 SO 内部的 PSB 文档，可直接操作。

### PSB 去重机制

多个 SO 图层实例可能共享同一 PSB 文件（复制 SO 图层时）。通过 ActionDescriptor 查询 SO 的 `fileReference` 字段获取 PSB 文件名，以此作为去重 key，确保每个 PSB 只被扫描/修改一次。

复合主键：`fileReference@|@layer_path`，同名不同源嵌入 SO 不再误合并。

### 分辨率隔离 Resolution Isolation

SO 内部的 PSB 可能有独立的分辨率（与外层文档不同）。实验室文档的 DPI 必须与被测文档一致，否则 pt→px 换算错误：

- 直接图层 → `LabDocument(dpi = auto_doc.Resolution)`
- SO 内图层 → `LabDocument(dpi = soDoc.Resolution)`

### A+B Scale Calibration 图层缩放校准

部分文字图层在 PS 中可能被应用了**自由变换**（缩放、旋转等），导致图层级别的 `bounds_h` ≠ 原始文字的实际渲染高度。

**Method A：进入算法前校准**

```
lab_orig_h = lab.measure_text(original_font, original_text, original_size, ...)
scale = real_bounds_h / lab_orig_h
target_h_lab = real_bounds_h / scale
```

**Method B：真实渲染验证 + REFINE**

写回后读取真实图层 bounds，偏差 ≥ 2px 时按比例修正字号+行间距，最多 5 轮。

### SO 边界防护 Boundary Protection

修改后的文案可能因字体/字号变化而超出 SO 画布边界。处理完每个 SO 后调用 `expand_so_canvas()`：

```javascript
doc.resizeCanvas(origWidth * scale, origHeight * scale, AnchorPosition.MIDDLECENTER);
```

- 扩边比例：动态计算 `max(1.2, size_ratio * 1.1)`，上限 3.0x
- 居中向四面扩展
- 异常时记录 WARNING 但不中断

---

## Font System 字体系统

### PostScript 名与字重

PS COM 的 `ti.Font` 接受 **PostScript 名**（如 `NotoSans-SemiBold`），不是字体家族名。字重编码在名字后缀中：

```
NotoSans-Thin       → Thin    (100)
NotoSans-Light      → Light   (300)
NotoSans-Regular    → Regular (400)
NotoSans-Medium     → Medium  (500)
NotoSans-SemiBold   → SemiBold(600)
NotoSans-Bold       → Bold    (700)
NotoSans-ExtraBold  → ExtraBold(800)
NotoSans-Black      → Black   (900)
```

### 字体索引构建

```python
build_font_index(app)  →  {"Noto Sans": [FontEntry, ...], ...}
```

遍历 `app.Fonts`，每个字体取 `.Family`（家族名）和 `.Style`（样式字符串）构建索引。

### 字体解析 resolve_font

```
resolve_font(font_index, target_family, target_weight_kw)
```

- 精确关键词匹配优先
- 无精确匹配时按数值距离最近原则选取
- 支持大小写不敏感和去空格回退搜索

---

## Data Models 数据模型

### TextLayerRecord

扫描阶段产出，也是工单 JSON 的数据结构。

| 字段 | 含义 |
|------|------|
| `layer_id` | PS 图层 ID（`SaveAs` 副本后保持稳定） |
| `layer_path` | 从文档根到该图层的完整路径，`/` 分隔 |
| `in_smart_object` | 是否位于智能对象内部 |
| `so_layer_id / so_layer_path / so_psb_name` | 智能对象的定位信息 |
| `so_chain` | SO 嵌套链（从外层到内层） |
| `font` | PostScript 字体名（如 `NotoSans-Bold`） |
| `size_pt / size_px` | 字号（磅 / 像素） |
| `tracking` | 字间距（1/1000 em） |
| `auto_leading / leading_pt / leading_px` | 行间距模式及数值 |
| `bounds_h_px` | **自适应目标高度**，算法以此为收敛目标 |
| `faux_bold / faux_italic` | 伪粗体/伪斜体标记 |
| `dpi` | 所在文档的分辨率 |
| `enabled` | 用户标记为 `true` 时才执行修改 |
| `new_text / new_font_family / new_font_weight` | 用户填写的目标值 |

### AdaptedParams

自适应算法输出，包含最终写回 PS 的数值：

| 字段 | 含义 |
|------|------|
| `font_ps` | 最终 PostScript 字体名 |
| `size_pt / size_px` | 最终字号 |
| `auto_leading / leading_pt / leading_px` | 最终行间距 |
| `tracking` | 最终字间距 |
| `final_bounds_h_px` | 实际渲染高度 |
| `target_h_px` | 目标高度 |
| `converged` | 是否收敛 |
| `iterations_log` | 每次迭代日志 |

---

## CLI Usage 使用说明

### 依赖安装

```bash
pip install pywin32
```

### 命令

```bash
# 扫描当前活跃文档（PS 中打开的）
python psa.py scan

# 扫描指定 PSD 文件
python psa.py scan --psd "D:\designs\banner.psd"

# 扫描并指定工单输出路径
python psa.py scan --psd "banner.psd" --output "banner_task.json"

# 应用工单（在 _auto 副本上执行）
python psa.py apply --psd "banner.psd" --workorder "banner_workorder.json"

# 一步执行（扫描 + 应用）
python psa.py run --psd "banner.psd" --workorder "banner_workorder.json"

# 兼容旧式调用（等同于 run）
python psa.py --psd "banner.psd" --workorder "banner_workorder.json"
```

### 输出文件

| 文件 | 命名规则 | 说明 |
|------|---------|------|
| 工单 JSON | `<psd名>_workorder.json` | 扫描输出，用户编辑后交给 apply |
| 副本 PSD | `<psd名>_auto.psd` | apply 的实际落地文件，原文件不变 |
| 日志 | `<psd名>_YYYYMMDD_HHMMSS.log` | 每次运行独立一份 |

### 工单 JSON 示例

```json
[
  {
    "layer_id": 449,
    "layer_path": "背景组/标题文字",
    "layer_name": "标题文字",
    "in_smart_object": false,
    "text": "Original Headline",
    "font": "NotoSansSC-Medium",
    "size_pt": 117.4,
    "size_px": 117.4,
    "tracking": -30.0,
    "auto_leading": true,
    "leading_pt": 0.0,
    "bounds_h_px": 131.0,
    "dpi": 72.0,
    "enabled": true,
    "new_text": "新标题文字",
    "new_font_family": "Noto Sans SC",
    "new_font_weight": "Bold"
  }
]
```

---

## Error Handling 错误处理

| 错误类型 | 处理方式 |
|---------|---------|
| PS 未运行 | 立即退出，打印错误 |
| 无活跃文档 | 立即退出，打印错误 |
| 图层在 apply 阶段找不到 | 记录日志，跳过该图层，继续 |
| 字体家族不存在 | 记录警告，回退使用原字体，继续 |
| 无法进入智能对象 | 记录日志，跳过该 PSB 下所有图层，关闭悬空文档 |
| 自适应算法异常 | 记录日志，跳过该图层，继续 |
| COM `-2147213004`（无段落文字） | 视为 `auto_leading=True`，`leading=0`，继续 |

所有资源（实验室文档、SO 文档、标尺单位）均通过上下文管理器（`__exit__`）保证清理，即使中途抛出异常。

---

## Known Limitations 已知限制

- 需要 Photoshop 在 Windows 上运行（COM 依赖）
- 字符级别的混排格式（同一图层内多种字体/字号）不支持，只处理图层级属性

---

## Development Environment 开发环境

- Python 3.10+
- Windows 10/11
- Adobe Photoshop CC 2017–2025
- 依赖：`pywin32`（`pip install pywin32`）

---

## Version History 版本历史

| Version | Date | Highlights |
|---------|------|-----------|
| v1.5.4 | 2026-05-13 | Code split: `psa_algorithm.py` + `psa_so_handler.py`，all files < 500 lines |
| v1.5.3 | 2026-05-13 | Composite key SO dedup, 3-level width fallback |
| v1.5.2 | 2026-05-13 | "Safety-take" strategy, MediaTools adapter, 3-stage stress test passed |
| v1.5.1 | 2026-05-12 | Aggressive early-exit (~30-40% speedup), SO depth cap, decorative char skip |
| v1.5.0 | 2026-05-12 | Adaptive thresholds, faux-bold handling, nested SO chains, dynamic SO expansion |
| v1.4.0 | 2026-05-12 | Phase 2 single/multiline split, Phase 3 full rewrite |
| v1.3.0 | 2026-05-12 | A+B scale calibration, unified `_process_layer` |
| v1.2.0 | 2026-05-12 | Tracking adaptation, SO boundary protection |
| v1.1.0 | 2026-05-12 | SO write fix, PSB dedup |
| v1.0.0 | 2026-05-12 | Initial release |
