import json

from erb import lint


def setup(tmp_path, monkeypatch, body, sources="- [S1] 10-K: https://sec.gov/x\n"):
    cdir = tmp_path / "T"
    (cdir / "sections").mkdir(parents=True)
    (cdir / "sections" / "02_x.md").write_text(body)
    (cdir / "sources.md").write_text(sources)
    (cdir / "model.json").write_text(json.dumps({
        "cover": {"currency": "USD"}, "rating": {"rating": "Outperform"},
        "scenarios": {"bear": {"price_target": 567.76}, "base": {"price_target": 935.94}, "bull": {"price_target": 1310.81}}}))
    monkeypatch.setattr(lint, "coverage_dir", lambda t: cdir)
    return {i.code for i in lint.lint("T")}, lint.lint("T")


def test_clean_paragraph_passes(tmp_path, monkeypatch):
    codes, _ = setup(tmp_path, monkeypatch,
                     "# Industry\n\nDigital ad spend rose 7.3% in CY'24 [S1]. We believe the Street is too cautious.\n"
                     "Our base case price target of $935.94 implies upside [M].\n")
    assert codes == set()


def test_catches_each_error(tmp_path, monkeypatch):
    codes, issues = setup(tmp_path, monkeypatch,
                          "Revenue grew 22.2% to $201.0 bn — a record.\n"
                          "I think margins expand 300 bps [S9].\n"
                          "We set a price target of $950.00 [M] and an Underperform rating [M].\n")
    assert {"em-dash", "unsourced", "first-person", "unknown-source", "pt-mismatch"} <= codes


def test_style_warnings(tmp_path, monkeypatch):
    codes, _ = setup(tmp_path, monkeypatch,
                     "Sales rose 15% in Q3 2025 to $4 billion [S1]. The landscape is robust [S1]. [VERIFY: check]\n")
    assert {"number-style", "ai-ism", "verify"} <= codes


def test_ignores_front_matter_comments_tokens_tables(tmp_path, monkeypatch):
    codes, _ = setup(tmp_path, monkeypatch,
                     "---\ntagline: \"Up 50%!\"\n---\n<!-- 15% example -->\n{{dcf}}\n| a | 15% |\n")
    assert codes == set()
