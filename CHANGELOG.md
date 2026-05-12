# CHANGELOG

所有重要变更将记录在此文件中。

---

## [未发布]

## [1.5.2] - 2026-05-13

### "保一条"安全策略
- 各阶段早退时追加一次额外迭代再跳转，避免边界震荡导致假收敛
- Phase 1/2/3 及 REFINE 全部覆盖，剧组"保一条"思路落地

### PSA-MediaTools 适配器
- 新增 `psa_mediatools_adapter/` 包，4 个公开函数（scan/apply/run/verify-font）
- `_bridge.py` 桥接 PhotoshopConnector ↔ PSA raw COM
- 自动跳过无变更图层和装饰性单英文字符
- 不指定字重时自动匹配最接近字重
- 输出结果 JSON 可直接供前端进行前后对比展示

### 三阶段魔鬼测试
- Stage 1：西班牙语 + 逐行镜像反转（无字体变更），20/20 收敛
- Stage 2：西班牙语 + 镜像 + Noto Sans → CapCut Sans Display（无指定字重），21/21 收敛
- Stage 3：西班牙语 + 镜像 + 全部字体随机 → Segoe UI（魔鬼测试），21/21 收敛

### 代码变更
- `psa_lab.py`：保一条策略（4 个阶段）
- `psa_applier.py`：REFINE 保一条 + 字重空匹配修复
- `psa_logger.py`：新增 `log_path` 属性
- `psa_mediatools_adapter/`：新包（577 行）

## [1.5.1] - 2026-05-12

### 迭代策略：激进早退
- 各阶段从固定轮次改为"最多 N 轮 + 早退"模式
- Phase 1 字号二分：最多 10 轮，搜索区间 < 2pt 或高度差 < 4% 时早退
- Phase 2 精确收敛：最多 5 轮，达到自适应阈值时早退（已有逻辑保留）
- Phase 3 字间距：最多 5 轮，宽度差 < 5px 时早退（已有逻辑保留）
- REFINE 渲染校验：伪粗体最多 5 轮（阈值 4px），普通图层最多 3 轮（阈值 2px）
- 测量次数大幅减少，实际运行速度提升约 30-40%

### 嵌套 SO 深度上限
- Scanner 和 Applier 均限制最多进入 3 层嵌套 SO
- 超过深度直接跳过并记录日志

### 跳过装饰性单英文字符
- 仅含单个 ASCII 字母的图层（如 T、X）自动跳过，不执行修改
- 中文单字不受影响（具有语义意义）

### 代码变更
- `psa_lab.py`：Phase 1/2/3 迭代策略调整
- `psa_applier.py`：装饰字符检测 + 深度上限 + REFINE 策略
- `psa_scanner.py`：SO 深度上限

## [1.5.0] - 2026-05-12

### 自适应收敛阈值
- Phase 2 收敛阈值不再硬编码 1px，改为按目标高度动态缩放 `max(1.0, target_h * 0.005)`
- 伪粗体图层使用加倍阈值 `max(2.0, target_h * 0.01)`
- 最终收敛判定同步使用自适应阈值

### 伪粗体（FauxBold）特殊处理
- REFINE 最大迭代次数：伪粗体 8 次，普通图层 5 次
- REFINE 收敛阈值：伪粗体 4px，普通 2px
- 最终收敛阈值：伪粗体 6px，普通 3px
- 解决伪粗体图层字体变更后边界框震荡导致的假阴性

### 二级嵌套智能对象支持
- `TextLayerRecord` 新增 `so_chain` 字段，记录从外层到内层的 SO 嵌套链
- Scanner 递归进入 SO 时自动构建 `so_chain`
- Applier 新增 `_process_so_level()` 递归函数，按深度逐层进入 SO
- 向后兼容旧版工单（空 `so_chain` 视为单层 SO）

### 自适应 SO 边界扩展
- `expand_so_canvas()` 支持动态 scale 参数（原硬编码 1.2x）
- 扩边比例按字号变化率计算：`max(1.2, size_ratio * 1.1)`，上限 3.0x
- 日志输出扩边百分比、scale、size_ratio 三个指标

### 字体匹配增强
- `resolve_font()` 增加去空格回退搜索（如 "NotoSans" → "Noto Sans"）

### 自动行距优化
- `find_adapted_params()` 对 `auto_leading=True` 的多行文案跳过 leading 调整
- 传入 lab 的初始 leading 值使用原始记录的 `leading_pt`

### 代码变更
- `psa_models.py`: +3 行（`so_chain` 字段）
- `psa_lab.py`: +13/-3 行（自适应阈值 + auto_leading 优化）
- `psa_scanner.py`: +13/-1 行（`so_chain` 追踪）
- `psa_applier.py`: +182/-59 行（嵌套 SO + 伪粗体 + 自适应扩边）
- `psa_utils.py`: +19/-3 行（动态 scale 参数）

## [1.4.0] - 2026-05-12

### 重构自适应算法 Phase 2 和 Phase 3

**Phase 2（精确收敛）**
- 单行文案新增独立分支：使用字号微调二分法（±5%，7次二分 × 5轮）
- 多行文案保持原有 leading+size 交替调整
- 收敛判定阈值 1px

