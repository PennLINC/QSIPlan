"""The tier-3 live provider: key parsing, the HTTP server, and static parity.

The contract under test: the canonical combined key IS the endpoint's query
string; a live view is byte-identical to what the static generator would
have embedded for the same combination; and combinations beyond the
embedded grid compile live.
"""

import json
import re
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest
from grouping_scenarios import build_layout

from qsiplan import index_subject, render_explorer_html
from qsiplan.explorer import reachable_policies
from qsiplan.methods import (
    combined_key,
    parse_combined_key,
    reachable_selections,
)
from qsiplan.serve import ExplorerApp, make_server


def test_parse_combined_key_roundtrips_the_whole_grid():
    for policy in reachable_policies():
        for selection in reachable_selections():
            parsed_policy, parsed_selection = parse_combined_key(combined_key(policy, selection))
            assert parsed_policy == policy
            assert parsed_selection == selection


def test_parse_combined_key_accepts_any_part_order():
    policy, selection = parse_combined_key(
        'separate-all-dwis=1&sdc-method=drbuddi&shoreline-model=tensor&hmc-method=shoreline'
    )
    assert policy.separate_all_dwis
    assert selection.shoreline_model == 'tensor'


def test_parse_combined_key_rejects_malformed_keys():
    with pytest.raises(ValueError, match='must include'):
        parse_combined_key('hmc-method=eddy')  # no sdc-method
    with pytest.raises(ValueError, match='Unknown key part'):
        parse_combined_key('hmc-method=eddy&sdc-method=topup&bogus=1')
    with pytest.raises(ValueError, match='shoreline-model is invalid'):
        parse_combined_key('hmc-method=eddy&sdc-method=topup&shoreline-model=tensor')
    with pytest.raises(ValueError, match='takes only the value 1'):
        parse_combined_key('hmc-method=eddy&sdc-method=topup&separate-all-dwis=yes')
    with pytest.raises(ValueError, match='Unknown distortion-group-merge'):
        parse_combined_key('hmc-method=eddy&sdc-method=topup&distortion-group-merge=maybe')


