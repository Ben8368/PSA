# PSA → MediaTools 对接操作说明

## 前置条件

- Windows 10/11
- Python 3.10+
- Adobe Photoshop 已安装并运行
- 已安装 `pywin32`（`pip install pywin32`）

## 第一步：复制 PSA 文件

将以下文件复制到 MediaTools 项目的 `src/` 目录下：

**PSA 核心模块（9 个文件）：**

```
psa_models.py
psa_utils.py
psa_logger.py
psa_fonts.py
psa_scanner.py
psa_lab.py
psa_algorithm.py
psa_applier.py
psa_so_handler.py
```

**PSA 适配器包（1 个目录）：**

```
psa_mediatools_adapter/
    __init__.py
    _bridge.py
```

> 共计 11 个文件，约 2,500 行 Python 代码。所有文件均 < 500 行。

## 第二步：修改 MediaTools 的 main.py

### 2.1 修改 import 区域

删除以下 import 行：
```python
from config_reader import read_mappings
from text_modifier import process_document, AdjustParams
from ticket_workflow import (
    scan_document_for_ticket,
    write_scan_layers_csv,
    write_scan_summary_csv,
    build_ticket_rows,
    write_ticket_csv,
    read_ticket_csv,
    execute_ticket,
)
```

替换为：
```python
from psa_mediatools_adapter import psa_scan, psa_apply, psa_run
```

### 2.2 修改 main() 函数中的 CLI 分发

将以下模式的函数调用替换为 PSA 版本：

**原 `--scan` / `--scan-ticket` / `--scan-only` / `--build-ticket` 分支：**

```python
# 原来（删除）
if args.scan:
    doc = ps.open_document(args.psd)
    rows = scan_document_for_ticket(ps, doc, args.psd)
    ...

# 改为
if args.scan or args.scan_ticket or args.scan_only or args.build_ticket:
    psa_scan(ps, psd_path=args.psd, output_dir=args.output)
```

**原 `--execute-ticket` / `--ticket` 分支：**

```python
# 原来（删除）
if args.execute_ticket or args.ticket:
    ticket_rows = read_ticket_csv(ticket_path)
    results = execute_ticket(ps, args.psd, ticket_rows, output_dir, params)
    ...

# 改为
if args.execute_ticket or args.ticket:
    result = psa_apply(ps, psd_path=args.psd, workorder_path=ticket_path, output_dir=args.output)
    # result 包含 results、summary、log_file 等字段，供前端展示
```

### 2.3 移除不再需要的 CLI 参数

以下 argparse 参数对应的功能已被 PSA 覆盖或不再需要，可移除：
- `--tracking-min` / `--tracking-step` / `--tolerance` 等 AdjustParams 参数
- `--format` (PNG/JPG 导出)
- `--jpg-quality`
- `--font-metrics` / `--build-font-metrics`
- `--use-cache`
- `--csv`（传统 CSV 模式）
- `--export-mapping`

### 2.4 修改 font_verifier.py（可选）

如果保留字体验证工具，将其内部 `from font_weight_mapper import find_closest_weight` 替换为：
```python
from psa_fonts import build_font_index, resolve_font
# 用 resolve_font() 替代 find_closest_weight()
```

## 第三步：测试验证

```bash
# 1. 扫描文档
python main.py --psd test.psd --scan --output ./output

# 2. 编辑输出的 JSON 工单（设置 new_text / new_font_family / enabled）

# 3. 执行修改
python main.py --psd test.psd --execute-ticket ./output/test_workorder.json --output ./output

# 4. 检查输出
# - test_auto.psd：修改后的副本
# - test_*.log：详细迭代日志
# - 控制台输出：每层处理结果
```

## 第四步：回退方案

如需回退到 MediaTools 原有逻辑：
1. 恢复 `main.py` 的原始 import 和函数调用
2. 删除 `psa_*.py` 和 `psa_mediatools_adapter/` 目录

PSA 文件完全不侵入 MediaTools 原有代码，删除即可恢复。

## 附录 A：JSON 工单格式

```json
[
  {
    "layer_id": 123,
    "layer_name": "Title",
    "layer_path": "Group/Title",
    "text": "Hello World",
    "font": "NotoSans-Bold",
    "size_pt": 72.0,
    "tracking": 0.0,
    "bounds_h_px": 96.0,
    "new_text": "你好世界",
    "new_font_family": "Byte Sans",
    "new_font_weight": "",
    "enabled": true
  }
]
```

- `new_font_weight` 留空即可，PSA 自动匹配最接近字重
- 前端只需填写 `new_text` 和 `new_font_family`，设置 `enabled: true`
- 不改的图层保持 `enabled: false` 或直接删除该条目

## 附录 B：Apply 返回格式

```json
{
  "source_psd": "C:\\project\\test.psd",
  "auto_psd": "C:\\project\\test_auto.psd",
  "log_file": "C:\\project\\test_20260513_143021.log",
  "results": [
    {
      "layer_path": "Group/Title",
      "original_text": "Hello World",
      "new_text": "你好世界",
      "original_font": "NotoSans-Bold",
      "new_font": "Byte Sans Bold",
      "original_size_pt": 72.0,
      "final_size_pt": 68.5,
      "original_bounds_h": 96.0,
      "final_bounds_h": 94.0,
      "converged": true,
      "skipped": false
    }
  ],
  "summary": {
    "total": 15,
    "processed": 14,
    "skipped": 1,
    "converged": 14,
    "errors": 0
  }
}
```

- `results` 数组供前端做前后工单对比展示
- `log_file` 指向完整日志文件，前端可读取展示
- `summary` 提供整体统计
