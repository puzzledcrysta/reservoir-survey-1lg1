# 河道断面测方深度登记

- 规模：中型
- 核心规则：按相邻里程和不规则横断面梯形积分，遇截面从挖转填时按零点分割。
- 使用者与工作流：航道测量员按测段复算来源批次，对照外部记录后提交复核。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 来源采信 | 接收分段记录、定位坏行 | `POST /api/intake` | `app/modules/intake/service.py` | `tests/test_intake.py` |
| M2 字段解释 | 归一主键、版本、时间和原字段 | `POST /api/contract` | `app/modules/contract/service.py` | `tests/test_contract.py` |
| M3 隔离裁决 | 归并重复、隔离争议版本 | `POST /api/quality` | `app/modules/quality/versions.py` | `tests/test_quality.py` |
| M4 断面测方 | 复算业务明细与边界证据 | `POST /api/domain` | `app/modules/domain/rule.py` | `tests/test_domain.py` |
| M5 独立对账 | 核对外部记录并分别计量 | `POST /api/reconcile` | `app/modules/reconcile/service.py` | `tests/test_reconcile.py` |
| M6 批次复算 | 保存运行、查询历史、复算原输入 | `POST /api/runs` | `app/modules/runs/service.py` | `tests/test_runs.py` |
| M7 交付复核 | 复核差异、阻止陈旧提交、导出证据 | `GET /api/export` | `app/modules/review/decisions.py` | `tests/test_review.py` |
| M8 合卷边界 | 重叠里程切分、边界调整单、合卷复核与导出 | `POST /api/merges` | `app/modules/merge/boundary.py` | `tests/test_merge_boundary.py`、`tests/test_merge_flow.py` |

## 陷阱登记

| TRAP | 现象 | 样例 | 处理位置 | 测试 |
|---|---|---|---|---|
| TRAP-02 | BOM | shift.csv | `app/modules/intake/service.py` | `tests/test_intake.py::test_bom` |
| TRAP-03 | 引号内换行 | shift.csv | `app/modules/intake/service.py` | `tests/test_intake.py::test_multiline` |
| TRAP-04 | 重复表头 | shift.csv | `app/modules/intake/service.py` | `tests/test_intake.py::test_repeated` |
| TRAP-05 | 列数不齐 | shift.csv | `app/modules/intake/service.py` | `tests/test_intake.py::test_width` |
| TRAP-07 | 空值哨兵 | shift.csv | `app/modules/contract/service.py` | `tests/test_contract.py::test_missing` |
| TRAP-08 | 主键前导零 | shift.csv | `app/modules/contract/service.py` | `tests/test_contract.py::test_leading_zero` |
| TRAP-11 | 偏移时间归一 | shift.csv | `app/modules/contract/service.py` | `tests/test_contract.py::test_offsets` |
| TRAP-14 | 等版本冲突 | shift.csv | `app/modules/quality/versions.py` | `tests/test_quality.py::test_conflicting` |
| TRAP-18 | 三种空态 | 测试构造输入 | `app/modules/intake/service.py` | `tests/test_intake.py::test_empty_states` |
| TRAP-26 | 陈旧复核 | 测试构造输入 | `app/modules/review/decisions.py` | `tests/test_review.py::test_stale` |
| TRAP-10 | 不对中间断面积分提前舍入 | cases.csv | `app/modules/domain/rule.py` | `tests/test_domain.py::test_fraction` |
| TRAP-30 | 补测重叠里程直接相加重复计量 | 测试构造输入 | `app/modules/merge/boundary.py` | `tests/test_merge_boundary.py::test_overlap_counts_bed_once` |
| TRAP-31 | 同一补测重跑重复累加 | 测试构造输入 | `app/modules/merge/repository.py` | `tests/test_merge_flow.py::test_idempotent_rerun_does_not_accumulate` |
| TRAP-32 | 合卷失败产生半成品 | 测试构造输入 | `app/modules/merge/repository.py` | `tests/test_merge_flow.py::test_closure_failure_rolls_back_no_half_product` |

## 合卷规则（M8）

裁决采用**可追溯的合卷边界**，不推翻各测段原结论重新分配。

1. 取所有测站里程的并集作为切点，相邻切点构成基础区间；区间内面积按两端断面线性内插。
2. 每个基础区间只归属一个权威来源：角色序列为一个基线后接若干补测，`ordinal` 高者（后提交的补测）取得重叠区归属，同批次以业务键、行号兜底保证确定性。因此同一段河床在全卷只计一次。
3. 区间挖方沿用 M4 零点分割规则（`interval_cut`），填方不抵销挖方；里程空档标记 `GAP`，不臆造断面。
4. 原测段行原样保留，调整以 `adjustments` 边界调整单表达：`EFFECTIVE`（原结论有效）、`PARTIAL`（部分里程被取代，其余仍有效）、`REPLACED`（全部被取代），每条去重额带责任批次 `removed_by`。
5. 闭合恒等式：原合计 = 合卷总额 + 重叠去重额；残差非零抛 `MERGE_CLOSURE`，事务回滚，不落任何半成品。
6. 合卷指纹含规则版本、批次序列与角色；同序列重跑命中定版（`reused=true`）不二次累加。合卷复核是独立版本链（`merge_reviews`），与原批次复核互不影响；工作台与 `/api/export/merge/{id}` 读取同一份定版 JSON。

## 对账规则

输入记录数 = 计入 + 隔离 + 去重和替换 + 空白记录 + 重复表头。
业务账按测段全外连接。差异分别标记漏记、外部单边和数值不符，以立方米对差。

## 范围

本地文件与单机复核。单次来源文本限 128 KiB。复合字段单项最多 240 段。
