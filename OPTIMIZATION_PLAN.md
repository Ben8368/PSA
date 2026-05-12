# 字间距自适应优化方案

## 问题分析

### 当前现象
- 修改后的文案比原始文案小了一点
- 目标：修改完之后的大小应该是原始大小的 **1.1 倍**（即稍微放大 10%）

### 根本原因

当前的 20 次迭代流程：
1. **Phase 1（10 次）**：二分法调整字号，使高度接近目标
2. **Phase 2（5 次）**：精确调整 leading，进一步优化高度
3. **Phase 3（5 次）**：调整 tracking，使宽度接近原始宽度
4. **REFINE（5 次）**：在真实 PSD 中验证并微调

**问题所在**：
- Phase 3 的 tracking 调整是为了让新文案的**宽度**接近原始宽度
- 但这导致字号被压缩（因为 tracking 调整无法完全补偿字体变化）
- 最终 REFINE 阶段又进一步缩小了字号以匹配高度
- 结果：文案整体变小

---

## 优化方案

### 方案核心思路

**目标**：修改后的文案大小 = 原始大小 × 1.1（放大 10%）

**实现方式**：在 Phase 1 的二分法中，不是以原始高度为目标，而是以 **原始高度 × 1.1** 为目标

### 详细调整步骤

#### 1. 修改 `find_adapted_params()` 中的目标高度计算

**当前逻辑**：
```python
target_h = target_h_override if target_h_override is not None else record.bounds_h_px
```

**新逻辑**：
```python
# 基础目标高度
base_target_h = target_h_override if target_h_override is not None else record.bounds_h_px

# 应用 1.1 倍放大系数（可配置）
SIZE_MULTIPLIER = 1.1  # 修改后的文案应该是原始大小的 1.1 倍
target_h = base_target_h * SIZE_MULTIPLIER
```

#### 2. 调整 Phase 3（Tracking Adaptation）的宽度目标

**当前逻辑**：
```python
# 目标是让新文案宽度接近原始宽度
if width_ratio > 1.05:  # 新文案太宽
    current_tracking = current_tracking - 20
elif width_ratio < 0.95:  # 新文案太窄
    current_tracking = current_tracking + 20
```

**新逻辑**：
```python
# 目标是让新文案宽度接近原始宽度的 1.1 倍
# 因为字号已经放大了 1.1 倍，宽度也应该相应放大
target_width_ratio = 1.1  # 新文案宽度应该是原始的 1.1 倍

if width_ratio > target_width_ratio * 1.05:  # 新文案太宽
    current_tracking = current_tracking - 20
elif width_ratio < target_width_ratio * 0.95:  # 新文案太窄
    current_tracking = current_tracking + 20
```

#### 3. 调整 REFINE 阶段的收敛阈值

**当前逻辑**：
```python
converged = abs(final_h - target_h) < 2.0  # 严格要求 <2px
```

**新逻辑**：
```python
# 允许更宽松的收敛范围，因为目标已经是 1.1 倍
# 目标高度 = 原始高度 × 1.1，允许 ±5% 的偏差
tolerance_px = base_target_h * 0.05  # 原始高度的 5%
converged = abs(final_h - target_h) < tolerance_px
```

---

## 实现细节

### 修改 1：在 `psa_models.py` 中添加配置参数

```python
@dataclass
class AdaptedParams:
    # ... 现有字段 ...
    size_multiplier: float = 1.1  # 修改后文案相对原始大小的倍数
    target_h_px: float  # 原始目标高度
    adjusted_target_h_px: float  # 应用倍数后的目标高度
```

### 修改 2：在 `psa_lab.py` 中调整算法

