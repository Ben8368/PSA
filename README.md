# PSA — Photoshop COM Automation Tool

> 基于 Python + win32com 的 Photoshop 文字图层批量自动化修改工具

---

## 项目背景与设计思路

### 问题来源

设计工作中常常需要对 PSD 文档里的文案、字体、字重进行批量替换（例如多语言版本切换、品牌字体统一）。手工逐层修改效率极低，且改完后文字大小、行数往往会因为新字体的字形差异而跑版。

### 核心设计目标

1. **无损母版**：绝不直接修改用户指定的 PSD，所有操作在副本（`_auto.psd`）上进行。
2. **JSON 工单驱动**：先扫描输出 JSON，用户只需填写想改的部分，其余自动跳过。
3. **自适应排版**：更换文案/字体后，通过算法自动将文字高度（`bounds_h`）收敛到原始值，保证行数不变、视觉占位不变。
4. **空白实验室**：自适应算法在一个隔离的 1000×1000 空白文档里进行，不污染真实文档，测完数值后删除测试图层、将结果写回真实文档。
5. **全程日志**：每次运行生成带时间戳的 `.log` 文件，记录扫描结果、每次迭代、改前改后所有属性值。

---

## 技术方案选型

### 为什么用 COM 而不是 psd-tools

| 方案 | 优势 | 劣势 |
|---|---|---|
| **win32com (COM)** | 调用真实 PS 引擎，字体渲染、排版完全一致 | 需要 PS 正在运行，Windows Only |
| psd-tools | 无需 PS，跨平台 | 无真实渲染，文字 bounds 不可靠，写入支持有限 |
| ExtendScript (.jsx) | 原生 PS 脚本 | 不易与 Python 生态集成，调试困难 |

选择 COM 的核心原因：自适应算法依赖**真实渲染后的 bounding box**，只有 COM 调用真实 PS 渲染引擎才能保证数值准确。

### 单位统一策略

Photoshop COM 的 `TextItem.Size` 和 `TextItem.Leading` 均以**磅（pt）**为单位传递，但设计师习惯以 **px** 表达尺寸。工具在 JSON 工单和日志中统一展示 px，内部运算和向 COM 写入时始终用 pt。

```
px = pt × (DPI / 72)
pt = px × (72 / DPI)
```

读取图层 bounds 时，必须先将 PS 的标尺单位切换为像素（`RulerUnits = 1`），读完后恢复原值，防止干扰用户当前设置。

---

## 项目架构

```
C:\PSA\
├── psa.py              CLI 入口，子命令路由 (scan / apply / run)
├── psa_models.py       数据模型 (TextLayerRecord, AdaptedParams)
├── psa_utils.py        COM 底层工具函数和异常类
├── psa_fonts.py        字体索引构建和字重解析匹配
├── psa_logger.py       结构化日志写入器
├── psa_scanner.py      文档扫描（含智能对象递归）
├── psa_lab.py          空白实验室文档 + 20次自适应算法 (3 Phase)
├── psa_applier.py      工单应用：创建副本、_process_layer 统一处理、SO 边界防护
└── debug_mirror.py     调试工具：每行独立倒序的文案生成
```

### 模块依赖关系

```
psa.py
  ├── psa_scanner.py  ──→  psa_utils.py
  │                   ──→  psa_models.py
  │
  └── psa_applier.py ──→  psa_utils.py
                      ──→  psa_models.py
                      ──→  psa_fonts.py
                      ──→  psa_lab.py    ──→  psa_models.py
                                         ──→  psa_utils.py

psa_logger.py  （被 scanner / applier / lab 共同依赖）
```

### 应用阶段核心流程 (`psa_applier.py`)

```
apply_workorder()
  └─ _process_layer(app, doc, record, lab, in_so)  ← 统一处理直接层和 SO 层
       ├─ 定位图层 (find_layer_by_id / find_layer_by_path)
       ├─ Method A: scale calibration (Lab 中用原文案测 scale)
       ├─ lab.find_adapted_params()  ← 20次自适应 (Phase 1+2+3)
       ├─ _apply_to_text_layer()     ← 写回属性
       ├─ SO 边界防护 (expand_so_canvas, in_so only)
       └─ Method B: verify + REFINE (≤5轮真实渲染验证)
```

