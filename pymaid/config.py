#    This script is part of pymaid (http://www.github.com/navis-org/pymaid).
#    Copyright (C) 2017 Philipp Schlegel
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.

import logging
import os

import numpy as np

from functools import lru_cache

logger = logging.getLogger('pymaid')

def default_logging():
    logger.setLevel(logging.INFO)
    if len(logger.handlers) == 0:
        sh = logging.StreamHandler()
        sh.setLevel(logging.DEBUG)
        # Create formatter and add it to the handlers
        formatter = logging.Formatter('%(levelname)-5s : %(message)s (%(name)s)')
        sh.setFormatter(formatter)
        logger.addHandler(sh)


NAVIS_SKIP_LOG_SETUP = os.environ.get("NAVIS_SKIP_LOG_SETUP", "").lower() == "true"

if not NAVIS_SKIP_LOG_SETUP:
    default_logging()


def get_logger(module_name: str):
    if NAVIS_SKIP_LOG_SETUP:
        return logging.getLogger(module_name)
    return logger


# Default settings for progress bars
pbar_hide = False
pbar_leave = False

# Default setting for igraph:
#   If True, will use iGraph if possible
#   If False, will ignore iGraph even if present
# Primarily used for debugging
use_igraph = True

# Default color for neurons
default_color = (.95, .65, .04)

# Default data types for nodes and connectors
node_dtypes = {'node_id': np.int64,
               'parent_id': np.int64,
               'creator_id': 'category',
               'x': np.float32,
               'y': np.float32,
               'z': np.float32,
               'radius': np.float32,
               'confidence': 'category'}
connector_dtypes = {'node_id': np.int64,
                    'type': 'category',
                    'connector_id': np.int64,
                    'x': np.float32,
                    'y': np.float32,
                    'z': np.float32}


def _type_of_script():
    """Return context in which pymaid is run."""
    try:
        ipy_str = str(type(get_ipython()))
        if 'zmqshell' in ipy_str:
            return 'jupyter'
        if 'terminal' in ipy_str:
            return 'ipython'
    except BaseException:
        return 'terminal'


def is_jupyter():
    """Test if pymaid is run in a Jupyter notebook."""
    return _type_of_script() == 'jupyter'


def ipywidgets_installed():
    """Test if ipywidgets are installed."""
    try:
        import ipywidgets
        return True
    except ImportError:
        return False
    except BaseException as e:
        logger.error('Error importing ipytwidgets: {}'.format(str(e)))
        return False


# Here, we import tqdm and determine whether we use classic notebook tbars
from tqdm import tqdm_notebook, tnrange
from tqdm import tqdm as tqdm_classic
from tqdm import trange as trange_classic

# Keep this because `tqdm_notebook` is only a wrapper (type "function")
tqdm_class = tqdm_classic

if is_jupyter() and ipywidgets_installed():
    from tqdm import tqdm_notebook, tnrange
    tqdm = tqdm_notebook
    trange = tnrange
else:
    tqdm = tqdm_classic
    trange = trange_classic

compact_skeleton_relations = {0: 'presynaptic_to',
                              1: 'postsynaptic_to',
                              2: 'gapjunction_with',
                              3: 'abutting'}

@lru_cache
def get_link_types(remote_instance):
    return remote_instance.fetch(remote_instance._get_connector_types_url())