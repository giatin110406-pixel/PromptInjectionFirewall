# archive/: các phiên bản và file cũ

Nơi gom mọi thứ **không còn dùng cho engine hiện tại** (engine v4, L2 v3b), dọn ngày 02/11/2026. Không có code đang chạy nào đọc từ đây. Muốn dùng lại thứ gì thì chép ra, đừng sửa tại chỗ.

| Thư mục | Nội dung | Trong git? |
|---|---|---|
| `legacy_v1/` | Bản chụp engine v1 (XGBoost, DistilBERT), commit `65e2a02`. Xem `legacy_v1/README.md` | Có (trừ trọng số L3) |
| `reports_old/` | Báo cáo Word cũ: `BaoCao_Firewall_Layer0_5.docx` (13/10), `_v2.docx` (14/10), bản backup trước khi sửa. Báo cáo hiện hành: `../BaoCao_Firewall_Engine_v3.docx` | Có |
| `scripts_old/` | Script dùng một lần để sửa và đối chiếu báo cáo cũ (`edit_docx.py`, `verify_doc_claims*.py`). Đường dẫn bên trong vẫn trỏ vị trí cũ | Có |
| `notes_old/` | Ghi chú cũ: roadmap v1 (đã thay bằng `docs/implementation_plan_v4_vi.md`), text trích từ PDF hướng dẫn, `push_to_github.sh`, bản ghi phiên làm việc 14/10 | Có (trừ bản ghi phiên) |
| `downloads/` | Zip tải từ Google Drive và bundle Colab của mọi lần train L2 (v2, v3, v3b, v3c), khoảng 5,9 GB. Model đang dùng đã giải nén ở `models/l2_multilingual/artifacts*` | Không |
| `data_backups/` | Bản sao tạm của `data/processed` (dataset v2) | Không |
| `models_old/` | `l2_artifacts_old`: checkpoint L2 đời đầu | Không |
| `misc/` | File không thuộc dự án, để riêng cho chủ máy quyết định | Không |

Vẫn để ngoài thư mục này vì code còn dùng:
- `dataset_for_huggingface.jsonl` ở gốc (đọc bởi `data/scripts/build_dataset_v2.py`, `audit_leakage.py`).
- `models/l2_multilingual/artifacts_v2_aigen`, `artifacts_v3`, `artifacts_v3c` (dùng để so sánh model).
- `artifacts/` (zip bàn giao H1–H6; `evaluation/validate_h2_h3_review_drafts.py` đọc một file trong đó).
- `figma_inspiration/` (được `frontend/security-console/styles/globals.css` tham chiếu).
