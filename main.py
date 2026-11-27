import argparse
import base64
import os
import re
import sys
import tempfile
import threading
import traceback

from bs4 import BeautifulSoup
from flask import Flask, jsonify, request
from playwright.sync_api import sync_playwright

app = Flask(__name__)

BASE_PATH = os.getenv("BASE_PATH", "")

_lock = threading.Lock()
_playwright = None
_browser = None
_browser_pid = None


def _get_browser():
    global _playwright, _browser, _browser_pid
    pid = os.getpid()
    with _lock:
        if _browser is not None and _browser_pid == pid and _browser.is_connected():
            return _browser
        if _playwright is None or _browser_pid != pid:
            _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        _browser_pid = pid
        return _browser


def rewrite_html_paths(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "html.parser")

    def to_local_uri(url: str) -> str:
        if re.match(r"^(?:https?:|data:|file:|//)", url):
            return url
        if BASE_PATH and url.startswith("/"):
            return f"file://{BASE_PATH}{url}"
        return url

    for tag in soup.find_all(src=True):
        src = tag["src"]
        if src:
            tag["src"] = to_local_uri(src)

    for tag in soup.find_all(href=True):
        href = tag["href"]
        if href and tag.name == "link":
            tag["href"] = to_local_uri(href)

    for tag in soup.find_all(style=True):
        style = tag["style"]

        def repl(match):
            url = match.group(1).strip("'\"")
            if url:
                return f"url({to_local_uri(url)})"
            return match.group(0)

        tag["style"] = re.sub(r"url\((.*?)\)", repl, style)

    return str(soup)


def _render_with_chromium(html_content: str, footer_template: str | None = None,
                          wait_for_class: str | None = None, timeout_secs: float = 15.0) -> bytes:
    html_content = rewrite_html_paths(html_content)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".html", delete=False) as tf:
            tf.write(html_content)
            tmp_path = tf.name

        browser = _get_browser()
        context = browser.new_context(viewport={"width": 1024, "height": 1440})
        try:
            page = context.new_page()
            page.goto(f"file://{tmp_path}", wait_until="load", timeout=int(timeout_secs * 1000))
            page.evaluate("() => document.fonts ? document.fonts.ready : Promise.resolve()")
            if wait_for_class:
                try:
                    page.wait_for_selector(f".{wait_for_class}", timeout=1500)
                except Exception:
                    pass
            page.wait_for_timeout(150)

            pdf_kwargs = {
                "format": "A4",
                "scale": 0.85,
                "print_background": True,
                "margin": {"top": "14mm", "bottom": "16mm", "left": "14mm", "right": "14mm"},
            }
            if footer_template:
                ft = (
                    footer_template
                    .replace("{page_number}", '<span class="pageNumber"></span>')
                    .replace("{total_pages}", '<span class="totalPages"></span>')
                )
                pdf_kwargs["display_header_footer"] = True
                pdf_kwargs["header_template"] = "<span></span>"
                pdf_kwargs["footer_template"] = ft

            return page.pdf(**pdf_kwargs)
        finally:
            context.close()
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@app.route("/", methods=["POST"])
def create_pdf():
    try:
        title = request.form.get("title")
        html_content = request.form.get("html")
        footer_template = request.form.get("footer-template") or None
        wait_for_class = request.form.get("wait-for-class") or None
        try:
            timeout_secs = float(request.form.get("wait-for-duration-secs") or 15)
        except ValueError:
            timeout_secs = 15.0

        if not title or not html_content:
            return jsonify({"success": False, "message": "Missing required parameters"}), 400

        pdf_output = _render_with_chromium(
            html_content,
            footer_template=footer_template,
            wait_for_class=wait_for_class,
            timeout_secs=timeout_secs,
        )

        if pdf_output:
            pdf_base64 = base64.b64encode(pdf_output).decode("utf-8")
            return jsonify({"success": True, "pdf": pdf_base64})
        return jsonify({"success": False, "message": "Failed to generate PDF"}), 500

    except ModuleNotFoundError as e:
        traceback.print_exc(file=sys.stderr)
        return jsonify({"success": False, "message": f"ModuleNotFoundError: {str(e)}"}), 500
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500


def safe_run_app(host, port):
    """Chạy Flask app, không để crash toàn bộ app."""
    while True:
        try:
            print(f"Starting Flask app on {host}:{port}...", file=sys.stderr)
            app.run(host=host, port=port)
        except Exception as e:
            print(f"[ERROR] Flask app crashed: {str(e)}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            print("Restarting Flask app...", file=sys.stderr)


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(description="Flask app to generate PDF")
        parser.add_argument("host", type=str, help="Host IP address")
        parser.add_argument("port", type=int, help="Port number")
        args = parser.parse_args()

        safe_run_app(args.host, args.port)

    except Exception as e:
        print(f"[FATAL ERROR] {str(e)}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
