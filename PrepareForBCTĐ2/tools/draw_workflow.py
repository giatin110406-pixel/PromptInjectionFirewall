"""
Draw the firewall workflow from code.

    python PrepareForBCTĐ2/tools/draw_workflow.py

Writes PrepareForBCTĐ2/workflow/firewall_workflow.png (+ .svg) and firewall_workflow.mmd (Mermaid text).
To change a block's status after finishing a layer, edit STATUS below (done / partial / planned) and run again.
"""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workflow")

# key -> done | partial | planned
STATUS = {
    "user": "done", "l0": "done", "l1": "done", "l2": "done", "l3": "done", "decision": "done",
    "agent": "planned", "l5": "done", "reply": "planned",
    "src": "done", "clean": "done", "scan": "done", "taint": "done", "mark": "done", "ctx": "done",
    "call": "done", "l4a": "done", "l4b": "done", "l4c": "done", "run": "done", "queue": "done", "deny": "done",
    "console": "partial",
}
STYLE = {"done": ("#d9f2e1", "#2e7d4f", "-"), "partial": ("#fff1cc", "#b7791f", "-"), "planned": ("#ececec", "#7a7a7a", "--")}

BOXES = {
    # lane 1: user message
    "user": (0.3, 9.2, 1.9, 1.1, "Người dùng\nnhập prompt"),
    "l0": (2.7, 9.2, 2.1, 1.1, "L0 Chuẩn hóa\nbỏ ký tự ẩn, bỏ dấu,\nleet, base64 (7 góc nhìn)"),
    "l1": (5.3, 9.2, 2.3, 1.1, "L1 Chữ ký\nregex EN/VI + chỉ mục\nngữ nghĩa (3.590 mẫu)"),
    "l2": (8.1, 9.2, 2.3, 1.1, "L2 Bộ phân loại\nmDeBERTa, quét từng\ncửa sổ 200 token"),
    "l3": (10.9, 9.2, 2.1, 1.1, "L3 LLM judge\nca lưng chừng\n(đã chốt, sắp làm)"),
    "decision": (13.5, 9.2, 2.3, 1.1, "Quyết định\nALLOW / SANITIZE\nREVIEW / BLOCK"),
    "agent": (16.3, 9.2, 1.8, 1.1, "Agent LLM\n(demo)"),
    "l5": (18.6, 9.2, 2.3, 1.1, "L5 Output Guard\ncanary, PII,\nrò rỉ qua link/ảnh"),
    "reply": (21.4, 9.2, 1.6, 1.1, "Phản hồi\nngười dùng"),
    # lane 2: untrusted content
    "src": (0.3, 5.6, 2.3, 1.2, "Nội dung không tin cậy\nemail, web, RAG,\nkết quả công cụ"),
    "clean": (3.2, 5.6, 2.3, 1.2, "Làm sạch\ngỡ ghi chú HTML, CSS ẩn,\nký tự vô hình (quét cả phần ẩn)"),
    "scan": (6.1, 5.6, 2.3, 1.2, "Quét từng đoạn\ndùng lại L0 + L1 + L2\n(POST /chat/context)"),
    "taint": (9.0, 4.9, 2.6, 1.0, "Đoạn có chỉ thị: loại bỏ\nphiên bị gắn TAINT"),
    "mark": (9.0, 6.4, 2.6, 1.0, "Đoạn sạch: bọc <untrusted>\nvà datamark (spotlighting)"),
    "ctx": (12.2, 6.4, 2.4, 1.0, "Ngữ cảnh an toàn\nđưa vào Agent LLM"),
    # lane 3: actions
    "call": (0.3, 1.7, 2.3, 1.2, "Agent đề xuất\nhành động (hoàn tiền,\nchuyển tiền, đổi quyền...)"),
    "l4a": (3.2, 1.7, 2.4, 1.2, "L4a Luật cứng\nvai trò, hạn mức, OTP,\nkhông tự nâng quyền"),
    "l4b": (6.2, 1.7, 2.4, 1.2, "L4b Phiên bị TAINT?\ntiền, danh tính, quyền: BLOCK\nhoàn tiền, voucher: REVIEW"),
    "l4c": (9.2, 1.7, 2.4, 1.2, "L4c Chính sách YAML\nvượt ngưỡng, hành động\nquá nhiều: REVIEW"),
    "run": (12.3, 2.5, 1.8, 0.8, "ALLOW: chạy"),
    "queue": (12.3, 1.45, 2.6, 0.8, "REVIEW: hàng chờ người duyệt\n(/chat/review)"),
    "deny": (12.3, 0.4, 1.8, 0.8, "BLOCK: từ chối"),
    "console": (16.2, 1.7, 4.8, 1.2, "Security Console (SOC)\nnhật ký sự cố, luồng qua từng layer, hàng REVIEW\n(cần cập nhật theo engine v2)"),
}

