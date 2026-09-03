"""The shared plan-CLI spec: internal consistency and argparse round-trips.

The spec (:mod:`qsiplan.cli_spec`) is the single description of the
plan-relevant CLI surface; qsiplan and qsiprep both build (or validate) their
parsers from it. These tests pin the spec against qsiplan's own truth - the
:class:`~qsiplan.models.GroupingPolicy` fields and the argparse round-trip - so
a flag added on one side or a field left unspelled fails here, in CI, instead
of drifting silently across the split (as ``selection_for_config``'s signature
already did once). qsiprep carries the mirror-image test against its parser.
"""

import argparse
import dataclasses

import pytest

from qsiplan.cli_spec import (
    PLAN_OPTIONS,
    Axis,
    Kind,
    add_plan_arguments,
    policy_from_namespace,
    selection_from_namespace,
)
from qsiplan.models import GroupingPolicy


def _parser():
    parser = argparse.ArgumentParser()
    add_plan_arguments(parser)
    return parser


def _policy_fields():
    return {field.name for field in dataclasses.fields(GroupingPolicy)}


def test_policy_options_cover_every_grouping_policy_field():
    # Every GroupingPolicy field must be reachable from some flag, so adding a
    # policy knob without a CLI spelling fails CI here.
    covered = set()
    for option in PLAN_OPTIONS:
        if option.axis is not Axis.POLICY:
            continue
        if option.policy_field:
            covered.add(option.policy_field)
        covered.update(field for _, field in option.members)
    assert covered == _policy_fields()


def test_every_named_target_is_a_real_policy_field():
    fields = _policy_fields()
    for option in PLAN_OPTIONS:
        if option.axis is not Axis.POLICY:
            continue
        if option.policy_field:
            assert option.policy_field in fields, option.flag
        for value, field in option.members:
            assert field in fields, f'{option.flag} {value}'


def test_method_options_name_real_selection_arguments():
    assert {opt.selection_arg for opt in PLAN_OPTIONS if opt.axis is Axis.METHOD} == {
        'hmc',
        'sdc',
        'shoreline_model',
    }


def test_default_namespace_is_the_default_policy():
    assert policy_from_namespace(_parser().parse_args([])) == GroupingPolicy()


def test_policy_from_namespace_tolerates_missing_flags():
    # A consumer can omit a flag it has not wired up (or a config object that
    # predates it); the missing attribute falls back to its default.
    namespace = argparse.Namespace(
        separate_all_dwis=True,
        ignore=['fieldmaps'],
        force=[],
        use_syn_sdc=False,
        distortion_group_merge='concat',
        # note: no `use_synb0` attribute at all
    )
    policy = policy_from_namespace(namespace)
    assert policy == GroupingPolicy(separate_all_dwis=True, ignore_fieldmaps=True)
    assert policy.use_synb0 is False


def test_ignore_is_one_list_flag_toggling_the_right_fields():
    policy = policy_from_namespace(_parser().parse_args(['--ignore', 'fieldmaps', 'shims']))
    assert policy.ignore_fieldmaps
    assert policy.ignore_shims
    assert not policy.ignore_fov
    assert not policy.ignore_sdc


def test_ignore_rejects_values_qsiplan_does_not_own():
    # 'phase' is a qsiprep-only --ignore choice; qsiplan's parser must not
    # silently accept it (it would map to no grouping field). 't2w' *is* owned
    # by qsiplan now (it drops the T2Wreg fieldmap-less fallback).
    with pytest.raises(SystemExit):
        _parser().parse_args(['--ignore', 'phase'])
    assert policy_from_namespace(_parser().parse_args(['--ignore', 't2w'])).ignore_t2w


def test_presence_flag_reads_as_bool():
    parser = _parser()
    assert policy_from_namespace(parser.parse_args([])).use_nipreps_syn_sdc is False
    assert policy_from_namespace(parser.parse_args(['--use-syn-sdc'])).use_nipreps_syn_sdc is True
    with_arg = parser.parse_args(['--use-syn-sdc', 'warn'])
    assert policy_from_namespace(with_arg).use_nipreps_syn_sdc is True


def test_selection_from_namespace_bridges_to_selection_for_config():
    parser = _parser()
    assert selection_from_namespace(parser.parse_args([])) is None
    namespace = parser.parse_args(
        ['--hmc-method', 'shoreline', '--shoreline-model', 'tensor', '--sdc-method', 'drbuddi']
    )
    selection = selection_from_namespace(namespace)
    assert (
        selection.combination_key()
        == 'hmc-method=shoreline&sdc-method=drbuddi&shoreline-model=tensor'
    )


def test_shoreline_model_requires_shoreline():
    namespace = _parser().parse_args(['--hmc-method', 'eddy', '--shoreline-model', 'tensor'])
    with pytest.raises(ValueError, match='requires --hmc-method shoreline'):
        selection_from_namespace(namespace)


@pytest.mark.parametrize(
    'policy',
    [
        GroupingPolicy(),
        GroupingPolicy(ignore_fieldmaps=True, ignore_shims=True),
        GroupingPolicy(ignore_pepolar_dwis=True, ignore_fieldmaps=True),
        GroupingPolicy(ignore_sdc=True, separate_all_dwis=True),
        GroupingPolicy(use_nipreps_syn_sdc=True, distortion_group_merge='none'),
        GroupingPolicy(force_t2wreg=True, use_synb0=True),
    ],
)
def test_cli_phrase_round_trips_through_the_parser(policy):
    # A policy -> its qsiprep flags -> parse -> the same policy. This closes the
    # loop between the display (cli_phrase) and the input (the spec parser).
    namespace = _parser().parse_args(policy.cli_phrase().split())
    assert policy_from_namespace(namespace) == policy


def test_owned_choices_are_the_conformance_contract():
    # The choices a consumer must accept, spelled per kind.
    by_flag = {opt.flag: opt for opt in PLAN_OPTIONS}
    assert set(by_flag['--ignore'].owned_choices()) == {
        'fieldmaps',
        'pepolar-dwis',
        't2w',
        'sdc',
        'shims',
        'fov',
    }
    assert by_flag['--ignore'].extendable  # qsiprep adds phase
    assert not by_flag['--use-synb0'].planned  # wired: qsiprep exposes the flag
    assert by_flag['--hmc-method'].kind is Kind.CHOICE