@pytest.fixture()
def served(tmp_path):
    layout, subject_data = build_layout('abcd_style', tmp_path)
    records, issues = index_subject(layout, subject_data)
    app = ExplorerApp(layout, ['01'])
    server = make_server(app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(
            url=f'http://127.0.0.1:{server.server_address[1]}',
            records=records,
            issues=issues,
        )
    finally:
        server.shutdown()
        server.server_close()


def _get(url):
    with urllib.request.urlopen(url) as response:  # noqa: S310 - our own localhost server
        return response.status, response.read().decode()


def _embedded_index(page):
    match = re.search(
        r'<script type="application/json" class="explorer-index">(.*?)</script>',
        page,
        re.DOTALL,
    )
    assert match
    return json.loads(match.group(1))


def test_served_page_is_live_and_minimal(served):
    # / redirects to the single subject's page.
    status, page = _get(served.url + '/')
    assert status == 200
    index = _embedded_index(page)
    assert index['api'] == '/sub-01/view'
    # Full policy map for the no-op greying, but only the initial
    # combination's content embedded - the rest is fetched live.
    assert len(index['policies']) == len(reachable_policies())
    assert sum(policy['sig'] is not None for policy in index['policies'].values()) == 1
    assert len(index['groupings']) == 1
    (by_selection,) = index['plans'].values()
    assert len(by_selection) == 1


def test_live_view_matches_the_static_embedding(served):
    static = render_explorer_html(served.records, '01', index_issues=served.issues)
    static_index = _embedded_index(static)
    policy_key = 'separate-all-dwis=1'
    selection_key = 'hmc-method=tortoise&sdc-method=drbuddi'
    status, body = _get(f'{served.url}/sub-01/view?{policy_key}&{selection_key}')
    assert status == 200
    data = json.loads(body)
    signature = static_index['policies'][policy_key]['sig']
    assert data['policyKey'] == policy_key
    assert data['selectionKey'] == selection_key
    assert data['policy'] == static_index['policies'][policy_key]
    assert data['grouping'] == static_index['groupings'][signature]
    assert data['payload'] == static_index['plans'][signature][selection_key]


def test_live_view_compiles_beyond_the_embedded_grid(served):
    # ignore-sdc is not in the enumerated grid; only the live compiler
    # reaches it.
    status, body = _get(f'{served.url}/sub-01/view?hmc-method=eddy&sdc-method=topup&ignore-sdc=1')
    assert status == 200
    data = json.loads(body)
    assert data['policyKey'] == 'ignore-sdc=1'
    assert 'No fieldmap estimations' in data['grouping']['view']


def test_view_errors_are_http_errors(served):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(served.url + '/sub-01/view?hmc-method=eddy')
    assert excinfo.value.code == 400
    assert 'error' in json.loads(excinfo.value.read().decode())
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(served.url + '/sub-99')
    assert excinfo.value.code == 404


def _duplicate_subject(bids_dir, src='01', dst='02'):
    """Copy sub-<src> to sub-<dst> so a scenario yields a two-subject cohort."""
    import os
    import shutil

    src_dir, dst_dir = bids_dir / f'sub-{src}', bids_dir / f'sub-{dst}'
    shutil.copytree(src_dir, dst_dir)
    for root, _dirs, files in os.walk(dst_dir):
        for name in files:
            if f'sub-{src}' in name:
                os.rename(
                    os.path.join(root, name),
                    os.path.join(root, name.replace(f'sub-{src}', f'sub-{dst}')),
                )


def test_multi_subject_root_shows_cohort_dashboard(tmp_path):
    build_layout('abcd_style', tmp_path)
    bids = tmp_path / 'abcd_style'
    _duplicate_subject(bids)
    from bids import BIDSLayout

    layout = BIDSLayout(str(bids), validate=False)
    app = ExplorerApp(layout, ['01', '02'])
    server = make_server(app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, page = _get(f'http://127.0.0.1:{server.server_address[1]}/')
        assert status == 200
        # The root is now the cohort dashboard, not a plain link list.
        assert 'Cohort Grouping Map' in page
        embed = json.loads(re.search(r'id="cohort-data">(.*?)</script>', page, re.DOTALL).group(1))
        assert {e['subject'] for e in embed['subject']} == {'01', '02'}
    finally:
        server.shutdown()
        server.server_close()


def test_cohort_page_embeds_labels_without_html_injection():
    from qsiplan.interactive import cohort_page_html

    facts = {'sig': 'a1', 'outputs': 1, 'runs': 1, 'errors': 0, 'warnings': 0}
    data = {
        'methods': [{'key': 'eddy', 'label': 'eddy', 'cli': '--hmc-method eddy'}],
        'session': [],
        'subject': [
            {
                'subject': 'x</script><img src=x onerror=alert(1)>',
                'label': 'x',
                'sessions': [],
                'scans': 1,
                't2w': False,
                'byMethod': {'eddy': facts},
            }
        ],
        'defaultGranularity': 'subject',
        'defaultMethod': 'eddy',
        'summary': {'subjects': 1, 'sessions': 0},
    }
    page = cohort_page_html(data, live=True)
    # The embedded JSON must not let a label close the script element.
    assert '</script><img' not in page


def test_server_caches_are_bounded_and_policies_compile_on_demand(tmp_path):
    layout, _ = build_layout('abcd_style', tmp_path)
    app = ExplorerApp(layout, ['01'], max_cached_subjects=1, max_cached_policies=2)

    page = app.page('01')
    index = _embedded_index(page)
    assert sum(policy['sig'] is not None for policy in index['policies'].values()) == 1

    app.view('01', 'hmc-method=eddy&sdc-method=topup&separate-all-dwis=1')
    app.view('01', 'hmc-method=eddy&sdc-method=topup&ignore-fieldmaps=1')
    state = app._states['01']
    assert len(state.groupings) == 2
