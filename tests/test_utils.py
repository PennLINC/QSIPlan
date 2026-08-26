"""Unit tests for the BIDS skeleton generator."""

from qsiplan.metadata import read_bvals_bvecs
from qsiplan.utils import generate_bids_skeleton

#: One DWI series whose gradients are declared inline: a flat ``.bval`` row
#: and a three-row (x/y/z) ``.bvec`` table, as FSL writes them.
GRADIENT_SKELETON = {
    '01': {
        'dwi': [
            {'dir': 'AP', 'suffix': 'dwi', 'extension': '.nii.gz'},
            {'dir': 'AP', 'suffix': 'dwi', 'extension': '.bval', 'content': [0, 1000, 2000]},
            {
                'dir': 'AP',
                'suffix': 'dwi',
                'extension': '.bvec',
                'content': [[0, 1, 0], [0, 0, 1], [0, 0, 0]],
            },
        ]
    }
}


def _dwi_dir(tmp_path, name='skeleton'):
    generate_bids_skeleton(str(tmp_path / name), GRADIENT_SKELETON)
    return tmp_path / name / 'sub-01' / 'dwi'


def test_gradient_content_written_as_fsl_text(tmp_path):
    dwi_dir = _dwi_dir(tmp_path)
    assert (dwi_dir / 'sub-01_dir-AP_dwi.bval').read_text() == '0 1000 2000\n'
    assert (dwi_dir / 'sub-01_dir-AP_dwi.bvec').read_text() == '0 1 0\n0 0 1\n0 0 0\n'


def test_gradients_round_trip_through_the_reader(tmp_path):
    """The three rows written are read back as three (x, y, z) volumes."""
    dwi_dir = _dwi_dir(tmp_path)
    bvals, bvecs = read_bvals_bvecs(
        str(dwi_dir / 'sub-01_dir-AP_dwi.bval'), str(dwi_dir / 'sub-01_dir-AP_dwi.bvec')
    )
    assert bvals.tolist() == [0.0, 1000.0, 2000.0]
    assert bvecs.tolist() == [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]


def test_string_content_is_written_verbatim(tmp_path):
    skeleton = {'01': {'dwi': [{'suffix': 'dwi', 'extension': '.bval', 'content': '0 5 5\n'}]}}
    generate_bids_skeleton(str(tmp_path / 'strings'), skeleton)
    assert (tmp_path / 'strings' / 'sub-01' / 'dwi' / 'sub-01_dwi.bval').read_text() == '0 5 5\n'


def test_files_without_content_stay_empty(tmp_path):
    """Data files are zero-byte placeholders unless the skeleton says otherwise."""
    assert (_dwi_dir(tmp_path) / 'sub-01_dir-AP_dwi.nii.gz').stat().st_size == 0
