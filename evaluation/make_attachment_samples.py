"""Make small real files from the existing synthetic shop demo; no LLM calls."""
import io
import json
from pathlib import Path
import re
import zipfile
from xml.sax.saxutils import escape

from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject, NameObject, TextStringObject

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'frontend/security-console/public/attachment-samples'
OUT.mkdir(parents=True, exist_ok=True)
cases = json.loads((ROOT / 'frontend/security-console/lib/demo_scenarios.json').read_text(encoding='utf-8'))
source = next(c for c in cases['domains']['shop']['cases'] if c['kind'] == 'attack')['doc']['text']
instruction = re.search(r'<!--(.*?)-->', source, re.S).group(1).strip()
(OUT / 'invoice-clean.txt').write_text('Đơn DH20261031. Giá trị 60 USD. Đơn đã giao. Khách yêu cầu hỗ trợ kiểm tra đơn.\n', encoding='utf-8')
(OUT / 'invoice-hidden.html').write_text('<!doctype html><meta charset="utf-8"><h1>Phiếu giao hàng</h1>\n' + source, encoding='utf-8')
(OUT / 'invoice-hidden.eml').write_bytes(('From: supplier@example.com\r\nSubject: Delivery note\r\nMIME-Version: 1.0\r\nContent-Type: text/html; charset=utf-8\r\n\r\n' + source).encode('utf-8'))
(OUT / 'order-data.json').write_text(json.dumps({'order_id': 'DH20261031', 'order_value': 60, 'currency': 'USD', 'refund_requested': 30}, indent=2) + '\n', encoding='utf-8')
document = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
            '<w:p><w:r><w:t>Delivery note. Order DH20261031. Value 60 USD.</w:t></w:r></w:p>'
            '<w:p><w:r><w:rPr><w:vanish/></w:rPr><w:t>' + escape(instruction) + '</w:t></w:r></w:p></w:body></w:document>')
with zipfile.ZipFile(OUT / 'invoice-hidden.docx', 'w', zipfile.ZIP_DEFLATED) as z:
    z.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    z.writestr('_rels/.rels', '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    z.writestr('word/document.xml', document)
writer = PdfWriter(); page = writer.add_blank_page(500, 300)
page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): DictionaryObject({
    NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})})})
stream = DecodedStreamObject(); stream.set_data(b'BT /F1 12 Tf 25 230 Td (Delivery note. Order DH20261031. Value 60 USD.) Tj ET')
page[NameObject('/Contents')] = writer._add_object(stream)
annotation = DictionaryObject({NameObject('/Type'): NameObject('/Annot'), NameObject('/Subtype'): NameObject('/Text'),
    NameObject('/Rect'): ArrayObject([FloatObject(v) for v in (20, 20, 40, 40)]), NameObject('/Contents'): TextStringObject(instruction)})
page[NameObject('/Annots')] = ArrayObject([writer._add_object(annotation)])
writer.write(str(OUT / 'invoice-annotation.pdf'))
print('Generated 6 real sample files from existing synthetic shop-attack content.')
