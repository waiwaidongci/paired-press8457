# 实际验证记录

环境：Linux · Python 3.11 · SQLAlchemy SQLite（测试）/ PostgreSQL 16（运行）· Node 22（仅用于 ES module 语法检查）。

## 自动化测试

```bash
cd backend
python -m pytest tests -q
```

最近一次运行：`10 passed`（2026-11-20）。

| 用例 | 验证点 |
|---|---|
| test_basis_uses_only_earlier_complete_same_paper | 依据只取同纸类、到单更早、读数已可见的订单；异纸类无依据 |
| test_same_instant_competes_for_last_slot_by_source_key | 同刻两单按编号次序抢最后一个名额；同刻互不作为依据 |
| test_same_instant_natural_order_puts_2_before_10 | 编号按自然序（QM-2 在 QM-10 之前），避免字典序把 10 排前 |
| test_unread_order_selected_still_consumes_quota_and_is_excluded_from_means | 读数未齐但被选中：占名额照扣，两套平均都不计；依据不因未齐订单增加 |
| test_threshold_is_strict_and_no_basis_falls_back | 平均改善等于门槛不算超过；无依据走原工艺 |
| test_idempotent_retry_does_not_add_or_use_later_data | 相同幂等键重试不新增、结果与 SHA256 不变、不采用冻结后补录的可见时刻；不同门槛复用同键返回 409 |
| test_snapshot_hides_readings_not_yet_visible_at_freeze | 冻结时刻尚未可见的读数在快照里置为未齐 |
| test_end_to_end_replay_through_http | HTTP 端到端：录入订单、设名额、回放、重试、CSV 导出、列表不返回整份快照 |
| test_viewer_cannot_write_and_anonymous_is_rejected | 观察员不能写、未登录 401 |
| test_invalid_backfill_is_rejected | 已齐读数缺可见时刻、可见早于到单、负数色差均 422 |

## 合成样本验算

`python -m scripts.seed_demo` 在第一个试印研究中写入 12 单，含不同纸类、同刻抢名额与读数后到。以冻结时刻 `2026-11-19T10:00:00Z`、门槛 `0.3` 回放：

- 选中：TRIAL-0002、TRIAL-0006（读数未齐，仍占名额）、TRIAL-0004；白班 3 个名额用尽。
- TRIAL-0005 与 TRIAL-0004 同刻到单但编号靠后，最后一个名额被 0004 拿走，0005 走原工艺；TRIAL-0008 同因名额用尽走原工艺。
- 计入对比 7 单；派单平均 3.0714 ΔE，全走原工艺 3.2857 ΔE，差额 −0.2143 ΔE。

## 未覆盖

- 未在真实 PostgreSQL/Redis 容器里做并发压测；REPEATABLE READ 冻结逻辑按 SQLAlchemy 方言分支实现，SQLite 下为普通事务。
- 未做浏览器端到端测试；前端仅通过 `node --check` 式的 ES module 导入验证语法与导出。
- 原有配对分析（符号翻转置换检验）未改动，本次未新增其测试。
