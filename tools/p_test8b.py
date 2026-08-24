# -*- coding: utf-8 -*-
p = 'tests/test_viz_api.py'
s = open(p, encoding='utf-8').read()
add = '''

def test_i58_table_chart_sync_tokens() -> None:
    """I58 : le tableau affiche strictement le set du graphe (selection unique)."""
    from bruittrack.viz import HTML_DASHBOARD

    for tok in (
        "function syncEventsToTable(",
        "const visId = new Set(lastVisible.map(e => e.id))",
        "I58 SELECTION UNIQUE",
        "sort((a, b) => b.t0 - a.t0)",
    ):
        assert tok in HTML_DASHBOARD, tok


def test_i58_no_divergent_renders() -> None:
    """I58 : plus de rendu table+graphe divergent en dehors du chemin unifie."""
    from bruittrack.viz import HTML_DASHBOARD

    assert "const visible = filterEvents(eventsData);\n  renderEventsTable(visible)" not in HTML_DASHBOARD
    # applyFilters minimal : uniquement drawTimelineFull()
    i = HTML_DASHBOARD.find("function applyFilters() {")
    block = HTML_DASHBOARD[i: i + 200]
    assert "drawTimelineFull(); // I58" in block
'''
open(p, 'a', encoding='utf-8').write(add)
print('APPENDED')
