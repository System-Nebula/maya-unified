"""Gateway research route tests."""

from maya_contracts import CreateResearchRunRequest, ResearchDepth


def test_create_run_request_contract():
    req = CreateResearchRunRequest(
        brief="Krea 2 technical analysis",
        depth=ResearchDepth.SHALLOW,
    )
    assert req.brief.startswith("Krea")
    assert req.depth == ResearchDepth.SHALLOW
