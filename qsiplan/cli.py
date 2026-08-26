"""Preview how qsiprep would group and process a BIDS dataset's DWI scans.

Usage::

    qsiprep-group /path/to/bids [--participant-label 01 02] \\
        [--ignore-shims] [--separate-all-dwis] [--ignore-fieldmaps] \\
        [--hmc-method eddy|shoreline|tortoise] [--sdc-method auto|topup|...]

Prints, per subject, the grouping decisions (with curated/inferred
provenance) and a plain-language preview of what the selected processing
methods would do with the data - or, with no method flags, every default
method combination. Nothing is processed and nothing is written.
"""

import argparse
import sys
from functools import partial
from pathlib import Path

from qsiplan import (
    describe_processing,
    index_subject,
    render_explorer_html,
    report_text,
    selection_for_config,
)
from qsiplan.explorer import build_for_policy
from qsiplan.methods import SHORELINE_MODELS
from qsiplan.models import GroupingPolicy
from qsiplan.report import default_preview_selections


def _path_exists(path, parser):
    """Ensure a given path exists.

    Parameters
    ----------
    path : str or None
        The path to check for existence. If None or the path does not exist, an error is raised.
    parser : argparse.ArgumentParser
        The argument parser instance used to raise an error if the path does not exist.

    Returns
    -------
    pathlib.Path
        The absolute path if it exists.

    Raises
    ------
    argparse.ArgumentError
        If the path does not exist or is None.
    """
    if path is not None:
        path = Path(path)

    if path is None or not path.exists():
        raise parser.error(f'Path does not exist: <{path.resolve()}>.')
    return path.resolve()


def _is_dir(path, parser):
    """Ensure a given path exists and is a directory."""
    path = _path_exists(path, parser)
    if not path.is_dir():
        raise parser.error(
            f'Path should point to a directory (or symlink of directory): <{path.absolute()}>.'
        )
    return str(path)


def _build_parser():
    parser = argparse.ArgumentParser(
        prog='qsiplan',
        description=__doc__.splitlines()[0],
    )
    IsDir = partial(_is_dir, parser=parser)

    parser.add_argument(
        'bids_dir',
        type=IsDir,
        help='Root of the BIDS dataset',
    )
    parser.add_argument(
        '--participant-label',
        nargs='+',
        default=None,
        help='Subject label(s) to preview (without "sub-"). Default: all subjects.',
    )
    parser.add_argument(
        '--session-id',
        default=None,
        help='Restrict to one session label (without "ses-").',
    )
    parser.add_argument(
        '--hmc-method',
        choices=['eddy', 'shoreline', 'tortoise'],
        default=None,
        help='Preview one head-motion-correction method instead of all defaults.',
    )
    parser.add_argument(
        '--shoreline-model',
        choices=list(SHORELINE_MODELS),
        default=None,
        help='SHORELine signal model (with --hmc-method shoreline).',
    )
    parser.add_argument(
        '--sdc-method',
        choices=['auto', 'topup', 'drbuddi', 'topup+drbuddi'],
        default='auto',
        help='PEPOLAR tool preference for the previewed method (default: auto).',
    )
    parser.add_argument(
        '--ignore-shims',
        action='store_true',
        help='Treat all ShimSetting values as compatible.',
    )
    parser.add_argument(
        '--ignore-fov',
        action='store_true',
        help=(
            'Concatenate series with differently-oriented fields of view anyway '
            '(distortion corrections will be misapplied). Grid-size mismatches '
            'still error.'
        ),
    )
    parser.add_argument(
        '--separate-all-dwis',
        action='store_true',
        help='Every DWI series becomes its own output.',
    )
    parser.add_argument(
        '--ignore-fieldmaps',
        action='store_true',
        help='Skip fmap/; only the reverse phase-encoding DWI heuristic applies.',
    )
    parser.add_argument(
        '--force',
        nargs='+',
        default=[],
        choices=['t2wreg'],
        help='Force processing choices (space-delimited list). "t2wreg" '
        'overrides all fieldmaps with T2w-registration SDC (TORTOISE T2Wreg).',
    )
    parser.add_argument(
        '--distortion-group-merge',
        choices=['concat', 'average', 'none'],
        default='concat',
        help="How the corrected results of an output's correction units are "
        'combined: concatenated (default), averaged (opposite-PE duplicate '
        'schemes), or kept as separate per-unit outputs.',
    )
    parser.add_argument(
        '--use-synb0',
        action='store_true',
        help='Give fieldmap-less series a SyNb0 synthetic-b=0 estimation from the T1w.',
    )
    parser.add_argument(
        '--html',
        metavar='PATH',
        help='Also write a self-contained explorer HTML page: the grouping plus '
        'live controls for every grouping-policy and processing-method flag '
        '(the CLI flags pick the initial state). With more than one subject, '
        'the subject label is inserted before the extension.',
    )
    parser.add_argument(
        '--serve',
        action='store_true',
        help='Serve the explorer live at http://localhost:<port> instead of '
        'writing files: every control change is answered by the real compiler, '
        'and flag combinations beyond the embedded grid work too.',
    )
    parser.add_argument(
        '--port',
        type=int,
        default=8765,
        help='Port for --serve (default: 8765).',
    )
    return parser


