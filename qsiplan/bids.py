# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:
#
# Copied recent function write_bidsignore
#
# Copyright The NiPreps Developers <nipreps@gmail.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# We support and encourage derived works from this project, please read
# about our expectations at
#
#     https://www.nipreps.org/community/licensing/
#
"""
Utilities to handle BIDS inputs
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Fetch some test data

    >>> import os
    >>> from niworkflows import data
    >>> data_root = data.get_bids_examples(variant='BIDS-examples-1-enh-ds054')
    >>> os.chdir(data_root)

"""

from pathlib import Path


def find_bids_root(path):
    """Locate the root of the BIDS dataset containing ``path``.

    Parameters
    ----------
    path : :obj:`str` or :obj:`pathlib.Path`
        A file inside a BIDS dataset.

    Returns
    -------
    :obj:`pathlib.Path` or None
        The closest ancestor directory holding a ``dataset_description.json``,
        or ``None`` if ``path`` is not inside a BIDS dataset.
    """
    for parent in Path(path).resolve().parents:
        if (parent / 'dataset_description.json').is_file():
            return parent

    return None


def _parse_bids_name(path):
    """Split a BIDS filename into its entities, suffix and extension.

    Parameters
    ----------
    path : :obj:`str` or :obj:`pathlib.Path`
        A BIDS-style filename. It need not exist.

    Returns
    -------
    entities : :obj:`dict`
        Mapping of entity key to entity value, e.g. ``{'sub': '01', 'part': 'mag'}``.
    suffix : :obj:`str` or None
        The BIDS suffix, e.g. ``'dwi'``. ``None`` if the name carries no suffix.
    extension : :obj:`str`
        Everything from the first period of the filename onward, e.g. ``'.nii.gz'``.
    """
    name = Path(path).name
    stem, _, remainder = name.partition('.')
    extension = f'.{remainder}' if remainder else ''

    entities = {}
    suffix = None
    for chunk in stem.split('_'):
        key, sep, value = chunk.partition('-')
        if sep:
            entities[key] = value
        else:
            # The only chunk without a "-" is the suffix, which comes last.
            suffix = chunk

    return entities, suffix, extension


def _inheritance_levels(path):
    """List the directories that may hold files applicable to ``path``.

    The BIDS inheritance principle lets files sitting in a data file's ancestor
    directories apply to it. Directories are returned shallowest-first, so that
    values from more specific files can overwrite less specific ones.

    Files that are not inside a BIDS dataset -- for instance, images that have
    already been copied into a working directory -- only ever match files
    sitting beside them.
    """
    path = Path(path).resolve()
    root = find_bids_root(path)
    if root is None:
        return [path.parent]

    # ``reversed(path.parents)`` runs shallowest-first and ends at ``path.parent``.
    return [root] + [parent for parent in reversed(path.parents) if root in parent.parents]


def find_associated_files(path, extension):
    """Find the files that apply to ``path`` under the BIDS inheritance principle.

    A file applies to ``path`` when it has the same suffix, the requested
    extension, and a set of entities that is a subset of ``path``'s entities
    with identical values. For example, ``sub-01_dwi.bval`` applies to both
    ``sub-01_part-mag_dwi.nii.gz`` and ``sub-01_part-phase_dwi.nii.gz``, while
    ``sub-01_part-mag_dwi.bval`` applies to neither of the other two.

    Parameters
    ----------
    path : :obj:`str` or :obj:`pathlib.Path`
        The data file whose associated files are wanted.
    extension : :obj:`str`
        The extension to look for, including the leading period, e.g. ``'.json'``.

    Returns
    -------
    :obj:`list` of :obj:`pathlib.Path`
        Applicable files ordered from the dataset root down to ``path``'s own
        directory, so the last element is the most specific one.

    Raises
    ------
    ValueError
        If more than one applicable file is found in a single directory, which
        the BIDS specification forbids.
    """
    target_entities, target_suffix, _ = _parse_bids_name(path)

    associated_files = []
    for level in _inheritance_levels(path):
        if not level.is_dir():
            continue

        matches = []
        for candidate in sorted(level.iterdir()):
            if not candidate.is_file():
                continue

            entities, suffix, candidate_extension = _parse_bids_name(candidate)
            if candidate_extension != extension or suffix != target_suffix:
                continue

            if all(target_entities.get(key) == value for key, value in entities.items()):
                matches.append(candidate)

        if len(matches) > 1:
            raise ValueError(
                f'Multiple {extension} files in {level} apply to {path}: '
                f'{", ".join(match.name for match in matches)}. '
                'The BIDS inheritance principle allows at most one per directory.'
            )

        associated_files.extend(matches)

    return associated_files


def find_bval(path):
    """Find the b-value file that applies to a BIDS file.

    Parameters
    ----------
    path : :obj:`str` or :obj:`pathlib.Path`
        The data file whose b-values are wanted.

    Returns
    -------
    :obj:`str` or None
        Path to the most specific applicable ``.bval`` file, or ``None`` if
        there is not one.
    """
    bval_files = find_associated_files(path, '.bval')

    return str(bval_files[-1]) if bval_files else None


def find_bvec(path):
    """Find the b-vector file that applies to a BIDS file.

    Parameters
    ----------
    path : :obj:`str` or :obj:`pathlib.Path`
        The data file whose b-vectors are wanted.

    Returns
    -------
    :obj:`str` or None
        Path to the most specific applicable ``.bvec`` file, or ``None`` if
        there is not one.
    """
    bvec_files = find_associated_files(path, '.bvec')

    return str(bvec_files[-1]) if bvec_files else None