`_process_layer()` 消除了直接层和 SO 层的重复逻辑，通过 `in_so` 参数切换定位方式。

---

## 数据模型

### TextLayerRecord

扫描阶段产出，也是工单 JSON 的数据结构。

| 字段 | 含义 |
|---|---|
| `layer_id` | PS 图层 ID（`SaveAs` 副本后保持稳定，用于 apply 阶段定位图层） |
| `layer_path` | 从文档根到该图层的完整路径，`/` 分隔 |
| `in_smart_object` | 是否位于智能对象内部 |
| `so_layer_id / so_layer_path / so_psb_name` | 智能对象的定位信息 |
| `font` | PostScript 字体名（如 `NotoSans-Bold`） |
| `size_pt / size_px` | 字号（磅 / 像素） |
| `tracking` | 字间距（1/1000 em 为单位） |
| `auto_leading / leading_pt / leading_px` | 行间距模式及数值 |
| `bounds_h_px` | **自适应目标高度**，算法以此为收敛目标 |
| `dpi` | 所在文档的分辨率 |
| `enabled` | 用户在工单中标记为 `true` 时才执行修改 |
| `new_text / new_font_family / new_font_weight` | 用户填写的目标值 |

### AdaptedParams

自适应算法输出，包含最终写回 PS 的数值：
`font_ps`, `size_pt`, `size_px`, `auto_leading`, `leading_pt`, `leading_px`, `tracking`, `final_bounds_h_px`, `converged`

---

## 核心流程

### 1. 扫描阶段 (`psa.py scan`)

```
连接 PS COM
  └─ 打开/获取目标文档
       └─ 递归遍历所有图层
            ├─ TextLayer (Kind=2)    → 提取所有 TextItem 属性 → TextLayerRecord
            ├─ SmartObject (Kind=17) → 检查 PSB 是否已访问
            │    └─ 未访问 → 进入 SO（via JS placedLayerEditContents）
            │                → 递归扫描 SO 内图层
            │                → 关闭 SO（不保存）
            │                → 标记 PSB 已访问
            └─ LayerSet (group)      → 递归遍历子图层
  └─ 输出 JSON 工单（含全部图层信息，enabled 默认 false）
  └─ 写 .log 文件
```

**PSB 去重**：同一个 PSB 文件被多个 SO 实例引用时（例如复制了一个智能对象图层），只扫描一次、只修改一次。通过 `get_so_psb_name()` 用 ActionDescriptor 查询 PSB 文件名实现，无需打开 SO。

### 2. 用户编辑工单

打开输出的 `xxx_workorder.json`，对需要修改的图层：
- 设置 `"enabled": true`
- 填写 `new_text`（新文案）
- 填写 `new_font_family`（字体家族名，如 `"Noto Sans SC"`）
- 填写 `new_font_weight`（字重关键词，如 `"Bold"`, `"SemiBold"`, `"Regular"`）

未填或 `enabled: false` 的图层完全跳过。

### 3. 应用阶段 (`psa.py apply`)

```
读取工单 JSON
  └─ 构建字体索引（app.Fonts → {family: [FontEntry,...]}）
  └─ 解析每个 enabled 图层的目标 PostScript 字体名
  └─ 创建 _auto 副本（SaveAs copy=True，不改变活跃文档）
  └─ 打开 _auto 副本
       ├─ 直接图层（in_smart_object=False）
       │    └─ LabDocument(分辨率=文档DPI) 上下文
       │         └─ 对每个图层：
       │              find_layer_by_id → 自适应算法 → 写回属性
       └─ 智能对象图层（按 PSB 分组）
            └─ 每个 PSB 组：
                 enter_smart_object → LabDocument(分辨率=SO的DPI)
                   └─ 对每个图层：find_layer_by_path → 自适应算法 → 写回属性
                 soDoc.Save() + soDoc.Close()
  └─ auto_doc.Save() + auto_doc.Close()
  └─ 写 .log 文件
```

---

## 自适应算法详解

### 设计思路

换字体/文案后，同样的字号在新字体下渲染高度不同，且多行文案的高度还受行间距影响。算法目标是：**使新文字图层的 bounding box 高度（px）收敛至原始图层的高度**，以高度优先，不考虑宽度（文案长度可变）。