def _per_subject_path(path: str, subject: str, multi: bool) -> str:
    """Insert ``sub-<label>`` before the extension when writing many subjects."""
    if not multi:
        return path
    base, dot, ext = path.rpartition('.')
    stem = base if dot else path
    suffix = f'.{ext}' if dot else ''
    return f'{stem}_sub-{subject}{suffix}'


def _selections(args):
    """The method selections to preview, from the parsed arguments."""
    if args.shoreline_model and args.hmc_method != 'shoreline':
        raise SystemExit('--shoreline-model requires --hmc-method shoreline')
    if args.hmc_method:
        hmc = args.shoreline_model or args.hmc_method
        return [selection_for_config(hmc, args.sdc_method)]
    return list(default_preview_selections())


def main(argv=None):
    args = _build_parser().parse_args(argv)
    selections = _selections(args)

    from bids import BIDSLayout

    layout = BIDSLayout(args.bids_dir, validate=False)
    subjects = args.participant_label or layout.get_subjects()
    if not subjects:
        print(f'No subjects found in {args.bids_dir}', file=sys.stderr)
        return 1

    policy = GroupingPolicy(
        separate_all_dwis=args.separate_all_dwis,
        ignore_fieldmaps=args.ignore_fieldmaps,
        ignore_shims=args.ignore_shims,
        ignore_fov=args.ignore_fov,
        force_t2wreg='t2wreg' in args.force,
        use_synb0=args.use_synb0,
        distortion_group_merge=args.distortion_group_merge,
    )

    if args.serve:
        if args.html:
            raise SystemExit('--serve and --html are mutually exclusive')
        from qsiplan.serve import ExplorerApp, run_server

        app = ExplorerApp(
            layout,
            subjects,
            session_id=args.session_id,
            base_policy=policy,
            initial_selection=selections[0] if args.hmc_method else None,
        )
        return run_server(app, port=args.port)

    exit_code = 0
    for subject in subjects:
        query = {
            'subject': subject,
            'suffix': 'dwi',
            'extension': ['.nii', '.nii.gz'],
            'return_type': 'file',
        }
        if args.session_id:
            query['session'] = args.session_id
        subject_data = {'dwi': sorted(layout.get(**query))}
        if not subject_data['dwi']:
            print(f'sub-{subject}: no DWI files found, skipping.\n')
            continue

        # One fieldmaps-included index pass serves the terminal report and
        # (via record filtering) every policy the HTML page can select.
        records, index_issues = index_subject(layout, subject_data)
        grouping = build_for_policy(records, subject, policy, index_issues)
        print(report_text(grouping))
        for selection in selections:
            print(describe_processing(grouping, selection))
        multi = len(subjects) > 1
        if args.html:
            path = _per_subject_path(args.html, subject, multi)
            page = render_explorer_html(
                records,
                subject,
                index_issues=index_issues,
                initial_policy=policy,
                initial_selection=selections[0] if args.hmc_method else None,
            )
            with open(path, 'w') as fobj:
                fobj.write(page)
            print(f'sub-{subject}: wrote {path}')
        if grouping.errors:
            exit_code = 1

    return exit_code


if __name__ == '__main__':
    sys.exit(main())
