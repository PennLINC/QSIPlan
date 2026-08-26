"""The qsiplan CLI, end to end over materialized skeleton datasets."""

import os.path as op

import pytest
from grouping_scenarios import get_test_data_path

from qsiplan.cli import main
from qsiplan.utils import generate_bids_skeleton


def _materialize(scenario, tmp_path):
    bids_dir = tmp_path / scenario
    generate_bids_skeleton(
        str(bids_dir), op.join(get_test_data_path(), f'skeleton_grouping_{scenario}.yml')
    )
    return bids_dir


def test_cli_prints_report_and_writes_html(tmp_path, capsys):
    bids_dir = _materialize('hcp_style', tmp_path)
    html = tmp_path / 'grouping.html'
    assert main([str(bids_dir), '--html', str(html)]) == 0
    out = capsys.readouterr().out
    assert 'DWI grouping for sub-01' in out
    assert 'Processing preview:' in out
    page = html.read_text()
    assert page.startswith('<!doctype html>')
    # The page is the explorer: policy controls, method controls, and the
    # embedded policy-grid index.
    assert 'class="plan-explorer"' in page
    assert 'class="ctl-policy"' in page
    assert 'class="explorer-index"' in page


def test_cli_single_selection_flags(tmp_path, capsys):
    bids_dir = _materialize('hcp_style', tmp_path)
    html = tmp_path / 'grouping.html'
    assert main([str(bids_dir), '--hmc-method', 'tortoise', '--html', str(html)]) == 0
    out = capsys.readouterr().out
    # One preview, for the selected combination only.
    assert out.count('Processing preview:') == 1
    assert 'TORTOISE + DRBUDDI' in out
    # The page keeps every method selectable; the CLI flags pick the initial
    # control state.
    page = html.read_text()
    assert '<option value="tortoise" selected>' in page


def test_cli_exit_code_reflects_grouping_errors(tmp_path, capsys):
    bids_dir = _materialize('nonshelled_pair', tmp_path)
    assert main([str(bids_dir)]) == 0  # non-shelled is only an error for eddy previews
    capsys.readouterr()
    bids_dir2 = _materialize('name_collision', tmp_path)
    assert main([str(bids_dir2)]) == 1
    assert 'output-name-collision' in capsys.readouterr().out


def test_cli_serve_and_html_are_mutually_exclusive(tmp_path, capsys):
    bids_dir = _materialize('hcp_style', tmp_path)
    with pytest.raises(SystemExit, match='mutually exclusive'):
        main([str(bids_dir), '--serve', '--html', str(tmp_path / 'x.html')])


def test_cli_multi_subject_writes_per_subject_pages(tmp_path, capsys):
    bids_dir = _materialize('multi_session', tmp_path)
    html = tmp_path / 'grouping.html'
    main([str(bids_dir), '--html', str(html)])
    capsys.readouterr()
    written = sorted(p.name for p in tmp_path.glob('grouping*.html'))
    assert written  # one page (single subject) or one per subject
