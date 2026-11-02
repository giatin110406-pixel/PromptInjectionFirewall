"""
Chart for the Data Leakage Check of BCTĐ2: how well length alone and a style-only classifier predict the label.

    python evaluation/plot_leakage_auc.py        ->  evaluation/results/leakage_auc.png

Reads only result files (leakage_report.json for the public sources, dataset_v2_audit.json for dataset v2,
leakage_v3.json for dataset v3). Horizontal grouped bars, one axis from 0.5 (the label cannot be guessed) to 1.0.
Colours: categorical slots 1 and 2 of the reference palette (checked with the validator: CVD and contrast pass).
"""
import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = os.path.join(BASE, "evaluation", "results")
OUT = os.path.join(R, "leakage_auc.png")

INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
BLUE, ORANGE = "#2a78d6", "#eb6834"      # length, style


def load(name):
    return json.load(open(os.path.join(R, name), encoding="utf-8"))


pub = load("leakage_report.json")["sources"]
v2 = load("dataset_v2_audit.json")["audit"]
v3 = load("leakage_v3.json")["length_style_auc"]

rows = [
    ("deepset (công khai)", pub["deepset"]["length_auc"], pub["deepset"]["style_auc"]),
    ("rikka-snow (công khai)", pub["rikka"]["length_auc"], pub["rikka"]["style_auc"]),
    ("BIPIA-GPT (công khai)", pub["bipia"]["length_auc"], pub["bipia"]["style_auc"]),
    ("tmdeptrai (công khai)", pub["tmdeptrai"]["length_auc"], pub["tmdeptrai"]["style_auc"]),
    ("Dataset v2, toàn bộ (dự án)", v2["all"]["length_auc"], v2["all"]["style_auc"]),
    ("Dataset v3, toàn bộ (dự án)", v3["all"]["length_auc"], v3["all"]["style_auc"]),
    ("Dataset v3, tập test (dự án)", v3["split:test"]["length_auc"], v3["split:test"]["style_auc"]),
    ("v3, nguồn xquad_vi_chat (cao nhất)", v3["source:xquad_vi_chat"]["length_auc"], v3["source:xquad_vi_chat"]["style_auc"]),
]

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "text.color": INK, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK})
fig, ax = plt.subplots(figsize=(7.4, 4.3), dpi=200)
fig.patch.set_facecolor(SURFACE)
ax.set_facecolor(SURFACE)

n = len(rows)
thick, gap = 0.30, 0.04            # bar thickness and the 2px surface gap between the two bars of a pair
base = 0.5
for i, (label, length, style) in enumerate(rows):
    y = n - 1 - i
    for k, (value, colour) in enumerate(((length, BLUE), (style, ORANGE))):
        yy = y + (0.5 * (thick + gap) if k == 0 else -0.5 * (thick + gap))
        ax.barh(yy, value - base, left=base, height=thick, color=colour, edgecolor="none", zorder=3)
        ax.text(value + 0.006, yy, f"{value:.2f}".replace(".", ","), va="center", ha="left", fontsize=7.5, color=INK2, zorder=5,
                bbox={"facecolor": SURFACE, "edgecolor": "none", "pad": 1.2})

ax.axvline(0.80, color=INK2, linewidth=1.0, zorder=2)
ax.text(0.803, n - 0.35, "Ngưỡng gắn cờ 0,80", fontsize=7.5, color=INK2, va="bottom", ha="left")
ax.axhline(3.5 - 0.0, color=GRID, linewidth=1.0, zorder=1)           # separator between public sources and the project data
ax.set_xlim(0.5, 1.0)
ax.set_ylim(-0.6, n - 0.1)
ax.set_yticks(range(n))
ax.set_yticklabels([r[0] for r in rows][::-1])
ax.set_xticks([0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
ax.set_xticklabels(["0,5", "0,6", "0,7", "0,8", "0,9", "1,0"])
ax.set_xlabel("AUC (0,5 = không đoán được nhãn; 1,0 = đoán hoàn hảo)")
ax.xaxis.grid(True, color=GRID, linewidth=0.8, zorder=0)
ax.set_axisbelow(True)
for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)
ax.spines["bottom"].set_color(GRID)
ax.tick_params(axis="y", length=0)
ax.tick_params(axis="x", length=0)

handles = [plt.Rectangle((0, 0), 1, 1, color=BLUE), plt.Rectangle((0, 0), 1, 1, color=ORANGE)]
leg = ax.legend(handles, ["AUC độ dài (chỉ nhìn độ dài văn bản)", "AUC văn phong (chỉ nhìn hình thức, không đọc nghĩa)"], loc="upper center",
                bbox_to_anchor=(0.42, 1.14), ncol=2, frameon=False, fontsize=8, handlelength=1.2, columnspacing=1.5)
for t in leg.get_texts():
    t.set_color(INK2)
fig.tight_layout()
fig.savefig(OUT, facecolor=SURFACE)
print("wrote", OUT)
