"""Subject-scoped access to the small part of a BIDS dataset QSIPlan needs.

The grouping compiler accepts an existing PyBIDS-like layout for QSIPrep
integration, but the standalone application should not build a whole-dataset
SQL index before it can show one subject.  This module is that narrow boundary.
"""

from __future__ import annotations

import os.path as op
import re
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class DatasetCatalog(Protocol):
    """The dataset operations used by the standalone CLI and explorer."""

    root: Path

    def subjects(self) -> list[str]: ...

    def subject_data(self, label: str, session: str | None = None) -> dict[str, list[str]]: ...


class Bids2TableCatalog:
    """A lazy bids2table catalog that indexes only the requested subject."""

    def __init__(self, root):
        self.root = Path(root).resolve()

    def subjects(self) -> list[str]:
        """Subject labels from the root directory, without indexing their files."""
        return sorted(
            path.name[4:]
            for path in self.root.glob('sub-*')
            if re.fullmatch(r'sub-[A-Za-z0-9]+', path.name) and path.is_dir()
        )

    def subject_data(self, label: str, session: str | None = None) -> dict[str, list[str]]:
        """Relevant image files for one subject, grouped by QSIPlan input key."""
        import bids2table as b2t

        table = b2t.index_dataset(self.root, include_subjects=f'sub-{label}')
        return self._subject_data_from_table(table, [label], session)[label]

    def iter_subject_data(self, labels, session: str | None = None, batch_size: int = 512):
        """Yield subject data from bounded multi-subject index batches."""
        import bids2table as b2t

        labels = list(labels)
        for start in range(0, len(labels), batch_size):
            batch = labels[start : start + batch_size]
            table = b2t.index_dataset(
                self.root,
                include_subjects=[f'sub-{label}' for label in batch],
            )
            data = self._subject_data_from_table(table, batch, session)
            yield from ((label, data[label]) for label in batch)

    def _subject_data_from_table(self, table, labels, session):
        import pyarrow as pa
        import pyarrow.compute as pc

        result = {label: {'dwi': [], 'fmap': [], 't1w': [], 't2w': []} for label in labels}
        if not table.num_rows:
            return result

        mask = pc.and_(
            pc.is_in(table['datatype'], value_set=pa.array(['dwi', 'fmap', 'anat'])),
            pc.is_in(table['ext'], value_set=pa.array(['.nii', '.nii.gz'])),
        )
        if session is not None:
            mask = pc.and_(mask, pc.equal(table['ses'], session))
        rows = table.filter(mask).select(['sub', 'datatype', 'suffix', 'path']).to_pylist()

        for row in rows:
            key = None
            if row['datatype'] == 'dwi' and row['suffix'] == 'dwi':
                key = 'dwi'
            elif row['datatype'] == 'fmap':
                key = 'fmap'
            elif row['datatype'] == 'anat' and row['suffix'] in ('T1w', 'T2w'):
                key = row['suffix'].lower()
            if key is not None and row['sub'] in result:
                result[row['sub']][key].append(str(self.root / row['path']))

        return {
            label: {key: sorted(paths) for key, paths in data.items()}
            for label, data in result.items()
        }


def collect_subject_data(source, label: str, session: str | None = None):
    """Collect one subject through a catalog or a legacy layout-like object."""
    if isinstance(source, DatasetCatalog):
        return source.subject_data(label, session)

    query = {
        'subject': label,
        'suffix': 'dwi',
        'extension': ['.nii', '.nii.gz'],
        'return_type': 'file',
    }
    if session:
        query['session'] = session
    return {'dwi': sorted(op.abspath(path) for path in source.get(**query))}
