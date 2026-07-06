"""MDX writer smoke test."""

from services.browser.mdx_writer import write_capture_artifacts


def test_write_capture_artifacts(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("services.browser.mdx_writer.MAYA_CAPTURE_MDX_ROOT", tmp_path)
    mdx_path, manifest_path = write_capture_artifacts(
        capture_id="00000000-0000-0000-0000-000000000001",
        capture_type="article",
        url="https://example.com/post",
        title="Example Post",
        content_hash="abc",
        tags=["research"],
        reader_text="Summary body",
        selection="highlight",
        assets=[{"key": "browser/pages/x/html.html", "kind": "html"}],
        metadata={"author": "test"},
    )
    assert mdx_path.is_file()
    assert manifest_path.is_file()
    text = mdx_path.read_text(encoding="utf-8")
    assert "Example Post" in text
    assert "research" in text