ARROWS = [
    ("user", "l0", ""), ("l0", "l1", ""), ("l1", "l2", "PASS /\nESCALATE"), ("l2", "l3", "lưng chừng"),
    ("l3", "decision", ""), ("decision", "agent", "ALLOW"), ("agent", "l5", ""), ("l5", "reply", ""),
    ("src", "clean", ""), ("clean", "scan", ""), ("scan", "taint", "độc"), ("scan", "mark", "sạch"),
    ("mark", "ctx", ""),
    ("call", "l4a", ""), ("l4a", "l4b", "hợp lệ"), ("l4b", "l4c", "không taint"),
    ("l4c", "run", ""), ("l4c", "queue", ""), ("l4a", "deny", None),
]
DASHED_LINKS = [("ctx", "agent"), ("agent", "call"), ("decision", "console"), ("queue", "console")]


def center(key, side="c"):
    x, y, w, h, _ = BOXES[key]
    return {"c": (x + w / 2, y + h / 2), "r": (x + w, y + h / 2), "l": (x, y + h / 2),
            "t": (x + w / 2, y + h), "b": (x + w / 2, y)}[side]


def draw(ax):
    for key, (x, y, w, h, text) in BOXES.items():
        fill, edge, line = STYLE[STATUS[key]]
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12",
                                    facecolor=fill, edgecolor=edge, linewidth=1.6, linestyle=line))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=8.3, color="#1b1b1b", linespacing=1.25)

    def arrow(a, b, label, dashed=False, a_side=None, b_side=None):
        ax_, ay_ = center(a, a_side or "r")
        bx_, by_ = center(b, b_side or "l")
        ax.add_patch(FancyArrowPatch((ax_, ay_), (bx_, by_), arrowstyle="-|>", mutation_scale=13,
                                     linewidth=1.3, color="#444", linestyle="--" if dashed else "-",
                                     connectionstyle="arc3,rad=0.0"))
        if label:
            ax.text((ax_ + bx_) / 2, (ay_ + by_) / 2 + 0.18, label, ha="center", va="bottom", fontsize=7, color="#555")

    special = {("scan", "taint"): ("r", "l"), ("scan", "mark"): ("r", "l"), ("taint", "l4b"): ("b", "t"),
               ("l4c", "run"): ("r", "l"), ("l4c", "queue"): ("r", "l"), ("l4a", "deny"): ("b", "l"),
               ("mark", "ctx"): ("r", "l")}
    for a, b, label in ARROWS:
        if label is None:
            # L4a hard-rule violation goes straight to BLOCK
            x0, y0 = center("l4a", "b")
            x1, y1 = center("deny", "l")
            ax.plot([x0, x0, x1 - 0.02], [y0, y1, y1], color="#444", linewidth=1.3)
            ax.add_patch(FancyArrowPatch((x1 - 0.5, y1), (x1, y1), arrowstyle="-|>", mutation_scale=13, color="#444", linewidth=1.3))
            ax.text(x0 + 0.1, y0 - 0.3, "vi phạm luật", fontsize=7, color="#555")
            continue
        sides = special.get((a, b))
        arrow(a, b, label, a_side=sides[0] if sides else None, b_side=sides[1] if sides else None)
    def route(points, label=None, dashed=False, label_at=0):
        xs, ys = zip(*points)
        ax.plot(xs[:-1] + (xs[-1],), ys[:-1] + (ys[-1],), color="#444", linewidth=1.3, linestyle="--" if dashed else "-")
        ax.add_patch(FancyArrowPatch(points[-2], points[-1], arrowstyle="-|>", mutation_scale=13, color="#444", linewidth=1.3))
        if label:
            lx = (points[label_at][0] + points[label_at + 1][0]) / 2
            ly = (points[label_at][1] + points[label_at + 1][1]) / 2
            ax.text(lx, ly + 0.12, label, ha="center", va="bottom", fontsize=7, color="#555")

    cx, cy = center("ctx", "r")
    ag_b = center("agent", "b")
    route([(cx, cy), (17.4, cy), (17.4, ag_b[1])], "ngữ cảnh an toàn", dashed=True)
    tx, ty = center("taint", "b")
    l4b_t = center("l4b", "t")
    route([(tx, ty), (tx, 3.55), (l4b_t[0], 3.55), (l4b_t[0], l4b_t[1])], "cờ taint của phiên", dashed=False, label_at=1)
    call_t = center("call", "t")
    route([(ag_b[0] - 0.4, ag_b[1]), (ag_b[0] - 0.4, 3.95), (call_t[0], 3.95), (call_t[0], call_t[1])], "Agent đề xuất hành động", dashed=True, label_at=1)
    qx, qy = center("queue", "r")
    route([(qx, qy), (16.2, qy + 0.3 if False else 2.3)], None, dashed=True)

    # lane titles
    ax.text(0.3, 10.65, "① Đường tin nhắn người dùng", fontsize=11, fontweight="bold", color="#1f3a5f")
    ax.text(0.3, 7.25, "② Đường nội dung không tin cậy (chặn indirect injection)", fontsize=11, fontweight="bold", color="#1f3a5f")
    ax.text(0.3, 3.35, "③ Đường hành động của agent", fontsize=11, fontweight="bold", color="#1f3a5f")
    for y in (8.75, 3.15):
        ax.plot([0.2, 23.2], [y - 0.35 if y > 5 else y + 0.25, y - 0.35 if y > 5 else y + 0.25], color="#cfd6de", linewidth=0.8)

    # legend
    for i, (name, label) in enumerate([("done", "đã xong, có test"), ("partial", "xong một phần"), ("planned", "kế hoạch")]):
        fill, edge, line = STYLE[name]
        x = 16.2 + i * 2.35
        ax.add_patch(FancyBboxPatch((x, 0.45), 0.45, 0.3, boxstyle="round,pad=0.01", facecolor=fill, edgecolor=edge,
                                    linewidth=1.4, linestyle=line))
        ax.text(x + 0.55, 0.6, label, fontsize=8, va="center")


