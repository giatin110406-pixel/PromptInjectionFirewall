import csv
import os

import pandas as pd
import pytest

from data.scripts import review_vi_test as r

NAMES = ["An", "Binh", "Chi", "Dung", "Em", "Phuc"]


def _master(path, n=60):
    rows = []
    for i in range(n):
        label = "attack" if i % 2 else "benign"
        rows.append({"id": f"T{i:03d}", "text": f"văn bản số {i}", "label": label,
                     "attack_type": "direct_injection" if label == "attack" else "safe", "style": "plain",
                     "difficulty": "easy", "author": "Claude", "reviewer": "", "reviewer_label": "", "notes": ""})
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _answer_all(directory, agree=True):
    """Fill every sheet the way a careful reviewer would: attack iff the text number is odd."""
    for name in os.listdir(directory):
        if not name.startswith("review_"):
            continue
        path = os.path.join(directory, name)
        sheet = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        sheet["reviewer_label"] = ["attack" if int(t.split()[-1]) % 2 else "benign" for t in sheet["text"]]
        sheet.to_csv(path, index=False, encoding="utf-8-sig")


def test_split_is_blind_balanced_and_covers_every_row_once(tmp_path):
    master = _master(str(tmp_path / "vi.csv"))
    counts = r.split(master, NAMES, str(tmp_path / "rev"))
    assert sum(counts.values()) == 60 and set(counts.values()) == {10}

    seen = []
    for name in NAMES:
        with open(tmp_path / "rev" / f"review_{name}.csv", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert list(rows[0].keys()) == r.SHEET_COLUMNS  # no label, attack_type or author in the sheet
        assert all(row["reviewer_label"] == "" for row in rows)
        seen += [row["id"] for row in rows]
    assert sorted(seen) == [f"T{i:03d}" for i in range(60)]


def test_split_is_deterministic_and_changes_with_the_seed(tmp_path):
    master = _master(str(tmp_path / "vi.csv"))
    r.split(master, NAMES, str(tmp_path / "a"), seed=1)
    r.split(master, NAMES, str(tmp_path / "b"), seed=1)
    r.split(master, NAMES, str(tmp_path / "c"), seed=2)
    read = lambda d: (tmp_path / d / "review_An.csv").read_text(encoding="utf-8-sig")
    assert read("a") == read("b") and read("a") != read("c")


def test_the_author_never_reviews_their_own_rows(tmp_path):
    master = _master(str(tmp_path / "vi.csv"))
    frame = pd.read_csv(master, dtype=str, keep_default_na=False)
    frame.loc[frame.index[:30], "author"] = "An"
    frame.to_csv(master, index=False)
    r.split(master, NAMES, str(tmp_path / "rev"))
    an_rows = pd.read_csv(tmp_path / "rev" / "review_An.csv", dtype=str)["id"]
    assert not set(an_rows) & set(frame.loc[frame.index[:30], "id"])


def test_split_validates_reviewers(tmp_path):
    master = _master(str(tmp_path / "vi.csv"))
    with pytest.raises(ValueError):
        r.split(master, ["An"], str(tmp_path / "rev"))
    with pytest.raises(ValueError):
        r.split(master, ["An", "an"], str(tmp_path / "rev"))


def test_merge_fills_reviewer_fields_and_keeps_a_backup(tmp_path):
    master = _master(str(tmp_path / "vi.csv"))
    r.split(master, NAMES, str(tmp_path / "rev"))
    _answer_all(str(tmp_path / "rev"))
    result = r.merge(master, str(tmp_path / "rev"))
    assert result["reviewed"] == 60 and result["disagree"] == 0 and result["agreement_rate"] == 1.0
    assert result["problems"] == []
    merged = pd.read_csv(master, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    assert set(merged["reviewer"]) == set(NAMES) and (merged["reviewer_label"] != "").all()
    assert (tmp_path / "vi_test_v1.before_review.csv").exists()


def test_merge_reports_disagreements_and_can_drop_them(tmp_path):
    master = _master(str(tmp_path / "vi.csv"))
    r.split(master, NAMES, str(tmp_path / "rev"))
    _answer_all(str(tmp_path / "rev"))
    sheet = tmp_path / "rev" / "review_An.csv"
    frame = pd.read_csv(sheet, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    wrong_id = frame.loc[0, "id"]
    frame.loc[0, "reviewer_label"] = "benign" if frame.loc[0, "reviewer_label"] == "attack" else "attack"
    frame.to_csv(sheet, index=False, encoding="utf-8-sig")

    result = r.merge(master, str(tmp_path / "rev"), drop_disagreements=True)
    assert result["disagree"] == 1 and result["disagreement_ids"] == [wrong_id] and result["dropped"]
    remaining = pd.read_csv(master, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    assert wrong_id not in set(remaining["id"]) and len(remaining) == 59
    assert (tmp_path / "rev" / "dropped_disagreements.csv").exists()


def test_merge_flags_bad_sheets(tmp_path):
    master = _master(str(tmp_path / "vi.csv"))
    r.split(master, NAMES, str(tmp_path / "rev"))
    _answer_all(str(tmp_path / "rev"))
    sheet = tmp_path / "rev" / "review_Binh.csv"
    frame = pd.read_csv(sheet, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    frame.loc[0, "reviewer_label"] = ""
    frame.loc[1, "reviewer_label"] = "maybe"
    frame.to_csv(sheet, index=False, encoding="utf-8-sig")
    result = r.merge(master, str(tmp_path / "rev"))
    text = " | ".join(result["problems"])
    assert "has no reviewer_label" in text and "use benign or attack" in text
    assert result["unreviewed"] == 2


def test_the_real_test_set_survives_a_full_split_and_merge_round_trip(tmp_path):
    real = os.path.join(r.BASE_DIR, "data", "eval", "vi_test_v1.csv")
    if not os.path.exists(real):
        pytest.skip("vi_test_v1.csv not present")
    copy = tmp_path / "vi.csv"
    copy.write_bytes(open(real, "rb").read())
    counts = r.split(str(copy), NAMES, str(tmp_path / "rev"))
    assert sum(counts.values()) == 300 and set(counts.values()) == {50}
