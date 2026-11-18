# Provenance of `src/lab8/` — lấy từ repo gốc VinUni, không phải bài Lab 8 của nhóm

Rubric Lab 9 trừ 10 điểm nếu `src/lab8/` bị sửa, nên phải chứng minh được nguồn gốc bằng diff, không bằng
lời khai. Đây là cách kiểm tra lại.

## Nguồn

| | |
|---|---|
| Repo gốc (theo README Lab 9) | `VinUni-AI20k/K5-Day8-FromWorkflows-to-Agents` |
| Commit gốc dùng làm chuẩn | **`e1ac1f9`** — "Update : Team.md", commit cuối **trước** khi học viên bắt đầu sửa `src/` |
| Repo nhóm (Day 8) | `PH31M/K5-L3B-DAY08-MV-FromWorkflowsToAgents` — giữ nguyên lịch sử của repo gốc, nên `e1ac1f9` truy được từ đó |
| Cách lấy | `git archive e1ac1f9 src \| tar -x -C <pristine>` rồi `cp -R <pristine>/src/. src/` |

Commit `e1ac1f9` là mốc đúng vì lịch sử của fork cho thấy commit **học viên** đầu tiên là `22b5163`
("feat(shapes): implement workflow (A) and single ReAct (B)") nằm ngay sau `e1ac1f9`; mọi commit trước đó
là của giảng viên/TA (`ivo-gilles`, `loversky02`, `haidm203`).

## Kiểm tra

```bash
# dựng lại bản gốc từ lịch sử của repo Day 8 (không cần mạng)
git -C <repo-day8> archive e1ac1f9 src | tar -x -C /tmp/pristine
diff -rq /tmp/pristine/src/lab8 src/lab8        # chỉ được thấy __pycache__
```

Kết quả trên bản nộp này: `src/lab8/` **giống byte-for-byte** bản gốc (khác biệt duy nhất là `__pycache__`,
không tracked). Toàn bộ `src/` chỉ khác bản gốc ở:

| File | Vì sao khác |
|---|---|
| `src/harness_map.yaml` | **Yêu cầu của Lab 9**: thêm section `eval` (mẫu `src/harness_map.eval.yaml`) và bump `harness_map_version` 1.1 → 1.2. Chỉ thêm, không sửa section cũ. |
| `src/lab9/`, `src/data/eval/`, `src/config/metric_spec*.yaml`, `config/fm_map.yaml`, `src/tests/test_lab9_*.py`, `src/requirements-lab9.txt` | File của Lab 9 (đã có trong starter hoặc do bài làm sinh ra) |
| `src/reports/*.json` | Report do script sinh (`lab9.eval`, `lab9.traps`), commit bằng `git add -f` |

## Những gì đã bị loại bỏ khỏi bản copy ban đầu

Lần copy đầu tiên lấy từ repo **nhóm**, nên mang theo bài làm Day 8. Đã kiểm tra và loại:

| Đã xoá | Vì sao |
|---|---|
| `src/bonus/` (6 file) | Bonus B3/B7 của nhóm — không thuộc phạm vi Lab 9 |
| `src/tests/test_{workflow,single,orchestrator}_extra.py`, `test_bonus_*.py` | Test của nhóm viết cho shape của nhóm, không phải test của Lab 9 |
| `src/lab8/shapes/{workflow,single,orchestrator}.py` | Nhóm đã **implement** 3 shape này (Lab 8). Đã **khôi phục bản gốc** (stub + docstring của giảng viên) để `src/lab8/` không còn dấu vết sửa đổi. |
| `src/student_drop/` | Hidden pack của buổi trợ giảng Day 8; `.gitignore` đã chặn nhưng bỏ hẳn cho chắc |
| `src/reports/{benchmark,bonus_b3,bonus_grader_audit,crash,hidden_selfcheck}.json` | Report của Day 8, không phải của Lab 9 |

`src/lab8/shapes/swarm_reference.py` **chưa bao giờ** bị nhóm sửa (diff rỗng ngay từ đầu), nên các số của
Lab 9 không phụ thuộc vào việc khôi phục này — chạy lại toàn bộ M0–M7 sau khi khôi phục cho ra **đúng
cùng kết quả**:

- `eval set 045b664cb0bb` · baseline `E-swarm-20261118-045b`: pass_rate 0.9857, pass_5 0.9286, reply_ledger_match 1.0
- `fixed` → exit 0; `seeded_regression` → exit 1, `pass_rate` Δ −0.271, CI [−0.500, −0.057]
- `eval set 958566fbfbad` · baseline `E-swarm-20261118-9585`: pass_hat_5 0.8929 · mutation **3/3, 0 báo nhầm** · traps **4/4 blocked**
