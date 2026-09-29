from erb import filings

DOC = """
TABLE OF CONTENTS
Item 1. Business 3
Item 1A. Risk Factors 10
Item 7. Management's Discussion and Analysis 40
Item 8. Financial Statements 60

Item 1. Business
We make widgets. """ + "Widgets are great. " * 50 + """
Item 1A. Risk Factors
Widgets might break. """ + "Risk. " * 50 + """
Item 1B. Unresolved Staff Comments
None.
"""


def test_section_skips_table_of_contents():
    spec = dict((n, (s, e)) for n, s, e in filings.SECTIONS["10-K"])
    body = filings.extract_section(DOC, *spec["business"])
    assert body.startswith("Item 1. Business\nWe make widgets.")
    assert "Risk Factors" not in body
    risks = filings.extract_section(DOC, *spec["risk_factors"])
    assert risks.startswith("Item 1A. Risk Factors\nWidgets might break.") and "Unresolved" not in risks


def test_html_tables_become_rows():
    html = "<p>Intro</p><table><tr><td>Revenue</td><td>$</td><td>100</td></tr><tr><td>Cost</td><td>40</td></tr></table>"
    text = filings.html_to_text(html)
    assert "Revenue | 100" in text and "Cost | 40" in text