所有测试在**空白实验室文档**（1000×1000，DPI 与目标文档一致）中进行，避免被其他图层遮挡或影响。每个文字图层用完后删除，下一个图层复用同一个实验室文档。

### 字重预处理（算法入口前）

在进入 15 次迭代前，先确定字重。通过 `app.Fonts` 枚举安装字体，按 PostScript 名后缀（`-Bold`、`-SemiBold` 等）提取字重关键词和数值（100–900），然后找与目标字重最接近的可用字重。

```
精确关键词匹配优先 → 无精确匹配时按数值距离最近原则选取
```

### Phase 1：快速收敛（第 1–10 次，二分法）

目标：快速逼近目标高度的量级。

```
lo = 1.0,  hi = 500.0
for i in 1..10:
    mid = (lo + hi) / 2
    ti.Size = mid
    h = layer.Bounds[bottom] - layer.Bounds[top]  # 实际渲染高度
    if h < target_h: lo = mid
    else:            hi = mid
```

- 单行/多行均适用
- 始终保持 `UseAutoLeading = True`，不调行间距
- 10 次迭代后误差通常在 1–2px 以内

### Phase 2：精确收敛（第 11–15 次）

多行文案的高度同时受字号和行间距影响，Phase 1 仅调字号可能留有残差。Phase 2 根据文案类型分叉：

#### 多行文案（含 `\r` 或 `\n`）

交替调整行间距和字号：

```
UseAutoLeading = False
Leading = Size × 1.2   # 初始锚定

for prec_iter in 1..5:
    if |h - target_h| < 1.0: break   # 已收敛

    # Sub-A: 二分法搜索行间距 [Size×0.8, Size×2.5] × 7次
    lo_l = Size×0.8;  hi_l = Size×2.5
    for _ in 1..7:
        mid_l = (lo_l + hi_l) / 2
        ti.Leading = mid_l
        h_test = get_h()
        if h_test < target_h: lo_l = mid_l else: hi_l = mid_l

    # Sub-B: 若仍未收敛，微调字号 ±3%，重新锚定行间距
    if |h - target_h| >= 1.0:
        ti.Size *= (0.97 if h > target_h else 1.03)
        ti.Leading = ti.Size × 1.2
```

#### 单行文案

单行文案不受行间距影响，Phase 2 使用字号微调二分法（±5% 范围，7 次二分）逐步逼近目标高度：

```
for prec_iter in 1..5:
    if |h - target_h| < 1.0: break
    lo_s = Size × 0.95;  hi_s = Size × 1.05
    for _ in 1..7:
        mid_s = (lo_s + hi_s) / 2
        ti.Size = mid_s
        if get_h() < target_h: lo_s = mid_s else: hi_s = mid_s
```

### Phase 3：字间距自适应（第 16–20 次）

字号和行间距确定后，换字体/文案会导致文字宽度偏移。Phase 3 通过调整 tracking 使新文案宽度逼近原始宽度，保持视觉占位一致。

```
orig_w = measure_text_width(original_font, original_text, original_size, original_tracking)

current_tracking = original_tracking
for track_iter in 1..5:
    new_w = get_w()  # 当前新文案宽度

    # Step 1: 二分法搜索最佳 tracking [current-50, current+50] × 7次
    lo_t = current_tracking - 50;  hi_t = current_tracking + 50
    for _ in 1..7:
        mid_t = (lo_t + hi_t) / 2
        ti.Tracking = mid_t
        w_test = get_w()
        if w_test < orig_w: lo_t = mid_t else: hi_t = mid_t

    current_tracking = clamp((lo_t + hi_t) / 2, -100, 200)

    # 宽度差 < 5px 即认为收敛，提前退出
    if |new_w - orig_w| < 5.0: break

    # Step 2: tracking 调整无效时（diff > 10px），缩小字号 5% 重试
    if |new_w - orig_w| > 10.0:
        ti.Tracking = original_tracking  # 恢复
        ti.Size *= 0.95

        # 边界保护：多行文案检查字号缩小是否破坏了 Phase 2 的行间距结果
        # 如果影响 > 2px，停止 tracking 调整，保持 leading 优先
```

