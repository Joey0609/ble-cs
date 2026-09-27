import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import h5py
from scipy.io import loadmat
from ble_channel_sounding.h5_to_mat import convert


class MatTests(unittest.TestCase):
    def test_columns_fixed_arrays_and_size_limit(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'data.h5'
            with h5py.File(source, 'w') as f:
                rows = np.zeros(3, dtype=[('counter', '<u4'), ('channels', 'u1', (10,))])
                rows['counter'] = [1, 2, 3]
                f.create_dataset('reports/configuration', data=rows)
                f.attrs['note'] = 'example'
                f.attrs['description'] = 'example\nrun'
                f.create_dataset('raw/example', data=[1, 2])
            target = convert(source)
            data = loadmat(target, struct_as_record=False, squeeze_me=False)
            table = data['reports'][0, 0].configuration[0, 0]
            self.assertEqual(table.counter.shape, (3, 1))
            self.assertEqual(table.channels.shape, (3, 10))
            self.assertNotIn('raw', data)
            self.assertEqual(data['description'][0, 0], 'e')
            with self.assertRaises(ValueError):
                convert(source)
            with patch('ble_channel_sounding.h5_to_mat.MAT5_LIMIT', 1):
                with self.assertRaisesRegex(ValueError, '2 GB'):
                    convert(source, Path(directory) / 'too-large.mat')
            self.assertIn('raw', loadmat(convert(source, Path(directory) / 'raw.mat', include_raw=True)))