**Phase 3（字间距自适应）**
- 实现完整的 5 次迭代 tracking 二分法调整（[-50, +50] 范围，7次二分）
- tracking 范围限制：-100 ~ 200
- 宽度差 < 5px 提前退出
- 宽度差 > 10px 时 fallback：恢复 tracking，缩小字号 5%
- 边界保护：多行文案中字号缩小若影响 leading > 2px，停止 tracking 调整
- 记录最佳 tracking 值并追踪是否因 leading 保护而放弃

**其他改进**
- 记录每次迭代的详细日志（iter/prec/micro），包含尝试值和结果值

### 代码变更
- `psa_lab.py`: +103/-27 行，Phase 2/3 完整重构

---

## [1.3.0] - 2026-05-12

### 新增 A+B Scale Calibration

**Method A: Scale Calibration（校准）**
- 进入自适应算法前，在 Lab 中用原文案+原字号测量一次高度
- 计算图层变换缩放系数 `scale = real_bounds_h / lab_orig_h`
- 调整自适应目标高度 `target_h_lab = real_bounds_h / scale`
- 确保有自由变换的图层能正确收敛

**Method B: REFINE（真实渲染验证）**
- 自适应写回后，读取真实图层的实际渲染高度
- 偏差 ≥ 2px 时进入 REFINE 阶段（最多 5 轮）
- 按比例调整字号+行间距，直到偏差 < 2px
- 最终收敛阈值 < 3px（考虑 COM API 精度损失）

### 重构 `_process_layer()`
- 统一直接层和 SO 层的处理逻辑，消除重复代码
- 通过 `in_so` 参数切换定位方式（by ID / by path）
- 新增 `measure_text()` 工具方法，单次高度测量后清理

### 代码变更
- `psa_applier.py`: +161/-106 行
- `psa_lab.py`: +129/-121 行

---

## [1.2.0] - 2026-05-12

### 新增字间距自适应（Tracking Adaptation）
- Phase 3: 5 次迭代调整 tracking 使新文案宽度接近原始宽度
- 集成到 `find_adapted_params()` 的 leading refinement 之后
- 宽度调整失败时恢复原 tracking 并缩小字号

### 新增智能对象边界防护（SO Boundary Protection）
- 所有 SO 内图层修改完成后，画布扩大 120%（居中扩展）
- 防止修改后的文案被 SO 边界切割
- 通过 ExtendScript `resizeCanvas()` 实现

### 新增工具
- `debug_mirror.py`: 镜像文案生成调试工具（每行独立倒序，保留空格和连字符）

### 其他改进
- 新增 `SOEnterError` 异常类
- `psa_utils.py` 添加 `expand_so_canvas()` 和对应的 ExtendScript

### 测试结果
- 20 层处理：19 OK + 1 WARNING（5px 偏差），成功率 95%
- 14 层成功应用 tracking 调整（-50 ~ +120）
- 17 个 SO 层全部扩边成功

### 代码变更
- `psa_lab.py`: +119/-13 行
- `psa_applier.py`: +9 行
- `psa_utils.py`: +24 行
- 新增 `debug_mirror.py` (118 行)
- 新增 `DEBUG_REPORT_20260512.md` (179 行)

---

## [1.1.0] - 2026-05-12

### 修复 SO 图层写入
- SO 图层能正确应用并保存属性
- 修复写入权限问题

### 新增 PSB 去重验证
- 通过 ActionDescriptor 查询 SO 的 `fileReference` 字段
- 同一 PSB 被多个 SO 引用时只处理一次

### 其他改进
- `psa_logger.py` 优化日志格式

### 代码变更
- `psa_applier.py`: +99/-64 行
- `psa_logger.py`: +5/-3 行

---

## [1.0.0] - 2026-05-12

### Initial Release
- 基于 Python + win32com 的 Photoshop 文字图层批量自动化工具
- **扫描阶段**: 递归遍历所有图层（含智能对象），输出 JSON 工单
- **工单驱动**: 用户编辑 JSON 指定修改内容（enabled/text/font/weight）
- **应用阶段**: 创建副本（_auto.psd），自适应算法，写回属性
- **自适应算法**: 2 阶段 15 次迭代（Phase 1: 二分法收敛字号，Phase 2: leading+size 精确调整）
- **空白实验室**: 隔离测试环境，避免污染真实文档
- **字体系统**: 从 `app.Fonts` 构建索引，按 PostScript 名后缀匹配字重
- **SO 支持**: 通过 ExtendScript 进入智能对象，按 PSB 分组处理，分辨率隔离
- **日志系统**: 每次运行生成带时间戳的 `.log` 文件

### 项目结构
- `psa.py` - CLI 入口
- `psa_models.py` - 数据模型
- `psa_utils.py` - COM 底层工具
- `psa_fonts.py` - 字体系统
- `psa_logger.py` - 日志
- `psa_scanner.py` - 扫描
- `psa_lab.py` - 实验室 + 自适应算法
- `psa_applier.py` - 工单应用

[未发布]: https://github.com/anomalyco/psa/compare/v1.4.0...HEAD
[1.4.0]: https://github.com/anomalyco/psa/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/anomalyco/psa/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/anomalyco/psa/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/anomalyco/psa/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/anomalyco/psa/releases/tag/v1.0.0
