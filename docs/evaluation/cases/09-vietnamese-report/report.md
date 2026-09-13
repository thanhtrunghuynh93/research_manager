# Tuần 14–20 tháng 9 — Chuẩn hoá dữ liệu

## Kế hoạch
Hoàn thành bước chuẩn hoá dấu tiếng Việt và báo cáo tỷ lệ lỗi còn lại.

## Công việc đã làm
Viết bộ chuẩn hoá dấu (NFC) và xử lý các trường hợp dấu đặt sai vị trí. Chạy trên toàn bộ 2,4 triệu
văn bản. Sửa lỗi tách từ làm hỏng các từ ghép có dấu gạch nối.

## Kết quả và điều học được
Tỷ lệ lỗi chuẩn hoá giảm từ 3,1 % xuống 0,4 %. Phần còn lại chủ yếu là văn bản gõ bằng bảng mã
TCVN3 cũ, cần một bộ chuyển mã riêng — đây là phát hiện mới, trước đây tôi cho rằng chỉ có Unicode.

## Bằng chứng
Commit `e77a2b1`; bảng thống kê lỗi trước và sau.

## Khó khăn
Không có.

## Kế hoạch tuần tới
Viết bộ chuyển mã TCVN3 sang Unicode.
