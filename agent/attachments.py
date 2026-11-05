"""Extract real, untrusted attachments without executing their active content."""
import hashlib
import http.client
import io
import ipaddress
import socket
import ssl
import time
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

MAX_BYTES = 5 * 1024 * 1024
MAX_TEXT = 20_000
FORMATS = {'.txt', '.md', '.csv', '.json', '.html', '.htm', '.eml', '.pdf', '.docx'}


class AttachmentError(ValueError):
    pass


def _decode(data):
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        return data.decode('utf-16')
    return data.decode('utf-8-sig')


def _docx(data):
    pieces = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if len(members) > 500 or sum(i.file_size for i in members) > 20 * 1024 * 1024:
            raise AttachmentError('DOCX quá lớn sau khi giải nén.')
        for item in members:
            if item.filename.startswith('word/') and item.filename.endswith('.xml') and any(
                part in item.filename for part in ('document', 'comments', 'footnotes', 'endnotes', 'header', 'footer')):
                tree = ElementTree.fromstring(archive.read(item))
                # Includes hidden runs, comments and tracked deletions; no Word macros are run.
                text = ' '.join(n.text for n in tree.iter() if n.tag.rsplit('}', 1)[-1] in ('t', 'delText') and n.text)
                if text:
                    pieces.append(f'[{item.filename}]\n{text}')
    return '\n\n'.join(pieces)


def _pdf(data):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise AttachmentError('PDF có mật khẩu; hãy xuất bản không khóa để thử.')
    if len(reader.pages) > 50:
        raise AttachmentError('PDF vượt 50 trang; hãy tách tài liệu.')
    pieces = []
    for page in reader.pages:
        contents = page.get_contents()
        if contents and len(contents.get_data()) > 10 * 1024 * 1024:
            raise AttachmentError('Trang PDF quá lớn để trích văn bản.')
        pieces.append(page.extract_text() or '')
        for annotation in page.get('/Annots', []):
            contents = annotation.get_object().get('/Contents')
            if contents:
                pieces.append('[PDF annotation]\n' + str(contents))
        if sum(map(len, pieces)) > MAX_TEXT:
            raise AttachmentError('Nội dung vượt 20.000 ký tự; hãy tách tài liệu. Không cắt bớt nội dung âm thầm.')
    return '\n'.join(pieces)


def parse_attachment(name, data, *, source='file', url=None, extension=None):
    name = PurePosixPath((name or 'attachment.txt').replace('\\', '/')).name[:160]
    suffix = (extension or PurePosixPath(name).suffix).lower()
    if suffix not in FORMATS:
        raise AttachmentError('Hỗ trợ PDF, DOCX, TXT, MD, CSV, JSON, HTML và EML. Hãy chuyển định dạng file này.')
    if not data or len(data) > MAX_BYTES:
        raise AttachmentError('File phải có nội dung và tối đa 5 MB.')
    notes = []
    try:
        if suffix == '.docx':
            text = _docx(data)
            notes.append('Trích cả text ẩn, ghi chú, header/footer; không chạy macro.')
        elif suffix == '.pdf':
            text = _pdf(data)
            notes.append('Trích text và chú thích PDF. Chưa có OCR cho ảnh hoặc PDF scan.')
        elif suffix == '.eml':
            message = BytesParser(policy=policy.default).parsebytes(data)
            parts = list(message.walk())
            if len(parts) > 100:
                raise AttachmentError('Email có quá nhiều phần.')
            text = '\n'.join(f'{k}: {v}' for k, v in message.items()) + '\n\n' + '\n'.join(
                str(p.get_content()) for p in parts if p.get_content_type() in ('text/plain', 'text/html'))
            notes.append('Trích phần văn bản email; không mở các file nhị phân lồng bên trong.')
        else:
            text = _decode(data)
            if suffix in ('.html', '.htm'):
                notes.append('Giữ HTML, comment và nội dung ẩn để quét injection; không chạy JavaScript.')
    except AttachmentError:
        raise
    except Exception as exc:
        raise AttachmentError(f'Không đọc được {name}. File có thể lỗi hoặc không đúng định dạng.') from exc
    if not text.strip():
        raise AttachmentError('Không trích được văn bản. File ảnh/PDF scan cần OCR trước khi gửi.')
    if len(text) > MAX_TEXT:
        raise AttachmentError('Nội dung vượt 20.000 ký tự; hãy tách tài liệu. Không cắt bớt nội dung âm thầm.')
    return {'name': name, 'text': text, 'channel': 'web' if source == 'url' else 'email' if suffix == '.eml' else 'document',
            'kind': source, 'format': suffix.lstrip('.'), 'bytes': len(data), 'chars': len(text),
            'sha256': hashlib.sha256(data).hexdigest(), 'url': url, 'notes': notes}


