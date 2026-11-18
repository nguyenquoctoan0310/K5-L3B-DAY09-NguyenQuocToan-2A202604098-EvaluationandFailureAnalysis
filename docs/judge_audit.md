# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (backend replay, nhãn người là chuẩn đối chiếu, FAIL là lớp dương).

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** (TP 24 · FP 4 · FN 6 · TN 66) | **dùng**, chỉ cho tone, không blocking cho tiền |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không đạt** κ và R (TP 9 · FP 0 · FN 21 · TN 70) | **loại** |

Tỉ lệ lỗi sau hiệu chỉnh Rogan-Gladen:
- tone: quan sát được 0.28, hiệu chỉnh thành **0.30** (sens 0.8, spec 66/70 = 0.943). Hai con số gần nhau vì judge ít sai.
- helpful: quan sát được 0.09, hiệu chỉnh thành **0.30**. Judge báo số lỗi chỉ bằng **một phần ba** số lỗi thật. Hiệu chỉnh kéo được con số về đúng 0.30, nhưng chỉ vì ta có sẵn nhãn người để tính sens. Với recall 0.3, mỗi FN lệch đi sẽ làm số hiệu chỉnh dao động mạnh, nên không dùng được làm gate.

## Audit thủ công các ca bất đồng

### tone_ok: toàn bộ 10 ca
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | Người | Xưng "em", dùng "nha" là quá suồng sã với khách khiếu nại. Rubric thêm: *xưng hô phải là "LogiX" và "anh/chị"; không dùng em/bạn/nha* |
| 2 | H-017 "bạn ơi … rồi nha" | PASS | FAIL | Người | Cùng lỗi xưng hô như #1. Judge nhầm "thân thiện" với "đúng mực". Thêm ví dụ FAIL có "bạn ơi" vào few-shot |
| 3 | H-029 "vui lòng chờ … không cần nhắn thêm" | PASS | FAIL | Người | Judge bị đánh lừa bởi các từ lịch sự bề mặt ("Dạ, vui lòng"). Rubric thêm: *câu ra lệnh hoặc chặn khách liên hệ là FAIL dù có kính ngữ* |
| 4 | H-042 "đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Judge phạt vì "thiếu xin lỗi". Rubric ghi rõ: *xin lỗi không bắt buộc; ngắn, đủ ý vẫn PASS*. Đây là thiên lệch "càng dài, càng xin lỗi càng tốt" |
| 5 | H-051 "LogiX đã refund 90.000đ" | FAIL | PASS | Người | Style guide CS cho phép từ "refund". Đưa danh sách từ mượn được phép vào rubric |
| 6 | H-063 "…và sẽ hoàn thêm cho anh/chị ạ" | PASS | FAIL | Người | Hứa hẹn ngoài kết quả hệ thống. Đây là lỗi **nội dung**, không phải tone, nên tách ra grader code (so lời hứa với ledger, cùng họ với FM-08). Tone judge không phải chịu trách nhiệm ca này |
| 7 | H-070 "…ạ 😂😂" | PASS | FAIL | Người | Rubric thêm: *không dùng emoji trong ngữ cảnh khiếu nại*. Có thể bắt bằng regex trước khi gọi judge (rẻ hơn) |
| 8 | H-081 "đơn O-107 chưa đủ điều kiện hoàn…" | FAIL | PASS | **Judge** | Ghi chú của người gán nhãn: "nhãn người sai (đọc nhầm ticket)". **Sửa nhãn người** về đúng; sau khi sửa, FP còn 3 và precision tăng lên ~0.889 |
| 9 | H-088 "Dạ, dạ, LogiX đã hoàn…" | FAIL | PASS | Hai bên đều có lý | Lỗi gõ lặp từ. Rubric phải chọn rõ một hướng: *lỗi chính tả nhỏ, không đổi nghĩa → PASS* (theo người). Thêm ví dụ vào few-shot |
| 10 | H-094 "Da, LogiX da hoan … xin loi…" | PASS | FAIL | Người | Mất dấu tiếng Việt (dịch máy). Rubric thêm: *thiếu dấu → FAIL*. Có thể kiểm bằng code (tỉ lệ ký tự có dấu) |

### helpful: 21 ca bất đồng, tất cả đều là judge PASS, người FAIL (FN), gom 3 nhóm
| # | Case (đại diện) | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa |
|---|---|---|---|---|---|
| 11 | HL-015 "đã hoàn 55.000đ cho đơn O-112" (ledger 40.000) | PASS | FAIL | Người | **FM-08 misreport.** Judge chỉ đọc reply, không thấy ledger, nên câu trơn tru có số cụ thể trông "helpful". 18/21 ca rơi vào nhóm này (HL-015, 016, 020, 028, 035, 041, 043, 053, 058, 062, 070, 072, 074, 087, 090, 096, 098, 100). **Không sửa rubric được**, phải chuyển sang grader code đọc `snapshot.refund_vnd` |
| 12 | HL-016 / HL-028 / HL-072: hai câu xin lỗi dài kẹp số tiền sai | PASS | FAIL | Người | Thiên lệch độ dài/lịch sự: reply càng dài, càng xin lỗi nhiều thì judge càng chấm PASS. Rubric thêm: *độ dài và lời xin lỗi không cộng điểm helpful* |
| 13 | HL-047 / HL-091 / HL-097 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | Người | Không nói kết quả (hoàn bao nhiêu, hay bị từ chối). Rubric thêm: *reply phải nêu trạng thái cuối và số tiền (nếu có)*. Phần này kiểm được bằng code |

## Kết luận
- **tone_ok dùng được**, nhưng chỉ làm metric không blocking cho văn phong. Ma trận nhầm lẫn TP 24 · FP 4 · FN 6 · TN 66, κ 0.757. Sau khi sửa nhãn H-081, FP còn 3. 5/6 FN có chung kiểu lỗi (xưng hô, ra lệnh, emoji, mất dấu), sửa được bằng rubric và few-shot; một phần (emoji, mất dấu) nên chuyển sang regex vì rẻ hơn.
- **helpful bị loại, không được làm gate.** Recall 0.30 nghĩa là judge **bỏ sót 21/30 reply tệ**. Precision 1.0 dễ gây hiểu lầm: judge chỉ bắt các câu rỗng hiển nhiên ("Cảm ơn bạn đã liên hệ…"), mà những câu đó code cũng bắt được. κ 0.375 thấp hơn nhiều so với sàn 0.6. Nguyên nhân gốc: **18/21 FN là số tiền trong reply khác ledger**, một thông tin judge không có trong input. Vì vậy, đúng quy tắc của bài, *tiền và approval luôn chấm bằng code*: phần "helpful về số tiền" giao cho metric FM-08 ở M3.
- Nếu dùng helpful làm gate, một bản agent nói sai số tiền (FM-08) vẫn sẽ có tỉ lệ helpful cao, và gate sẽ cho merge.
- **Rủi ro còn lại:** judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng mỗi tiêu chí) và rubric được sửa dựa trên chính các ca này. Cần một tập nhãn người mới làm held-out thật trước khi tin các con số sau khi sửa rubric. Ngoài ra, chỉ có một người gán nhãn (H-081 cho thấy người cũng sai), nên cần ≥2 người gán và đo κ giữa người với người để biết trần đồng thuận.
