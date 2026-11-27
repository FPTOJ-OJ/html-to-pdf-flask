# HTML to PDF Service (Flask + Playwright Chromium)

Microservice chuyển đổi nội dung HTML (kèm CSS, KaTeX/MathJax JS và ảnh/SVG tĩnh) sang PDF chuẩn A4, trả về chuỗi base64 qua HTTP JSON.

---

## 1. Cài đặt

### Tạo môi trường ảo & cài thư viện Python

```bash
python3 -m venv env
source env/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Cài đặt trình duyệt Chromium cho Playwright

```bash
playwright install chromium
# Nếu thiếu thư viện hệ thống trên Ubuntu/Debian:
sudo env/bin/playwright install-deps chromium
```

---

## 2. Chạy dịch vụ

### Cách 1: Chạy trực tiếp (Development)

```bash
BASE_PATH=/home/kien/site env/bin/python main.py 127.0.0.1 8888
```

### Cách 2: Chạy Production với uWSGI & Supervisor

Cấu hình `/etc/supervisor/conf.d/html-to-pdf-flask.conf`:

```ini
[program:html-to-pdf-flask]
command=/home/kien/html-to-pdf-flask/env/bin/uwsgi --ini uwsgi.ini
directory=/home/kien/html-to-pdf-flask
stopsignal=TERM
stopasgroup=true
killasgroup=true
environment=BASE_PATH="/home/kien/site",PLAYWRIGHT_BROWSERS_PATH="/home/kien/.cache/ms-playwright"
stdout_logfile=/home/kien/site/logs/html-to-pdf-flask_log.log
stderr_logfile=/home/kien/site/logs/html-to-pdf-flask.log
autorestart=true
```

Nạp lại Supervisor:

```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl restart html-to-pdf-flask
```

**Lưu ý biến môi trường:**
- `BASE_PATH`: Thư mục gốc của FPTOJ Site (ví dụ `/home/kien/site`). Các đường dẫn tương đối như `/static/...`, `/userdata/...` sẽ được tự động ánh xạ sang `file://<BASE_PATH>/...` để Chromium nạp CSS/JS/font/SVG trực tiếp từ đĩa.
- `PLAYWRIGHT_BROWSERS_PATH`: Đường dẫn chứa trình duyệt Chromium của Playwright (rất cần thiết nếu Supervisor chạy dưới user khác user đã cài `playwright install chromium`).

---

## 3. Sử dụng API

Gửi `POST /` với `application/x-www-form-urlencoded`:

- `title` *(bắt buộc)*: Tiêu đề tài liệu.
- `html` *(bắt buộc)*: Toàn bộ mã HTML cần chuyển sang PDF.
- `footer-template` *(tùy chọn)*: Mẫu footer HTML (hỗ trợ `{page_number}` và `{total_pages}`).
- `wait-for-class` *(tùy chọn)*: Chờ phần tử có class CSS xuất hiện trước khi xuất PDF.
- `wait-for-duration-secs` *(tùy chọn)*: Timeout tối đa tính bằng giây (mặc định `15`).

**Ví dụ:**

```bash
curl -X POST http://127.0.0.1:8888/ \
  -d "title=Test" \
  --data-urlencode "html=<h1>Xin chào FPTOJ</h1>"
```

**Kết quả thành công:**

```json
{
  "success": true,
  "pdf": "<base64-encoded-pdf>"
}
```

**Kết quả lỗi:**

```json
{
  "success": false,
  "message": "Missing required parameters"
}
```
