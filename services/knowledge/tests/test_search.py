from aihub_knowledge.search import RankedItem, reciprocal_rank_fusion


def test_rrf_prefers_items_present_in_both_rankings():
    result = reciprocal_rank_fusion(
        [RankedItem("a", "a"), RankedItem("b", "b")],
        [RankedItem("b", "b"), RankedItem("c", "c")],
    )
    assert result[0].key == "b"
