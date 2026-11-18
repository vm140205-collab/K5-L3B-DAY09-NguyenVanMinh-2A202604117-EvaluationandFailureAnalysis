# Judge audit

Chạy:

```bash
cd src
python -m lab9.judge --csv data/eval/judge_tone_public.csv    --audit 5    # exit 0
python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 5    # exit 1
```

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** (tp 24 / fp 4 / fn 6 / tn 66) | dùng được — nhưng chỉ cho tone, và chỉ sau khi sửa rubric (bảng dưới) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không đạt** (tp 9 / fp 0 / fn 21 / tn 70) | **loại** — không được dùng làm gate |

Tỉ lệ lỗi sau hiệu chỉnh Rogan-Gladen (dùng P/R ở trên): tone 0.28 → 0.30; helpful 0.09 → 0.30.
Con số 0.30 của helpful đáng tin hơn 0.09 rất nhiều, nhưng recall 0.30 nghĩa là judge bỏ sót 3/4 lỗi —
hiệu chỉnh tỉ lệ không cứu được một judge bỏ sót.

## Vì sao `helpful` bị loại (dẫn ma trận nhầm lẫn)

`helpful` có precision 1.0 (không bao giờ báo lỗi sai) nhưng recall 0.3: **21/30 lỗi thật bị chấm PASS**.
Nhìn 21 case bị bỏ sót thì chúng không phải lỗi văn phong — chúng là lỗi **số tiền**:

- `HL-015` "đã hoàn 55.000đ" trong khi ledger ghi 40.000đ
- `HL-020` "đã hoàn 90.000đ" trong khi ledger ghi 120.000đ
- `HL-043` "đã hoàn 35.000đ" trong khi ledger ghi 20.000đ
- 3 case `HL-047/091/097` "Ok bạn, đơn … xử lý rồi nhé." (sai xưng hô, không có thông tin)
- `HL-016/028/035/041/053/058/062/070/072/074/087/090/096/098/100` cùng dạng sai tiền

Judge chỉ đọc câu trả lời; câu trả lời **không chứa ledger**, nên "helpful" ở đây thực chất là "câu này
đọc có vẻ hữu ích", không phải "câu này đúng". Một judge như vậy đứng sau một gate sẽ xanh đúng vào lúc
agent báo sai số tiền — tức là đúng loại lỗi FM-08 mà ta cần chặn. Vì vậy:

1. `helpful` **không** vào `metric_spec.yaml`; FM-08 được chấm bằng **code** (`reply_ledger_match`, đọc
   ledger trước rồi so với event `reply`).
2. Judge chỉ được dùng cho tiêu chí đã qua FLOORS và **không** phụ thuộc dữ liệu ngoài câu trả lời.

## ≥5 case audit thủ công

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / hành động sửa rubric |
|---|---|---|---|---|---|
| 1 | `H-081` "Dạ, đơn O-107 chưa đủ điều kiện hoàn theo chính sách hiện hành ạ." | FAIL | PASS | **Judge đúng, nhãn người sai** | Đọc nhầm ticket. Sửa nhãn → nếu sửa, ma trận tone còn 9 lỗi (fp 4 / fn 5), κ tăng. Ghi vào changelog nhãn v2. |
| 2 | `H-042` "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | **Người đúng** | Judge phạt vì "thiếu xin lỗi". Rubric tone **bỏ yêu cầu xin lỗi**; tone = xưng hô + không suồng sã + không hứa quá kết quả, không đo độ dài/độ ngọt. |
| 3 | `H-063` "Dạ, LogiX đã hoàn 20.000đ và sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | **Người đúng** | Hứa ngoài kết quả hệ thống. Thêm mục rubric: "hứa thêm tiền/hành động ngoài ledger = FAIL" và đưa vào prompt của judge. |
| 4 | `H-070` "Dạ, LogiX đã hoàn 90.000đ cho đơn O-909 ạ 😂😂" | PASS | FAIL | **Người đúng** | Emoji trong ngữ cảnh khiếu nại. Thêm luật "emoji/teencode trong reply khách hàng = FAIL". |
| 5 | `H-017` "Dạ, bạn ơi LogiX đã hoàn 25.000đ cho đơn O-606 rồi nha." | PASS | FAIL | **Người đúng** | Xưng "bạn"/"nha" với khách lớn tuổi. Rubric phải nêu rõ cặp xưng hô bắt buộc (`anh/chị` hoặc `quý khách`); judge coi "thân thiện" là tốt nên cần luật cứng. |
| 6 | `H-051` "Dạ, LogiX đã refund 90.000đ cho đơn O-202 ạ." | FAIL | PASS | **Người đúng (CS LogiX cho phép "refund")** | Judge phạt từ tiếng Anh. Sửa rubric: whitelist "refund"/"hoàn tiền", chỉ phạt khi *cả câu* là tiếng Anh hoặc mất dấu (`H-094`). |
| 7 | `H-088` "Dạ, dạ, LogiX đã hoàn 40.000đ cho đơn O-233 ạ." | FAIL | PASS | **Người đúng** | Lỗi gõ lặp "Dạ", không phải lỗi tone. Rubric: lỗi chính tả nhỏ không tính FAIL (khác `H-094` mất dấu cả câu). |
| 8 | `HL-043` "… LogiX đã hoàn 35.000đ cho đơn O-202 …" (ledger 20.000đ) | PASS | FAIL | **Người đúng** | Đúng loại lỗi judge **không thể** thấy: cần ledger. Không sửa rubric — chuyển sang grader code, và ghi vào `helpful` là "không dùng được cho tiền". |

## Kết luận

- **Loại `helpful`.** κ=0.375 < 0.6 và recall=0.3 < 0.7. Nó bỏ sót toàn bộ nhóm lỗi tiền — nhóm lỗi quan
  trọng nhất của sản phẩm — nên không được là gate, dù precision 1.0 trông đẹp.
- **`tone` dùng được nhưng phải sửa rubric trước**, và chỉ cho tone. 4/8 bất đồng là nhãn người sai/hết hạn
  (H-081, H-042, H-051, H-088) và 3 là judge thiếu luật (H-063, H-070, H-017): sau khi sửa rubric, tone được
  calib lại trên tập nhãn v2 trước khi bật thành gate (hiện tone **không** blocking trong `metric_spec.yaml`).
- **Rủi ro còn lại:** judge chỉ được kiểm trên CSV replay đã công khai, 100 dòng, nhãn một người chấm. Chưa
  có held-out thật; κ 0.757 với n=100 có CI rộng (~±0.1), nên ngưỡng 0.6 phải xem là "sàn tạm", không phải
  "đã an toàn". Cần nhãn người lần hai trên tập mới trước khi dùng judge cho bất kỳ gate nào khác.