**边界保护机制**：多行文案中字号缩小可能破坏 Phase 2 已收敛的行间距。算法会对比缩放前后的 Phase 2 高度，若偏差 > 2px 则判定为"leading 被破坏"，立即停止 tracking 调整，优先保持行间距正确性。

### 写回顺序

向真实图层写回时，属性设置顺序至关重要，防止 PS 内部 reflow 干扰数值：

```
1. ti.Font        ← 先设字体
2. ti.Size        ← 再设字号
3. ti.UseAutoLeading / ti.Leading
4. ti.Tracking
5. ti.Contents    ← 最后写文案（触发 PS 重新排版）
```

---

## 智能对象处理

### 进入方式

PS COM 没有直接的"进入智能对象"API，通过执行 ExtendScript 触发：

```javascript
var idplacedLayerEditContents = stringIDToTypeID("placedLayerEditContents");
executeAction(idplacedLayerEditContents, new ActionDescriptor(), DialogModes.NO);
```

执行后 `app.ActiveDocument` 即变为 SO 内部的 PSB 文档，可直接操作。

### PSB 去重机制

多个 SO 图层实例可能共享同一 PSB 文件（复制 SO 图层时）。通过 ActionDescriptor 查询 SO 的 `fileReference` 字段获取 PSB 文件名，以此作为去重 key，确保每个 PSB 只被扫描/修改一次。

### 分辨率隔离

SO 内部的 PSB 可能有独立的分辨率（与外层文档不同）。实验室文档的 DPI 必须与被测文档一致，否则 pt→px 换算错误。因此：
- 直接图层 → `LabDocument(dpi = auto_doc.Resolution)`
- SO 内图层 → `LabDocument(dpi = soDoc.Resolution)`

### A+B Scale Calibration（图层缩放校准）

部分文字图层在 PS 中可能被应用了**自由变换**（缩放、旋转等），导致图层级别的 `bounds_h` ≠ 原始文字的实际渲染高度。自适应算法在实验室文档中渲染文字（无变换），如果不校准，Lab 收敛到的字号写回真实图层后会不对。

#### Method A：进入算法前校准

在 `_process_layer()` 中，先用**原文案+原字号**在 Lab 中测量一次高度：

```
lab_orig_h = lab.measure_text(original_font, original_text, original_size, ...)
scale = real_bounds_h / lab_orig_h          # 图层变换缩放系数
target_h_lab = real_bounds_h / scale        # Lab 空间中应该收敛的目标
```

`scale > 1` 说明原始图层被放大过，`scale < 1` 说明被缩小过。用 `target_h_lab` 代替 `real_bounds_h` 传入自适应算法，确保算法在 Lab 空间中收敛到正确值。

#### Method B：真实渲染验证 + REFINE

自适应写回真实图层后，**读取实际渲染的 bounds**，与期望值比对。偏差 ≥ 2px 时进入 REFINE 阶段（最多 5 轮）：

```
real_h = _real_bounds_h(app, layer)
for refine_iter in 1..5:
    diff = real_h - original_bounds_h
    if |diff| < 2.0: break
    ratio = original_bounds_h / real_h
    params.size_pt *= ratio
    if not auto_leading: params.leading_pt *= ratio
    ti.Size = new_size_pt
    ti.Leading = new_leading   # 如果手动行间距
    real_h = _real_bounds_h(app, layer)
```

按同比例缩放字号+行间距，避免 Lab 与真实渲染间的微小差异（如 COM API 精度损失、字体 hinting）累积成可见偏差。收敛阈值 **< 3px**，最终写入 `params.final_bounds_h_px` 和 `params.converged`。

### 智能对象边界防护

修改后的文案可能因字体/字号变化而超出 SO 内部画布边界，导致文字被切割。`psa_applier.py` 在处理完每个 SO 文档后会调用 `expand_so_canvas()`：

```javascript
// 将当前 SO 文档画布扩大 20%（1.2 倍），居中扩展
doc.resizeCanvas(origWidth * 1.2, origHeight * 1.2, AnchorPosition.MIDDLECENTER);
```

- 扩边比例为 **120%**（原始尺寸 × 1.2），居中向四面扩展
- 所有 SO 组内图层处理完成后、SO 保存前执行
- 异常时记录 WARNING 日志但不中断流程

