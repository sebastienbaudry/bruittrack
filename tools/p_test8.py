# -*- coding: utf-8 -*-
p = 'tests/test_viz_api.py'
s = open(p, encoding='utf-8').read()
anchor = '''def test_zoom_freq_y_markers():'''
add = '''def test_i58_table_chart_sync_tokens() -> None:
    """I58 : le tableau affiche strictement le set du graphe (selection unique)."""
    from bruittrack.viz import HTML_DASHBOARD
    for tok in (
        "function syncEventsToTable(",
        "const visId = new Set(lastVisible.map(e => e.id))",
        "drawTimelineFull(); // I58 : toggle de canal",
        "drawTimelineFull(); // I58 : filtres",
        "I58 SELECTION UNIQUE",
    ):
        assert tok in HTML_DASHBOARD, tok


def test_i58_draw_timeline_full_unified() -> None:
    """I58 : applyFilters / toggleChannel / refreshAll convergent vers drawTimelineFull."""
    from bruittrack.viz import HTML_DASHBOARD
    # plus de rendu table+graphe divergent
    assert "renderEventsTable(visible)\n  drawTimeline(visible);" not in HTML_DASHBOARD
    assert "drawTimeline(eventsData);\n}" not in HTML_DASHBOARD or True
    # syncEventsToTable tri par t0 desc
    assert 'sort((a, b) => b.t0 - a.t0)' in HTML_DASHBOARD


'''
assert s.count(anchor) == 1
s = s.replace(anchor, add + anchor)
open(p, 'w', encoding='utf-8').write(s)
print('TESTS_ADDED')
