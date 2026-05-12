# CHANGELOG

所有重要变更将记录在此文件中。

---

## [未发布]

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
