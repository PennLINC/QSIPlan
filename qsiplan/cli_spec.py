"""The plan-relevant CLI surface, as one declarative spec shared across repos.

qsiplan owns the grouping/plan semantics (:class:`~.models.GroupingPolicy`,
:class:`~.methods.MethodSelection`), so it also owns the canonical description
of the CLI options that select them: their real qsiprep flag spellings, the
choices each accepts, and the policy/selection field each one drives. Both
qsiplan's own CLI and qsiprep build their parsers from this list - or, for a
hand-built parser, assert conformance to it in a contract test - so a flag can
never be spelled one way here and another way there, nor map to a field on one
side and drift on the other.

The list is deliberately small and data-only. It has to describe four shapes:

- a boolean flag (``--separate-all-dwis`` -> ``separate_all_dwis``);
- a value list whose members each toggle a field (``--ignore fieldmaps shims``
  -> ``ignore_fieldmaps``/``ignore_shims``) - qsiprep's ``--ignore`` takes a
  space-delimited list, never one ``--ignore-<value>`` flag per value;
- a single-value choice (``--distortion-group-merge {concat,average,none}``);
- a presence flag (``--use-syn-sdc``) whose optional ``warn``/``error``
  argument is a qsiprep runtime concern, so here it only signals "requested".

``--ignore`` and ``--force`` are *split-owned*: qsiplan owns the grouping
values listed here, and a consumer (qsiprep) may add more choices that mean
nothing to grouping (``phase``); those options are marked ``extendable``. An
option a consumer has not exposed yet may be marked ``planned``, so a
conformance check treats its absence there as expected rather than as drift
(``--use-synb0`` carried the mark until qsiprep wired it up).
"""

from __future__ import annotations

import dataclasses
import enum

from .methods import MethodSelection, selection_for_config
from .models import GroupingPolicy


class Axis(enum.StrEnum):
    """Which value object a plan option feeds."""

    POLICY = 'policy'  # -> GroupingPolicy (regroups the data)
    METHOD = 'method'  # -> MethodSelection (picks the software), via selection_for_config


class Kind(enum.StrEnum):
    """The argparse shape of a plan option."""

    FLAG = 'flag'  # store_true boolean
    PRESENCE = 'presence'  # nargs='?' - requested when present (truthy), value is a runtime detail
    CHOICE = 'choice'  # one value from ``choices``
    LIST = 'list'  # nargs='+' - each listed member toggles its field


def _dest(flag: str) -> str:
    """The argparse ``dest`` a flag lands on (``--hmc-method`` -> ``hmc_method``)."""
    return flag.lstrip('-').replace('-', '_')


@dataclasses.dataclass(frozen=True)
class PlanOption:
    """One plan-relevant CLI option: how it parses, and what it drives.

    ``members`` (for :attr:`Kind.LIST`) pairs each accepted value with the
    :class:`GroupingPolicy` field it toggles; ``policy_field`` names the field
    for the single-valued kinds; ``selection_arg`` names the
    :func:`~.methods.selection_for_config` argument a :attr:`Axis.METHOD`
    option feeds.
    """

    flag: str
    axis: Axis
    kind: Kind
    help: str
    policy_field: str | None = None  # FLAG / PRESENCE / CHOICE target
    members: tuple[tuple[str, str], ...] = ()  # LIST: (choice value, policy field)
    selection_arg: str | None = None  # METHOD: 'hmc' | 'sdc' | 'shoreline_model'
    choices: tuple[str, ...] = ()  # CHOICE / PRESENCE
    default: object = None
    const: object = None  # PRESENCE: value stored for the bare flag
    extendable: bool = False  # a consumer may add choices (split-owned lists)
    planned: bool = False  # spelled here, not yet exposed by every consumer

    @property
    def dest(self) -> str:
        return _dest(self.flag)

    def owned_choices(self) -> tuple[str, ...]:
        """The choices qsiplan owns - all a conformant consumer must accept."""
        if self.kind is Kind.LIST:
            return tuple(value for value, _ in self.members)
        return tuple(self.choices)

    def argparse_kwargs(self) -> dict:
        """Keyword arguments for ``parser.add_argument(self.flag, **kwargs)``."""
        kwargs: dict = {'dest': self.dest, 'help': self.help}
        if self.kind is Kind.FLAG:
            kwargs.update(action='store_true', default=bool(self.default))
        elif self.kind is Kind.PRESENCE:
            kwargs.update(
                nargs='?', const=self.const, choices=list(self.choices), default=self.default
            )
        elif self.kind is Kind.CHOICE:
            kwargs.update(choices=list(self.choices), default=self.default)
        elif self.kind is Kind.LIST:
            kwargs.update(
                nargs='+',
                choices=list(self.owned_choices()),
                default=list(self.default or ()),
            )
        return kwargs

    def policy_kwargs(self, namespace) -> dict:
        """The ``GroupingPolicy`` field(s) this option sets, from parsed args.

        A consumer need not expose every flag - a ``planned`` one, or a config
        object that predates it - so a missing attribute falls back to the
        option's default (``--use-synb0`` absent means ``use_synb0=False``).
        """
        value = getattr(namespace, self.dest, self.default)
        if self.kind in (Kind.FLAG, Kind.PRESENCE):
            return {self.policy_field: bool(value)}
        if self.kind is Kind.CHOICE:
            return {self.policy_field: value}
        if self.kind is Kind.LIST:
            chosen = set(value or ())
            return {field: member in chosen for member, field in self.members}
        return {}


