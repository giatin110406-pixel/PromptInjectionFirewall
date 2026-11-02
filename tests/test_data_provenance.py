from evaluation.data_provenance import describe_data


def test_assignee_does_not_become_author_and_ai_metadata_survives_missing_author():
    result = describe_data([{"assigned_to": "Tín", "authorship": "ai_generated"}])
    assert result["data_authors"] == []
    assert result["declared_provenance"]["ai_generated"] == 1
    assert "AI-generated" in result["note"]


def test_missing_origin_is_unknown_not_human():
    result = describe_data([{"assigned_to": "Khang"}, {"author": "?"}])
    assert result["declared_provenance"]["unknown"] == 2
    assert "not established" in result["note"]


def test_legacy_ai_author_and_mixed_sources_are_reported():
    result = describe_data([{"author": "OpenAI Codex"}, {"author": "Thịnh"}])
    assert result["declared_provenance"] == {"ai_generated": 1, "named_without_ai_marker": 1, "unknown": 0}
    assert "not a result on human-written data" in result["note"]


def test_named_authors_are_declared_not_independently_verified():
    result = describe_data([{"author": "Thắng"}])
    assert result["data_authors"] == ["Thắng"]
    assert "not been independently verified" in result["note"]