def mermaid() -> str:
    return """flowchart LR
  subgraph A[1. Tin nhắn người dùng]
    U[Người dùng] --> L0[L0 Chuẩn hóa] --> L1[L1 Chữ ký] --> L2[L2 mDeBERTa] -->|lưng chừng| L3[L3 LLM judge]
    L2 --> D{Quyết định}
    L3 --> D
    D -->|ALLOW| AG[Agent LLM] --> L5[L5 Output Guard] --> R[Phản hồi]
  end
  subgraph B[2. Nội dung không tin cậy]
    S[Email, web, RAG, tool] --> C[Làm sạch nội dung ẩn] --> SC[Quét từng đoạn: L0+L1+L2]
    SC -->|độc| T[Loại bỏ + gắn TAINT]
    SC -->|sạch| M[Bọc + datamark] --> X[Ngữ cảnh cho Agent]
  end
  subgraph C3[3. Hành động của agent]
    CALL[Hành động đề xuất] --> H[L4a Luật cứng] --> TA{L4b phiên bị TAINT?} --> P[L4c Chính sách YAML]
    P -->|ok| OK[ALLOW]
    P -->|vượt ngưỡng| Q[REVIEW: hàng chờ]
    H -->|vi phạm| BL[BLOCK]
  end
  T -.cờ taint.-> TA
  X -.-> AG
  AG -.-> CALL
"""


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    fig, ax = plt.subplots(figsize=(23.4, 11.8))
    ax.set_xlim(0, 23.4)
    ax.set_ylim(0, 11.4)
    ax.axis("off")
    ax.set_title("AI Firewall v2: luồng xử lý (tin nhắn, nội dung không tin cậy, hành động)", fontsize=14, fontweight="bold", loc="left")
    draw(ax)
    fig.tight_layout()
    for ext in ("png", "svg"):
        fig.savefig(os.path.join(OUT_DIR, f"firewall_workflow.{ext}"), dpi=130 if ext == "png" else None, bbox_inches="tight")
    with open(os.path.join(OUT_DIR, "firewall_workflow.mmd"), "w", encoding="utf-8") as handle:
        handle.write(mermaid())
    print("wrote", OUT_DIR)


if __name__ == "__main__":
    main()
