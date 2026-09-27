"""Convert one or more CS HDF5 recordings into MATLAB structs of columns."""
from pathlib import Path
import h5py
import numpy as np
from scipy.io import savemat

MAT5_LIMIT = 2**31 - 1


def _value(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.ndarray) and value.dtype.kind == "O":
        return np.array([_value(x) for x in value], dtype=object)
    return value


def _group(group, *, include_groups=None, include_meta=True):
    result = ({"meta": {key: _value(value) for key, value in group.attrs.items()}}
              if include_meta else {})
    for name, node in group.items():
        if include_groups is not None and group.name == "/" and name not in include_groups:
            continue
        if isinstance(node, h5py.Group):
            result[name] = _group(node, include_groups=include_groups, include_meta=include_meta)
        else:
            data = node[()]
            if node.dtype.names:
                result[name] = {field: _value(data[field]) for field in node.dtype.names}
                if include_meta and node.attrs:
                    result[name]["meta"] = {k: _value(v) for k, v in node.attrs.items()}
            else:
                result[name] = _value(data)
    return result


HOST_LOG_FIELDS = ("timestamp", "level", "source", "text")


def _host_log(file):
    """``/host_log`` as a 1xN MATLAB struct array (``text`` and ``source`` as char rows).

    Empty (1x0) when the recording has no host messages, so MATLAB code can always index it.
    """
    dtype = [(name, object) for name in HOST_LOG_FIELDS]
    table = file["host_log"][()] if "host_log" in file else ()
    result = np.empty((1, len(table)), dtype=dtype)
    for column, row in enumerate(table):
        result[0, column] = (float(row["t_host"]), int(row["level"]),
                             str(_value(row["source"])), str(_value(row["text"])))
    return result


def convert(source, output=None, *, include_raw=False, include_groups=None, include_meta=True, v73=False):
    source = Path(source)
    output = Path(output) if output else source.with_suffix(".mat")
    if source.resolve() == output.resolve():
        raise ValueError("MAT output must differ from the input recording")
    if output.exists():
        raise ValueError(f"Output already exists: {output}")
    with h5py.File(source, "r") as file:
        # A top-level struct is itself a MAT variable. Check its aggregate storage
        # before reading datasets, including the heap storage of variable-length data.
        def size(node):
            if isinstance(node, h5py.Dataset):
                return max(node.size * node.dtype.itemsize, node.id.get_storage_size())
            return sum(size(child) for child in node.values())
        selected_groups = (set(include_groups) if include_groups is not None
                           else {name for name in file if include_raw or name != "raw"})
        if not v73 and any(size(node) >= MAT5_LIMIT for name, node in file.items()
                           if name in selected_groups):
            raise ValueError("MAT v5 variable exceeds 2 GB; use MATLAB h5read or MAT v7.3 (hdf5storage)")
        description = _value(file.attrs.get("description", ""))
        data = _group(file, include_groups=selected_groups, include_meta=include_meta)
        # Keep this as a MATLAB char row rather than a MATLAB string object;
        # old MATLAB releases and Octave both load it consistently.
        description = str(description)
        data["description"] = (np.empty((1, 0), dtype="U1") if not description
                                else np.asarray([list(description)], dtype="U1"))
        if include_groups is None or "host_log" in include_groups:
            data["host_log"] = _host_log(file)
    if v73:
        try:
            import hdf5storage
        except ImportError as error:
            raise ValueError("Install hdf5storage for MAT v7.3") from error
        hdf5storage.savemat(str(output), data, format="7.3", store_python_metadata=False)
    else:
        savemat(output, data, do_compression=True, long_field_names=True, oned_as="column")
    return output