```python
def find_adapted_params(
    self,
    record: TextLayerRecord,
    new_font_ps: str,
    new_text: str,
    logger=None,
    target_h_override: float | None = None,
    size_multiplier: float = 1.1,  # 新参数
) -> AdaptedParams:
    # ...
    
    # 计算目标高度
    base_target_h = target_h_override if target_h_override is not None else record.bounds_h_px
    target_h = base_target_h * size_multiplier
    
    # Phase 1: 二分法（目标是 target_h = base_target_h × 1.1）
    # ... 保持不变 ...
    
    # Phase 3: Tracking 调整（目标宽度也应该是 1.1 倍）
    try:
        orig_w = self.measure_text_width(...)
        target_width = orig_w * size_multiplier  # 新增：宽度目标也是 1.1 倍
        
        for track_iter in range(1, 6):
            # ...
            if orig_w > 1.0:
                width_ratio = new_w / orig_w
                target_ratio = size_multiplier  # 1.1
                
                if width_ratio > target_ratio * 1.05:
                    current_tracking = current_tracking - 20
                elif width_ratio < target_ratio * 0.95:
                    current_tracking = current_tracking + 20
```

### 修改 3：在 `psa_applier.py` 中传递参数

```python
params = lab.find_adapted_params(
    record, new_font_ps, new_text, logger,
    target_h_override=target_h_lab,
    size_multiplier=1.1,  # 新参数
)
```

---

## 预期效果

| 指标 | 当前 | 优化后 |
|------|------|--------|
| 修改后文案大小 | 原始 × 0.95 | 原始 × 1.1 |
| 高度偏差 | <2px | <5% |
| 宽度偏差 | <5px | <5% |
| 视觉效果 | 偏小 | 适中放大 |

---

## 可配置参数

### 全局配置（建议在 `psa_lab.py` 中定义）

```python
# 字间距自适应配置
TRACKING_ADAPTATION_CONFIG = {
    "size_multiplier": 1.1,           # 修改后文案相对原始大小的倍数
    "width_tolerance": 0.05,          # 宽度偏差容限（5%）
    "height_tolerance_ratio": 0.05,   # 高度偏差容限（原始高度的 5%）
    "tracking_step": 20,              # 每次 tracking 调整的步长
    "tracking_min": -100,             # tracking 最小值
    "tracking_max": 200,              # tracking 最大值
    "refine_iterations": 5,           # REFINE 迭代次数
}
```

### 工作单级别配置（可选）

在 `TextLayerRecord` 中添加可选字段：

```python
@dataclass
class TextLayerRecord:
    # ... 现有字段 ...
    size_multiplier: float | None = None  # 可选：该层的自定义倍数
```

---

## 实现优先级

### 第一阶段（必须）
1. 修改 Phase 1 的目标高度计算（×1.1）
2. 修改 Phase 3 的宽度目标（×1.1）
3. 调整 REFINE 的收敛阈值

### 第二阶段（推荐）
1. 添加全局配置参数
2. 支持工作单级别的自定义倍数
3. 添加日志记录倍数信息

### 第三阶段（可选）
1. 支持动态倍数计算（基于字体变化幅度）
2. 支持不同层的不同倍数
3. 添加 UI 配置界面

---

## 风险评估

| 风险 | 概率 | 影响 | 缓解方案 |
|------|------|------|---------|
| 文案过大超出边界 | 低 | 中 | 已有 120% SO 边界防护 |
| 字间距调整不足 | 中 | 低 | 增加 tracking 步长或迭代次数 |
| 伪粗体层仍未收敛 | 中 | 低 | 增加 REFINE 迭代或特殊处理 |
| 多行文案行距不均 | 低 | 低 | 调整 leading 倍数 |

---

## 建议实施步骤

1. **第一步**：修改 `find_adapted_params()` 中的目标高度计算
2. **第二步**：修改 Phase 3 的宽度目标计算
3. **第三步**：调整 REFINE 的收敛阈值
4. **第四步**：运行 debug 测试，验证效果
5. **第五步**：根据测试结果微调倍数（可能需要 1.05 或 1.15）
6. **第六步**：添加配置参数，支持灵活调整

---

## 预期测试结果

运行相同的 debug 测试后，预期：
- 文案大小：原始 × 1.1（±5%）
- 高度偏差：<5% 或 <5px
- 宽度偏差：<5% 或 <5px
- 成功率：≥95%
- Seedance 层：可能收敛（因为字号更大，边界框更稳定）
