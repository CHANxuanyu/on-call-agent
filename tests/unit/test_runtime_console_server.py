from runtime.console_server import render_operator_console_html


def test_console_html_keeps_panel_first_layout_and_secondary_assistant() -> None:
    html = render_operator_console_html()

    assert "Operator Console" in html
    assert "Incident Detail" in html
    assert "Timeline" in html
    assert "Session Assistant" in html
    assert "chat history" in html
    assert "Workflow authority" in html
    assert "Supporting context" in html
    assert "/api/phase1" in html
