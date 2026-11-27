import argparse
import base64
import html as html_lib
import os
import re
import sys
import traceback

import latex2mathml.converter
from bs4 import BeautifulSoup, NavigableString
from flask import Flask, jsonify, request
from weasyprint import HTML

app = Flask(__name__)

BASE_PATH = os.getenv("BASE_PATH", "")

PRINT_CSS = """
@page {
    size: A4;
    margin: 15mm 15mm 18mm 15mm;
    @bottom-center {
        content: counter(page) " / " counter(pages);
        font-family: "DejaVu Sans", sans-serif;
        font-size: 9pt;
        color: #666;
    }
}
html, body {
    background: #fff !important;
    color: #1a1a1a !important;
    font-family: "DejaVu Sans", "Liberation Sans", Arial, sans-serif !important;
    font-size: 10.5pt !important;
    line-height: 1.55 !important;
    overflow: visible !important;
    margin: 0;
    padding: 0;
}
h1, h2, h3, h4 {
    color: #111;
    margin-top: 1em;
    margin-bottom: 0.45em;
    page-break-after: avoid;
}
h2 {
    font-size: 16pt;
    margin-top: 0;
}
hr {
    border: none;
    border-top: 1px solid #cbd5e1;
    margin: 8px 0 12px 0;
}
.problem-info-entry {
    display: inline-block;
    vertical-align: top;
    padding: 4px 16px;
    text-align: left;
}
pre, code {
    font-family: "DejaVu Sans Mono", "Liberation Mono", monospace !important;
    font-size: 9.2pt !important;
    background: #f8fafc !important;
    border: 1px solid #e2e8f0;
    border-radius: 4px;
}
pre {
    padding: 8px 10px !important;
    white-space: pre-wrap !important;
    word-break: break-word !important;
    page-break-inside: avoid;
}
code {
    padding: 1px 4px;
}
pre code {
    border: none;
    padding: 0;
    background: transparent !important;
}
table {
    border-collapse: collapse;
    margin: 8px 0;
    max-width: 100%;
}
table th, table td {
    border: 1px solid #cbd5e1;
    padding: 5px 8px;
}
#info-table th, #info-table td {
    border: none;
}
img, svg {
    max-width: 100% !important;
    height: auto !important;
    page-break-inside: avoid;
}
ul, ol {
    margin: 4px 0 8px 0;
    padding-left: 20px;
}
p {
    margin: 0 0 8px 0;
}
math {
    font-family: "DejaVu Serif", "Liberation Serif", serif;
}
"""

_MATH_PATTERN = re.compile(
    r'(\$\$.*?\$\$|\\\[.*?\\\]|\\\(.*?\\\)|(?<!\\)\$(?!\s)(?:\\.|[^$\n])+?(?<!\s)\$)',
    re.DOTALL,
)


def _latex_to_mathml(expr: str, display: str) -> str:
    try:
        return latex2mathml.converter.convert(expr.strip(), display=display)
    except Exception:
        return expr


def _render_math_in_soup(soup: BeautifulSoup) -> None:
    skip_tags = {'script', 'style', 'pre', 'code', 'textarea', 'math'}
    text_nodes = [
        node for node in soup.descendants
        if isinstance(node, NavigableString)
        and not any(p.name in skip_tags for p in node.parents)
        and ('\\' in str(node) or '$' in str(node))
    ]
    for node in text_nodes:
        raw = str(node)
        if not _MATH_PATTERN.search(raw):
            continue
        parts = []
        last = 0
        for m in _MATH_PATTERN.finditer(raw):
            if m.start() > last:
                parts.append(html_lib.escape(raw[last:m.start()]))
            token = m.group(0)
            if token.startswith('$$') and token.endswith('$$'):
                parts.append(_latex_to_mathml(token[2:-2], 'block'))
            elif token.startswith(r'\[') and token.endswith(r'\]'):
                parts.append(_latex_to_mathml(token[2:-2], 'block'))
            elif token.startswith(r'\(') and token.endswith(r'\)'):
                parts.append(_latex_to_mathml(token[2:-2], 'inline'))
            elif token.startswith('$') and token.endswith('$'):
                parts.append(_latex_to_mathml(token[1:-1], 'inline'))
            else:
                parts.append(html_lib.escape(token))
            last = m.end()
        if last < len(raw):
            parts.append(html_lib.escape(raw[last:]))
        frag = BeautifulSoup(''.join(parts), 'html.parser')
        node.replace_with(frag)


def rewrite_html_paths(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "html.parser")

    for script in soup.find_all('script'):
        script.decompose()

    def to_local_uri(url: str) -> str:
        if re.match(r'^(?:https?:|data:|file:|//)', url):
            return url
        if BASE_PATH and url.startswith('/'):
            return f"file://{BASE_PATH}{url}"
        return url

    for tag in soup.find_all(src=True):
        src = tag["src"]
        if src:
            tag["src"] = to_local_uri(src)

    for tag in soup.find_all(href=True):
        href = tag["href"]
        if href and tag.name == 'link':
            tag["href"] = to_local_uri(href)

    for tag in soup.find_all(style=True):
        style = tag["style"]

        def repl(match):
            url = match.group(1).strip('\'"')
            if url:
                return f"url({to_local_uri(url)})"
            return match.group(0)

        tag["style"] = re.sub(r'url\((.*?)\)', repl, style)

    _render_math_in_soup(soup)

    head = soup.head
    if head is None:
        head = soup.new_tag('head')
        if soup.html:
            soup.html.insert(0, head)
        else:
            soup.insert(0, head)
    style_tag = soup.new_tag('style')
    style_tag.string = PRINT_CSS
    head.append(style_tag)

    return str(soup)


@app.route('/', methods=['POST'])
def create_pdf():
    try:
        title = request.form.get('title')
        html_content = request.form.get('html')

        if not title or not html_content:
            return jsonify({"success": False, "message": "Missing required parameters"}), 400

        html_content = rewrite_html_paths(html_content)
        base_url = f"file://{BASE_PATH}/" if BASE_PATH else "/"
        pdf_output = HTML(string=html_content, base_url=base_url).write_pdf()

        if pdf_output:
            pdf_base64 = base64.b64encode(pdf_output).decode('utf-8')
            return jsonify({"success": True, "pdf": pdf_base64})
        else:
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


if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser(description="Flask app to generate PDF")
        parser.add_argument('host', type=str, help="Host IP address")
        parser.add_argument('port', type=int, help="Port number")
        args = parser.parse_args()

        safe_run_app(args.host, args.port)

    except Exception as e:
        print(f"[FATAL ERROR] {str(e)}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
