# PSA → MediaTools 对接方案

## 1. 背景

MediaTools 是一个 PSD 文字批量修改工具，其核心自适应算法存在收敛不稳定、智能对象嵌套不支持、伪粗体处理缺失等问题。PSA 项目专门为解决这些问题而开发，提供更成熟的自适应算法和相关能力。

**对接目标**：用 PSA 的核心算法替换 MediaTools 的文字修改引擎，同时保留 MediaTools 的 CLI 框架和外围基础设施。

## 2. 架构概览

```
MediaTools 项目（对方）
├── main.py                    ← CLI 入口（保留，改 3 行 import）
├── ps_connector.py            ← PS 连接管理（保留，不改）
├── font_verifier.py           ← 字体验证工具（保留，改 1 行 import）
├── font_weight_mapper.py      ← 丢弃（PSA 自动匹配字重）
├── text_modifier.py           ← 丢弃（PSA 替换）
├── ticket_json.py             ← 丢弃（PSA 提供 JSON 工单）
├── ticket_workflow.py         ← 丢弃（PSA 替换）
├── ticket_excel.py            ← 丢弃
├── config_reader.py           ← 丢弃
├── font_metrics_cache.py      ← 丢弃
├── generate_bytesans_mapping.py ← 丢弃
│
└── psa_mediatools_adapter/    ← 新增（PSA 适配层）
    ├── __init__.py            ← 4 个公开 API
    └── _bridge.py             ← PhotoshopConnector 桥接

PSA 核心模块（新增，复制到对方 src/ 下）
├── psa_models.py              ← 数据模型
├── psa_utils.py               ← COM 底层工具
├── psa_logger.py              ← 日志系统
├── psa_fonts.py               ← 字体系统
├── psa_scanner.py             ← 文档扫描
├── psa_lab.py                 ← 实验室文档
├── psa_algorithm.py           ← 自适应算法（核心）
├── psa_applier.py             ← 图层应用
└── psa_so_handler.py          ← 智能对象递归处理
```

## 3. 替换范围

| MediaTools 能力 | 处置 | 替代方案 |
|----------------|------|---------|
| 自适应算法 (`text_modifier.py`) | 完全替换 | PSA 三阶段自适应 + REFINE |
| 智能对象处理 | 完全替换 | PSA 嵌套 SO 递归（最多 3 层） |
| 工单格式 (`ticket_json.py`) | 完全替换 | PSA JSON 工单 |
| CSV 映射 (`config_reader.py`) | 丢弃 | 不需要 |
| 字体缓存 (`font_metrics_cache.py`) | 丢弃 | 不稳定，PSA 实时测量更可靠 |
| PNG/JPG 导出 | 丢弃 | 仅处理 PSD |
| Excel 同步 (`ticket_excel.py`) | 丢弃 | 不需要 |
| 字重匹配 (`font_weight_mapper.py`) | 丢弃 | PSA 自动匹配最接近字重 |
| PS 连接 (`ps_connector.py`) | **保留** | 不动对方代码 |
| CLI 入口 (`main.py`) | **保留** | 仅改 import |
| 字体验证 (`font_verifier.py`) | **保留** | 替换内部依赖 |

## 4. 数据流

### Scan 流程
```
CLI (--scan / --scan-ticket)
  → ps.connect()
  → doc = ps.open_document(psd_path)
  → psa_scan(ps, psd_path, output_dir)
      → 提取 ps.app → PSA scanner
      → 递归扫描（含嵌套 SO）
      → 输出 JSON 工单
  → ps.close_document(doc)
```

### Apply 流程
```
CLI (--execute-ticket)
  → ps.connect()
  → 读取 JSON 工单 → list[TextLayerRecord]
  → psa_apply(ps, psd_path, workorder_path, output_dir)
      → 过滤装饰性单英文字符
      → 自动跳过无变更图层
      → 创建 _auto.psd 副本
      → 直接层：LabDocument.find_adapted_params() → 写回
      → SO 层：process_so_level() 递归进入
      → 每层：REFINE 校验 + SO 边界扩展
      → 返回 ModifyResult（供前端对比展示）
  → ps.close_document(doc)
```

## 5. PSA 核心能力（对方获得）

| 能力 | 说明 |
|------|------|
| 三阶段自适应算法 | Phase 1 字号二分 + Phase 2 精确收敛 + Phase 3 字间距微调 |
| 激进早退迭代 | 各阶段最多 N 轮，提前收敛则早退，保一条安全策略 |
| 三层宽度兜底 | 预缩放 + tracking 二分 + 80% 硬底线 |
| 嵌套 SO 支持 | 最多 3 层递归，`fileReference@|@layer_path` 复合主键去重 |
| 伪粗体处理 | 放宽收敛阈值 + 扩展 REFINE 迭代 |
| 单英文字符跳过 | 装饰性字符自动跳过，中文单字不受影响 |
| SO 边界扩展 | 按字号变化率动态扩边 |
| 字体名容错 | 空格标准化回退搜索 |
| 字重自动匹配 | 无需用户指定字重 |
| 完整迭代日志 | 每层每次迭代详细记录，前端可直接展示 |

## 6. 不改变的内容

- MediaTools 的 CLI 参数解析结构
- MediaTools 的 `PhotoshopConnector` 类
- MediaTools 的 PS 连接/断开生命周期
- MediaTools 的输出目录管理
- MediaTools 前端对接的接口签名（`ModifyResult` 兼容）
