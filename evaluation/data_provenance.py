"""Describe declared dataset provenance without inferring authors from assignees."""

AI_MARKERS = ("ai-generated", "codex", "claude", "gpt", "deepseek", "gemini")


def describe_data(rows):
    authors = sorted({str(r["author"]).strip() for r in rows if r.get("author") and str(r["author"]).strip() != "?"})
    counts = dict(ai_generated=0, named_without_ai_marker=0, unknown=0)
    for row in rows:
        declared = str(row.get("authorship", "")).casefold()
        author = str(row.get("author") or "").strip()
        if declared.startswith("ai_") or any(marker in author.casefold() for marker in AI_MARKERS):
            counts["ai_generated"] += 1
        elif author and author != "?":
            counts["named_without_ai_marker"] += 1
        else:
            counts["unknown"] += 1
    if counts["ai_generated"]:
        note = "some rows are AI-generated (see authorship/README): pipeline check, not a result on human-written data"
    elif counts["unknown"]:
        note = "some rows have no declared author or origin; human authorship is not established"
    else:
        note = "rows name authors without AI markers; human authorship has not been independently verified"
    return dict(data_authors=authors, declared_provenance=counts, note=note)