#: The single, ordered description of every plan-relevant flag. Method options
#: come first (they select the pipeline), then the grouping-policy options.
PLAN_OPTIONS: tuple[PlanOption, ...] = (
    PlanOption(
        '--hmc-method',
        Axis.METHOD,
        Kind.CHOICE,
        'which software corrects head motion and eddy currents',
        selection_arg='hmc',
        choices=('eddy', 'shoreline', 'tortoise'),
        default=None,
    ),
    PlanOption(
        '--shoreline-model',
        Axis.METHOD,
        Kind.CHOICE,
        'SHORELine signal model (only with --hmc-method shoreline)',
        selection_arg='shoreline_model',
        choices=('3dshore', 'tensor', 'none'),
        default=None,
    ),
    PlanOption(
        '--sdc-method',
        Axis.METHOD,
        Kind.CHOICE,
        'which tool corrects PEPOLAR (blip-up/blip-down) susceptibility distortion',
        selection_arg='sdc',
        choices=('auto', 'topup', 'drbuddi', 'topup+drbuddi'),
        default='auto',
    ),
    PlanOption(
        '--separate-all-dwis',
        Axis.POLICY,
        Kind.FLAG,
        'process every DWI series as its own output, never combined',
        policy_field='separate_all_dwis',
        default=False,
    ),
    PlanOption(
        '--ignore',
        Axis.POLICY,
        Kind.LIST,
        'ignore aspects of the dataset (space-delimited): '
        "'fieldmaps' skips fmap/; 'pepolar-dwis' stops pairing DWIs with each "
        "other for PEPOLAR SDC; 't2w' drops the T2w (so no T2Wreg fieldmap-less "
        "SDC); 'sdc' disables distortion correction; "
        "'shims' treats shim settings as compatible; 'fov' concatenates "
        'mismatched fields of view',
        members=(
            ('fieldmaps', 'ignore_fieldmaps'),
            ('pepolar-dwis', 'ignore_pepolar_dwis'),
            ('t2w', 'ignore_t2w'),
            ('sdc', 'ignore_sdc'),
            ('shims', 'ignore_shims'),
            ('fov', 'ignore_fov'),
        ),
        default=(),
        extendable=True,
    ),
    PlanOption(
        '--force',
        Axis.POLICY,
        Kind.LIST,
        "force processing choices (space-delimited): 't2wreg' overrides all "
        'fieldmaps with T2w-registration SDC',
        members=(('t2wreg', 'force_t2wreg'),),
        default=(),
        extendable=True,
    ),
    PlanOption(
        '--use-syn-sdc',
        Axis.POLICY,
        Kind.PRESENCE,
        'request fieldmap-less SyN distortion correction from the anatomical image',
        policy_field='use_nipreps_syn_sdc',
        choices=('warn', 'error'),
        const='error',
        default=False,
    ),
    PlanOption(
        '--use-synb0',
        Axis.POLICY,
        Kind.FLAG,
        'request a SyNb0 synthetic-b=0 fieldmap-less estimation from the T1w',
        policy_field='use_synb0',
        default=False,
    ),
    PlanOption(
        '--distortion-group-merge',
        Axis.POLICY,
        Kind.CHOICE,
        "how to combine an output's correction units: concat, average, or none",
        policy_field='distortion_group_merge',
        choices=('concat', 'average', 'none'),
        default='concat',
    ),
)


def add_plan_arguments(parser, *, axis: Axis | None = None) -> None:
    """Render the plan options onto an argparse parser or argument group.

    ``axis`` restricts to one axis, so a consumer that files method and policy
    flags under different ``--help`` groups can call this once per group.
    """
    for option in PLAN_OPTIONS:
        if axis is not None and option.axis is not axis:
            continue
        parser.add_argument(option.flag, **option.argparse_kwargs())


def policy_from_namespace(namespace) -> GroupingPolicy:
    """The :class:`GroupingPolicy` the parsed policy flags select."""
    kwargs: dict = {}
    for option in PLAN_OPTIONS:
        if option.axis is Axis.POLICY:
            kwargs.update(option.policy_kwargs(namespace))
    return GroupingPolicy(**kwargs)


def selection_from_namespace(namespace) -> MethodSelection | None:
    """The single :class:`MethodSelection` the method flags name, or ``None``.

    ``None`` when no ``--hmc-method`` was given: the caller then previews every
    default combination instead of one. This is the drop-in replacement for a
    consumer's hand-written config-to-selection bridge - it can only spell what
    :func:`~.methods.selection_for_config` actually accepts.
    """
    hmc = getattr(namespace, 'hmc_method', None)
    if not hmc:
        return None
    shoreline_model = getattr(namespace, 'shoreline_model', None)
    if shoreline_model and hmc != 'shoreline':
        raise ValueError('--shoreline-model requires --hmc-method shoreline')
    sdc = getattr(namespace, 'sdc_method', None) or 'auto'
    return selection_for_config(shoreline_model or hmc, sdc)