---

## 字体系统设计

### PostScript 名与字重的关系

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

不同字体家族可用字重数量差异很大（有的仅 3 种，有的 9 种），`resolve_font()` 通过数值距离最近原则保证总能选到最接近的可用字重。

### 构建字体索引

```python
build_font_index(app)  →  {"Noto Sans": [FontEntry, FontEntry, ...], ...}
```

遍历 `app.Fonts`，每个字体取 `.Family`（家族名）和 `.Style`（样式字符串）构建索引。Style 字符串（如 `"SemiBold Italic"`）用于提取字重关键词和是否为斜体。

---

## CLI 使用说明

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

# 一步执行（扫描 + 应用，工单里已有 enabled 条目时使用）
python psa.py run --psd "banner.psd" --workorder "banner_workorder.json"

# 兼容旧式调用（等同于 run）
python psa.py --psd "banner.psd" --workorder "banner_workorder.json"
```

### 输出文件

| 文件 | 命名规则 | 说明 |
|---|---|---|
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

## 错误处理策略

| 错误类型 | 处理方式 |
|---|---|
| PS 未运行 | 立即退出，打印错误 |
| 无活跃文档 | 立即退出，打印错误 |
| 图层在 apply 阶段找不到 | 记录日志，跳过该图层，继续 |
| 字体家族不存在 | 记录警告，回退使用原字体，继续 |
| 无法进入智能对象 | 记录日志，跳过该 PSB 下所有图层，关闭悬空文档 |
| 自适应算法异常 | 记录日志，跳过该图层，继续 |
| COM `-2147213004`（无段落文字）| 视为 `auto_leading=True`，`leading=0`，继续 |

所有资源（实验室文档、SO 文档、标尺单位）均通过上下文管理器（`__exit__`）保证清理，即使中途抛出异常。

---

## 已知限制与后续扩展点

### 当前限制

- 需要 Photoshop 在 Windows 上运行（COM 依赖）
- 字符级别的混排格式（同一图层内多种字体/字号）暂不支持，只处理图层级属性

### 已实现功能（v1.5.0 更新）

| 功能 | 版本 | 说明 |
|---|---|---|
| 自适应收敛阈值 | v1.5.0 | Phase 2 阈值按目标高度 0.5% 缩放（最小 1px），超大字号不再过于严格 |
| 伪粗体（FauxBold）特殊处理 | v1.5.0 | REFINE 迭代 5→8 次，收敛阈值放宽至 4px/6px，解决边界框震荡 |
| 二级嵌套 SO 支持 | v1.5.0 | 新增 `so_chain` 字段追踪 SO 嵌套链，applier 递归进入深层 SO |
| 自适应 SO 边界扩展 | v1.5.0 | 扩边比例按字号变化率动态计算 `max(1.2, ratio*1.1)`，上限 3x |
| 字体名空格容错匹配 | v1.5.0 | `resolve_font` 增加去空格回退搜索（如 "NotoSans" → "Noto Sans"） |
| 自动行距优化 | v1.5.0 | multiline+auto_leading 文案不再强制修改 leading，减少抖动 |
| 字间距自适应（Phase 3） | v1.4.0 | 5 次迭代二分法，支持 fallback 和 leading 边界保护 |
| A+B Scale Calibration | v1.3.0 | 变换图层自动校准 + 真实渲染验证 REFINE |
| SO 边界防护 | v1.2.0 | 动态画布扩展，防止文字切割 |
| 单行 Phase 2 分支 | v1.4.0 | 单行文案使用字号微调二分法，多行保持 leading+size 交替 |

### 扩展点

| 功能 | 位置 | 说明 |
|---|---|---|
| 批量文档处理 | `psa.py` | 新增 `batch` 子命令，遍历目录下所有 PSD |
| GUI 工单编辑器 | 新文件 | 用 tkinter 或 web 界面替代手动编辑 JSON |
| 颜色替换 | `psa_applier.py: _apply_to_text_layer()` | TextItem.Color 已在扫描中记录 |

---

## 开发环境

- Python 3.10+
- Windows 10/11
- Adobe Photoshop CC 2017–2025
- 依赖：`pywin32`（`pip install pywin32`）
