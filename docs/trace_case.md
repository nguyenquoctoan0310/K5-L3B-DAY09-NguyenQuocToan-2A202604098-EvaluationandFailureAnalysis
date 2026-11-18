# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Mẫu điền (mỗi bạn 1 case, lấy từ trial đang fail trong report)

| Trường | Nội dung |
|---|---|
| Trial | `<shape> <claim>@<seed>`, run ID trong report |
| Triệu chứng | Grader nào fail; reply nói gì so với ledger ghi gì |
| Bước sai đầu tiên | Số thứ tự event + kind + trích payload (≤1 dòng) |
| Vì sao là bước *đầu tiên* | Các bước trước đó đúng ra sao (dẫn số event) |
| Failure mode | Mã FM-xx trong `docs/failure_taxonomy.md` |
| Đối chứng | Cùng claim@seed trên shape `fixed`: bước đó khác thế nào |
| Regression test | Tên test + grader/assert nào bắt được; đã thấy fail trên variant lỗi và pass trên `fixed` chưa |
| Chưa chắc chắn | Điều trace không chứng minh được |

## Case của mình: `swarm C-002@55`

| Trường | Nội dung |
|---|---|
| Trial | `swarm C-002@55` (baseline; run ID sẽ ghi khi sinh `reports/baseline_v1.json` ở M4) |
| Triệu chứng | Grader Lab 8 FAIL `status resolved != denied`. Ledger `refund_vnd=20000, refund_count=1`, nhãn `0 / 0` |
| Bước sai đầu tiên | **Event 3** `model_override {"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` đúng contract, không có fact rò. Event 2 `investigator` đọc đúng DB: O-202 `delay_days=2`, phí ship 20.000. Từ event 3 trở đi, `quote` (event 4) tính trên số 5 ngày nên ra 20.000đ theo SHIP-LATE-03 (≥3 ngày) |
| Failure mode | FM-03 ticket_trust |
| Đối chứng | `fixed C-002@55`: không có event `model_override`; event 3 `quote` trả `no_entitlement`, 0đ, status `denied`, PASS |
| Regression test | Item `E-002` trong eval set v1 (`failure_modes: FM-01, FM-03`). Grader `DbFactKept` (fail khi có event `model_override`) và `RefundAmountCorrect` (ledger 20.000 ≠ 0) bắt được. `fixed` 0/5 seed fail; `seeded_regression` (bật `ticket_trust`) fail 5/5 seed |
| Chưa chắc chắn | Lỗi chỉ xảy ra khi `seed % 5 == 0` trong `swarm_reference`. Với MockLLM điều này tất định, còn với LLM thật thì tần suất sẽ khác và cần đo lại. Trace không cho biết *vì sao* model chọn tin ticket |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