def _connection(url, timeout):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise AttachmentError('Link phải là HTTP/HTTPS và không chứa thông tin đăng nhập.')
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    if port not in (80, 443):
        raise AttachmentError('Chỉ tải link web ở cổng 80 hoặc 443.')
    addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(info[4][0]).is_global for info in addresses):
        raise AttachmentError('Chỉ tải link internet công khai. Với tài liệu local, hãy tải file trực tiếp.')
    pinned_ip = addresses[0][4][0]
    if parsed.scheme == 'https':
        connection = http.client.HTTPSConnection(parsed.hostname, port, timeout=timeout, context=ssl.create_default_context())
    else:
        connection = http.client.HTTPConnection(parsed.hostname, port, timeout=timeout)
    # Pin the validated address while retaining the original Host/SNI and certificate verification.
    connection._create_connection = lambda address, *args, **kwargs: socket.create_connection((pinned_ip, address[1]), *args, **kwargs)
    return connection, parsed


def fetch_attachment(url):
    if len(url) > 2048:
        raise AttachmentError('Link vượt 2.048 ký tự.')
    started = time.monotonic()
    try:
        for _ in range(4):
            remaining = 10 - (time.monotonic() - started)
            if remaining <= 0:
                raise AttachmentError('Hết thời gian tải link (10 giây).')
            connection, parsed = _connection(url, remaining)
            try:
                path = parsed.path or '/'
                if parsed.query:
                    path += '?' + parsed.query
                connection.request('GET', path, headers={'Accept-Encoding': 'identity', 'User-Agent': 'AI-Firewall-Attachment/1.0'})
                response = connection.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    location = response.getheader('Location')
                    if not location:
                        raise AttachmentError('Link chuyển hướng thiếu đích.')
                    url = urljoin(url, location)
                    continue
                if response.status != 200:
                    raise AttachmentError(f'Không tải được link: HTTP {response.status}.')
                if response.getheader('Content-Encoding', 'identity') != 'identity':
                    raise AttachmentError('Máy chủ trả nội dung nén không được hỗ trợ; hãy tải file trực tiếp.')
                data = bytearray()
                while True:
                    left = 10 - (time.monotonic() - started)
                    if left <= 0:
                        raise AttachmentError('Hết thời gian tải link (10 giây).')
                    if connection.sock:
                        connection.sock.settimeout(left)
                    chunk = response.read(min(65536, MAX_BYTES + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise AttachmentError('Nội dung link vượt 5 MB.')
                media = response.getheader('Content-Type', '').split(';')[0].strip().lower()
                formats = {'text/html': '.html', 'text/plain': '.txt', 'text/markdown': '.md', 'text/csv': '.csv',
                           'application/json': '.json', 'application/pdf': '.pdf', 'message/rfc822': '.eml',
                           'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx'}
                suffix = formats.get(media) or PurePosixPath(parsed.path).suffix
                result = parse_attachment(PurePosixPath(parsed.path).name or 'web.html', bytes(data),
                                          source='url', url=url, extension=suffix)
                result['name'] = parsed.hostname + (parsed.path if parsed.path != '/' else '')
                return result
            finally:
                connection.close()
        raise AttachmentError('Link chuyển hướng quá nhiều lần.')
    except AttachmentError:
        raise
    except Exception as exc:
        raise AttachmentError('Không tải được link. Hãy kiểm tra URL, kết nối hoặc tải file trực tiếp.') from exc
