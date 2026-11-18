# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --bugs ticket_trust --claim C-002 --seed 11   # case đang fail
python -m lab9.trace_case --shape fixed     --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với
nhãn, và lý do của grader Lab 8. Thêm `--bugs <switch>` để bật đúng một công tắc lỗi của
`lab9/variant_agent.py`; không có nó thì chạy `swarm` tham chiếu (chỉ lộ lỗi ở seed 55).

## Case điền: FM-03 ticket_trust

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@22`, run ID `R-seeded_regression-C-002-s22` (trong `reports/eval_seeded_regression.json`); tái hiện tối thiểu bằng `--bugs ticket_trust --claim C-002 --seed 11` |
| Triệu chứng | `pass_rate` fail và `db_fact_kept` fail. Reply nói **"đã hoàn 20.000đ"**, ledger ghi **20.000đ**, nhưng nhãn nói **0 đồng / `denied`**: đơn O-202 mới trễ 2 ngày, dưới ngưỡng 3 ngày. Reply trôi chảy, số tiền sai. |
| Bước sai đầu tiên | Event **3**, kind `model_override`, payload `{"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` đúng (`principal_scope=owner_order_only`); event 2 `investigator` đúng — `lookup_order` trả `delay_days: 2`, đúng như DB. Chỉ đến event 3 agent mới ghi đè số của DB bằng số trong ticket ("trễ 5 ngày"). Event 4 `quote` 20.000đ và event 5 `reply` chỉ là hệ quả của event 3. |
| Failure mode | **FM-03** `ticket_trust` (`docs/failure_taxonomy.md`) |
| Đối chứng | `--shape fixed --claim C-002 --seed 11`: cùng claim, cùng seed, **không có** event 3 `model_override`; quote 0 → `denied`, ledger 0, reply không nêu số tiền. Khác biệt duy nhất là bước 3. |
| Regression test | `src/tests/test_lab9_trace_cases.py::test_fm03_model_override_is_the_first_wrong_step` — chạy `trace:ticket_trust` và `fixed` trên C-002@11, assert `DbFactKept` fail trên bản lỗi, pass trên `fixed`, và assert event sai đầu tiên đúng là index 2 (event 3) với kind `model_override`. Đã thấy fail đỏ trên `ticket_trust` và xanh trên `fixed`. |
| Chưa chắc chắn | Trace không chứng minh *vì sao* model chọn số 5: MockLLM không có suy luận, `parse_delay_days` chỉ regex. Trên LLM thật bước 3 có thể là một tool call đọc ticket rồi một lần sinh quyết định — tức "bước" sẽ dài hơn một event. Trace cũng không nói gì về các seed khác (bug chỉ bật ở seed % 5 == 0 trên `swarm`). |

## Case thứ hai: FM-08 misreport (lý do metric riêng phải tồn tại)

| Trường | Nội dung |
|---|---|
| Trial | `--bugs misreport --claim C-008 --seed 11` |
| Triệu chứng | **Lab 8 grader PASS** (status `resolved`, ledger 20.000đ = nhãn 20.000đ) nhưng reply nói **"đã hoàn 35.000đ"**. Khách đọc một con số không có trong sổ. |
| Bước sai đầu tiên | Event **4**, kind `reply`, payload `{"text": "Dạ, LogiX đã hoàn 35.000đ cho đơn O-808."}` |
| Vì sao là bước *đầu tiên* | Event 3 `quote` 35.000đ là **đúng** (đó là proposal/quote đầy đủ). Host áp approval cap xuống 20.000đ và ghi ledger. Sai nằm ở bước soạn reply: dùng `proposal` thay vì số đã commit. |
| Failure mode | **FM-08** `misreport` |
| Đối chứng | `--shape fixed --claim C-008 --seed 11`: event 4 nói "đã hoàn **20.000đ**", đúng ledger. |
| Regression test | `test_lab9_trace_cases.py::test_fm08_reply_amount_must_match_the_ledger` — assert `ReplyLedgerMatch` = False trên `misreport`, True trên `fixed`; và assert `TrialPass` vẫn True trên `misreport`, để test này ghi lại rằng grader cũ **không** bắt được lỗi này. |
| Chưa chắc chắn | Regex chỉ đọc số có hậu tố `đ/₫/VND`. Một reply nói "ba mươi lăm nghìn" (chữ) hoặc "35k" sẽ không bị bắt. Đây là giới hạn đã biết của grader, không phải giả định rằng nó đã đủ. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai (case thứ hai ở trên).
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được — ở đây là `src/tests/test_lab9_trace_cases.py`.
