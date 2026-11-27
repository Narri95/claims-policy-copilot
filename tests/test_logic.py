"""Tests for the pure logic: clause chunking, keyword search and scoring."""
import numpy as np

import ask
import chunk_wording
import run_eval


def test_chunker_groups_wrapped_lines_and_tracks_section():
    lines = ["4. Section A: Damage to your car",
             "4.1 We pay for damage.", "It continues here.",
             "4.2 Second clause."]
    chunks = chunk_wording.parse_chunks(lines)
    assert [c["clause"] for c in chunks] == ["4.1", "4.2"]
    assert chunks[0]["text"] == "We pay for damage. It continues here."
    assert chunks[0]["section"] == "4. Section A: Damage to your car"
    assert chunks[0]["id"] == "chunk-001"


def test_chunker_makes_one_table_chunk():
    chunks = chunk_wording.parse_chunks(["3. Cover levels at a glance", "Benefit Essential Plus"])
    assert chunks[0]["type"] == "table"


def test_keyword_search_prefers_clause_with_the_words():
    chunks = [{"text": "We do not pay if over the alcohol limit"},
              {"text": "Windscreen glass replacement limits"}]
    scores = ask.keyword_scores("drove over the alcohol limit", chunks)
    assert scores[0] > scores[1]


def test_ranks_puts_highest_score_first():
    assert list(ask.ranks(np.array([0.1, 0.9, 0.5]))) == [2, 0, 1]


def test_cited_in_reads_grouped_and_table_citations():
    numbers, table = run_eval.cited_in("[6.4, 6.6] and [Table 3: Lost keys]")
    assert numbers == {"6.4", "6.6"} and table is True


def test_scoring_accepts_table_citation_and_flags_needless_referral():
    fields = run_eval.score_fields("3 table, 5.2", ["5.2"], "£90 [Table 3, 5.1, 5.2].")
    assert fields["cited_expected"] is True and fields["mentions_handler"] is False
    fields = run_eval.score_fields("8.1", ["8.1"], "14 days [8.1]. Refer to a claims handler.")
    assert fields["mentions_handler"] is True


def test_refusal_is_detected_with_curly_apostrophe():
    fields = run_eval.score_fields("", [], "I can\u2019t find this in the policy wording.")
    assert fields["refused"] is True
