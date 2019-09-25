#    This script is part of pymaid (http://www.github.com/schlegelp/pymaid).
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
#
#    You should have received a copy of the GNU General Public License
#    along

import collections
import csv
from glob import glob
import itertools
import json
import os
import random
import six
import sys
import warnings

import pandas as pd
import numpy as np

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import vispy.visuals

from . import core, fetch, config

# Set up logging
logger = config.logger

__all__ = ['neuron2json', 'json2neuron', 'from_swc', 'to_swc',
           'set_loggers', 'set_pbars', 'eval_skids', 'clear_cache',
           'shorten_name']


def clear_cache():
    """ Clear cache of global CatmaidInstance. """
    if 'remote_instance' in sys.modules:
        rm = sys.modules['remote_instance']
    elif 'remote_instance' in globals():
        rm = globals()['remote_instance']
    else:
        raise ValueError('No global CatmaidInstance found.')

    rm.clear_cache()


def _type_of_script():
    """ Returns context in which pymaid is run. """
    try:
        ipy_str = str(type(get_ipython()))
        if 'zmqshell' in ipy_str:
            return 'jupyter'
        if 'terminal' in ipy_str:
            return 'ipython'
    except BaseException:
        return 'terminal'


def is_jupyterlab():
    """Test if we are inside Jupyter lab."""
    import psutil
    return any(['jupyter-lab' in x for x in psutil.Process().parent().cmdline()])


def has_plotly_extension():
    """Check if Jupyter lab plotly renderer extension is installed."""
    import subprocess
    # This is the old plotly renderer
    result = subprocess.run(['jupyter',
                             'labextension',
                             'check',
                             '@jupyterlab/plotly-extension'])
    if result.returncode == 0:
        return True

    # This is the new one
    result = subprocess.run(['jupyter',
                             'labextension',
                             'check',
                             'jupyterlab-plotly'])
    if result.returncode == 0:
        return True
    return False


def is_headless():
    """Check if Display is available."""
    return 'DISPLAY' in os.environ


def is_jupyter():
    """ Test if pymaid is run in a Jupyter notebook."""
    return _type_of_script() == 'jupyter'


def ipywidgets_installed():
    """ Test if pymaid is run in a Jupyter notebook."""
    try:
        import ipywidgets
        return True
    except ImportError:
        return False
    except BaseException as e:
        logger.error('Error importing ipytwidgets: {}'.format(str(e)))


def set_loggers(level='INFO'):
    """Helper function to set levels for all associated module loggers."""
    config.logger.setLevel(level)


def set_pbars(hide=None, leave=None, jupyter=None):
    """ Set global progress bar behaviors.

    Parameters
    ----------
    hide :      bool, optional
                Set to True to hide all progress bars.
    leave :     bool, optional
                Set to False to clear progress bars after they have finished.
    jupyter :   bool, optional
                Set to False to force using of classic tqdm even if in
                Jupyter environment.

    Returns
    -------
    Nothing

    """

    if isinstance(hide, bool):
        config.pbar_hide = hide

    if isinstance(leave, bool):
        config.pbar_leave = leave

    if isinstance(jupyter, bool):
        if jupyter:
            if not is_jupyter():
                logger.error('Unable to use fancy Jupyter progress: '
                             'No Jupyter environment detected.')
            elif not ipywidgets_installed():
                logger.error('Unable to use fancy Jupyter progress: '
                             'ipywidgets not installed .')
            else:
                config.tqdm = config.tqdm_notebook
                config.trange = config.tnrange
        else:
            config.tqdm = config.tqdm_classic
            config.trange = config.trange_classic


def _make_iterable(x, force_type=None):
    """ Helper function. Turns x into a np.ndarray, if it isn't already. For
    dicts, keys will be turned into array.
    """
    if not isinstance(x, collections.Iterable) or isinstance(x, six.string_types):
        x = [x]

    if isinstance(x, dict):
        x = list(x)

    if force_type:
        return np.array(x).astype(force_type)
    else:
        return np.array(x)


def _make_non_iterable(x):
    """ Helper function. Turns x into non-iterable, if it isn't already. Will
    raise error if len(x) > 1.
    """
    if not _is_iterable(x):
        return x
    elif len(x) == 1:
        return x[0]
    else:
        raise ValueError('Iterable must not contain more than one entry.')


def _is_iterable(x):
    """ Helper function. Returns True if x is an iterable but not str,
    dictionary or pandas DataFrame.
    """
    if isinstance(x, collections.Iterable) and not isinstance(x, (six.string_types, pd.DataFrame)):
        return True
    else:
        return False


def _eval_conditions(x):
    """ Splits list of strings into positive (no ~) and negative (~) conditions
    """

    x = _make_iterable(x, force_type=str)

    return [i for i in x if not i.startswith('~')], [i[1:] for i in x if i.startswith('~')]


def neuron2json(x, **kwargs):
    """ Generate JSON formatted ``str`` respresentation of CatmaidNeuron/List.

    Nodes and connectors are serialised using pandas' ``to_json()``. Most
    other items in the neuron's __dict__ are serialised using
    ``json.dumps()``. Properties not serialised: `._remote_instance`,
    `.graph`, `.igraph`.

    Important
    ---------
    For safety, the :class:`~pymaid.CatmaidInstance` is not serialised as
    this would expose your credentials. Parameters attached to a neuronlist
    are currently not preserved.

    Parameters
    ----------
    x :         CatmaidNeuron | CatmaidNeuronList
    **kwargs
                Parameters passed to ``json.dumps()`` and
                ``pandas.DataFrame.to_json()``.

    Returns
    -------
    str

    See Also
    --------
    :func:`~pymaid.json2neuron`
                Read json back into pymaid neurons.

    """

    if not isinstance(x, (core.CatmaidNeuron, core.CatmaidNeuronList)):
        raise TypeError('Unable to convert data of type "{0}"'.format(type(x)))

    if isinstance(x, core.CatmaidNeuron):
        x = core.CatmaidNeuronList([x])

    data = []
    for n in x:
        this_data = {'skeleton_id': n.skeleton_id}

        if 'nodes' in n.__dict__:
            this_data['nodes'] = n.nodes.to_json()

        if 'connectors' in n.__dict__:
            this_data['connectors'] = n.connectors.to_json(**kwargs)

        for k in n.__dict__:
            if k in ['nodes', 'connectors', 'graph', 'igraph', '_remote_instance',
                     'segments', 'small_segments', 'nodes_geodesic_distance_matrix',
                     'dps', 'simple']:
                continue
            try:
                this_data[k] = n.__dict__[k]
            except:
                logger.error('Lost attribute "{0}"'.format(k))

        data.append(this_data)

    return json.dumps(data, **kwargs)


def json2neuron(s, **kwargs):
    """ Load neuron from JSON string.

    Parameters
    ----------
    s :         str
                JSON-formatted string.
    **kwargs
                Parameters passed to ``json.loads()`` and
                ``pandas.DataFrame.read_json()``.

    Returns
    -------
    :class:`~pymaid.CatmaidNeuronList`

    See Also
    --------
    :func:`~pymaid.neuron2json`
                Turn neuron into json.

    """

    if not isinstance(s, str):
        raise TypeError('Need str, got "{0}"'.format(type(s)))

    data = json.loads(s, **kwargs)

    nl = core.CatmaidNeuronList([])

    for n in data:
        # Make sure we have all we need
        REQUIRED = ['skeleton_id']

        missing = [p for p in REQUIRED if p not in n]

        if missing:
            raise ValueError('Missing data: {0}'.format(','.join(missing)))

        cn = core.CatmaidNeuron(int(n['skeleton_id']))

        if 'nodes' in n:
            cn.nodes = pd.read_json(n['nodes'])
            cn.connectors = pd.read_json(n['connectors'])

        for key in n:
            if key in ['skeleton_id', 'nodes', 'connectors']:
                continue
            setattr(cn, key, n[key])

        nl += cn

    return nl


def _eval_remote_instance(remote_instance, raise_error=True):
    """ Evaluates remote instance and checks for globally defined remote
    instances as fall back.
    """

    if remote_instance is None:
        if 'remote_instance' in sys.modules:
            return sys.modules['remote_instance']
        elif 'remote_instance' in globals():
            return globals()['remote_instance']
        else:
            if raise_error:
                raise Exception('No pymaid.CatmaidInstance found. Please '
                                'either define globally or pass explicitly '
                                'as "remote_instance". See '
                                '`help(pymaid.CatmaidInstance) for details.')
            else:
                logger.warning('No global remote instance found.')
    elif not isinstance(remote_instance, fetch.CatmaidInstance):
        error = 'Expected None or CatmaidInstance, got {}'.format(type(remote_instance))
        if raise_error:
            raise TypeError(error)
        else:
            logger.warning(error)

    return remote_instance


def eval_skids(x, remote_instance=None, warn_duplicates=True):
    """ Evaluate skeleton IDs.

    Will turn annotations and neuron names into skeleton IDs.

    Parameters
    ----------
    x :             int | str | CatmaidNeuron | CatmaidNeuronList | DataFrame
                    Your options are either::
                    1. int or list of ints:
                        - will be assumed to be skeleton IDs
                    2. str or list of str:
                        - if convertible to int, will be interpreted as x
                        - if starts with 'annotation:' will be assumed to be
                          annotations
                        - else will be assumed to be neuron names
                    3. For CatmaidNeuron/List or pandas.DataFrames/Series:
                        - will look for ``skeleton_id`` attribute
    remote_instance :  CatmaidInstance, optional
                       If not passed directly, will try using global.
    warn_duplicates :  bool, optional
                       If True, will warn if duplicate skeleton IDs are found.
                       Only applies to CatmaidNeuronLists.

    Returns
    -------
    list
                    List containing skeleton IDs as strings.

    """

    remote_instance = _eval_remote_instance(remote_instance,
                                            raise_error=False)

    if isinstance(x, (int, np.int64, np.int32, np.int)):
        return [str(x)]
    elif isinstance(x, (str, np.str)):
        try:
            int(x)
            return [str(x)]
        except BaseException:
            if x.startswith('annotation:') or x.startswith('annotations:'):
                an = x[x.index(':') + 1:]
                return fetch.get_skids_by_annotation(an,
                                                     remote_instance=remote_instance)
            elif x.startswith('name:'):
                return fetch.get_skids_by_name(x[5:],
                                               remote_instance=remote_instance,
                                               allow_partial=False
                                               ).skeleton_id.tolist()
            else:
                return fetch.get_skids_by_name(x,
                                               remote_instance=remote_instance,
                                               allow_partial=False
                                               ).skeleton_id.tolist()
    elif isinstance(x, (list, np.ndarray, set)):
        skids = []
        for e in x:
            temp = eval_skids(e, remote_instance=remote_instance)
            if isinstance(temp, (list, np.ndarray)):
                skids += temp
            else:
                skids.append(temp)
        return sorted(set(skids), key=skids.index)
    elif isinstance(x, core.CatmaidNeuron):
        return [x.skeleton_id]
    elif isinstance(x, core.CatmaidNeuronList):
        if len(x.skeleton_id) != len(set(x.skeleton_id)) and warn_duplicates:
            logger.warning('Duplicate skeleton IDs found in neuronlist. '
                           'The function you are using might not respect '
                           'fragments of the same neuron. For explanation see '
                           'http://pymaid.readthedocs.io/en/latest/source/conn'
                           'ectivity_analysis.html.')
        return list(x.skeleton_id)
    elif isinstance(x, pd.DataFrame):
        if 'skeleton_id' not in x.columns:
            raise ValueError('Expect "skeleton_id" column in pandas DataFrames')
        return x.skeleton_id.tolist()
    elif isinstance(x, pd.Series):
        if x.name == 'skeleton_id':
            return x.tolist()
        elif 'skeleton_id' in x:
            return [x.skeleton_id]
        else:
            raise ValueError('Unable to extract skeleton ID from Pandas '
                             'series {0}'.format(x))
    elif isinstance(x, type(None)):
        return None
    else:
        logger.error(
            'Unable to extract x from type %s' % str(type(x)))
        raise TypeError('Unable to extract skids from type %s' % str(type(x)))


def eval_user_ids(x, user_list=None, remote_instance=None):
    """ Checks a list of users and turns them into user IDs.

    Always returns a list! Will attempt converting in the following order:

        (1) user ID
        (2) login name
        (3) last name
        (4) full name
        (5) first name

    Important
    ---------
    Last, first and full names are case-sensitive!

    Parameters
    ----------
    x :         int | str | list of either
                Users to check.
    user_list : pd.DataFrame, optional
                User list from :func:`~pymaid.get_user_list`. If you
                already have it, pass it along to save time.

    """

    remote_instance = _eval_remote_instance(remote_instance)

    if x and not isinstance(x, (list, np.ndarray)):
        x = [x]

    try:
        # Test if we have any non IDs (i.e. logins) in users
        user_ids = [int(u) for u in x]
    except BaseException:
        # Get list of users if we don't already have it
        if not user_list:
            user_list = fetch.get_user_list(
                remote_instance=remote_instance)

        # Now convert individual entries to user IDs
        user_ids = []
        for u in x:
            try:
                user_ids.append(int(u))
            except BaseException:
                for col in ['login', 'last_name', 'full_name', 'first_name']:
                    found = []
                    if u in user_list[col].values:
                        found = user_list[user_list[col] == u].id.tolist()
                        break
                if not found:
                    logger.warning(
                        'User "{0}" not found. Skipping...'.format(u))
                elif len(found) > 1:
                    logger.warning('Multiple matching entries for '
                                   '"{0}" found. Skipping...'.format(u))
                else:
                    user_ids.append(int(found[0]))

    return user_ids


def eval_node_ids(x, connectors=True, treenodes=True):
    """ Extract treenode or connector IDs.

    Parameters
    ----------
    x :             int | str | CatmaidNeuron | CatmaidNeuronList | DataFrame
                    Your options are either::
                    1. int or list of ints will be assumed to be node IDs
                    2. str or list of str will be checked if convertible to int
                    3. For CatmaidNeuron/List or pandas.DataFrames will try
                       to extract node IDs
    connectors :    bool, optional
                    If True will return connector IDs from neuron objects
    treenodes :     bool, optional
                    If True will return treenode IDs from neuron objects

    Returns
    -------
    list
                    List containing nodes as strings.

    """

    if isinstance(x, (int, np.int64, np.int32, np.int)):
        return [x]
    elif isinstance(x, (str, np.str)):
        try:
            return [int(x)]
        except BaseException:
            raise TypeError(
                'Unable to extract node ID from string <%s>' % str(x))
    elif isinstance(x, (set, list, np.ndarray)):
        # Check non-integer entries
        ids = []
        for e in x:
            temp = eval_node_ids(e, connectors=connectors,
                                 treenodes=treenodes)
            if isinstance(temp, (list, np.ndarray)):
                ids += temp
            else:
                ids.append(temp)
        # Preserving the order after making a set is super costly
        # return sorted(set(ids), key=ids.index)
        return list(set(ids))
    elif isinstance(x, core.CatmaidNeuron):
        to_return = []
        if treenodes:
            to_return += x.nodes.treenode_id.tolist()
        if connectors:
            to_return += x.connectors.connector_id.tolist()
        return to_return
    elif isinstance(x, core.CatmaidNeuronList):
        to_return = []
        for n in x:
            if treenodes:
                to_return += n.nodes.treenode_id.tolist()
            if connectors:
                to_return += n.connectors.connector_id.tolist()
        return to_return
    elif isinstance(x, (pd.DataFrame, pd.Series)):
        to_return = []
        if treenodes and 'treenode_id' in x:
            to_return += x.treenode_id.tolist()
        if connectors and 'connector_id' in x:
            to_return += x.connector_id.tolist()

        if 'connector_id' not in x and 'treenode_id' not in x:
            to_return = x.tolist()

        return to_return
    else:
        raise TypeError(
            'Unable to extract node IDs from type %s' % str(type(x)))


def _unpack_neurons(x, raise_on_error=True):
    """ Unpacks neurons and returns a list of individual neurons.
    """

    neurons = []

    if isinstance(x, (list, np.ndarray, tuple)):
        for l in x:
            neurons += _unpack_neurons(l)
    elif isinstance(x, core.CatmaidNeuron):
        neurons.append(x)
    elif isinstance(x, core.CatmaidNeuronList):
        neurons += x.neurons
    elif raise_on_error:
        raise TypeError('Unknown neuron format: "{}"'.format(type(x)))

    return neurons


def _parse_objects(x, remote_instance=None):
    """ Helper class to extract objects for plotting.

    Returns
    -------
    skids :     list
    skdata :    pymaid.CatmaidNeuronList
    dotprops :  pd.DataFrame
    volumes :   list
    points :    list of arrays
    visuals :   list of vispy visuals
    """

    if not isinstance(x, list):
        x = [x]

    # If any list in x, flatten first
    if any([isinstance(i, list) for i in x]):
        # We need to be careful to preserve order because of colors
        y = []
        for i in x:
            y += i if isinstance(i, list) else [i]
        x = y

    # Check for skeleton IDs
    skids = []
    for ob in x:
        if isinstance(ob, (str, int)):
            try:
                skids.append(int(ob))
            except BaseException:
                pass

    # Collect neuron objects and collate to single Neuronlist
    neuron_obj = [ob for ob in x if isinstance(ob,
                                               (core.CatmaidNeuron,
                                                core.CatmaidNeuronList))]
    skdata = core.CatmaidNeuronList(neuron_obj, make_copy=False)

    # Collect visuals
    visuals = [ob for ob in x if isinstance(ob, vispy.visuals.Visual)]

    # Collect dotprops
    dotprops = [ob for ob in x if isinstance(ob, core.Dotprops)]

    if len(dotprops) == 1:
        dotprops = dotprops[0]
    elif len(dotprops) == 0:
        dotprops = core.Dotprops()
        dotprops['gene_name'] = []
    elif len(dotprops) > 1:
        dotprops = pd.concat(dotprops)

    # Collect and parse volumes
    volumes = [ob for ob in x if isinstance(ob, (core.Volume, str))]

    # Collect dataframes with X/Y/Z coordinates
    # Note: dotprops and volumes are instances of pd.DataFrames
    dataframes = [ob for ob in x if isinstance(ob, pd.DataFrame) and not isinstance(ob, (core.Dotprops, core.Volume))]
    if [d for d in dataframes if False in [c in d.columns for c in ['x', 'y', 'z']]]:
        logger.warning('DataFrames must have x, y and z columns.')
    # Filter to and extract x/y/z coordinates
    dataframes = [d for d in dataframes if False not in [c in d.columns for c in ['x', 'y', 'z']]]
    dataframes = [d[['x', 'y', 'z']].values for d in dataframes]

    # Collect arrays
    arrays = [ob.copy() for ob in x if isinstance(ob, np.ndarray)]
    # Remove arrays with wrong dimensions
    if [ob for ob in arrays if ob.shape[1] != 3]:
        logger.warning('Point objects need to be of shape (n,3).')
    arrays = [ob for ob in arrays if ob.shape[1] == 3]

    points = dataframes + arrays

    return skids, skdata, dotprops, volumes, points, visuals


def from_swc(f, neuron_name=None, neuron_id=None, import_labels=True,
             pre_label=None, post_label=None, soma_label=1,
             include_subdirs=False):
    """ Generate neuron object from SWC file/DataFrame.

    This import is following format specified
    `here <http://www.neuronland.org/NLMorphologyConverter/MorphologyFormats/SWC/Spec.html>`_

    Important
    ---------
    Soma is inferred from radius (>0), not the label.

    Parameters
    ----------
    f :                 str | pandas.DataFrame | iterable
                        SWC string, filename, folder or DataFrame. If folder,
                        will import all ``.swc`` files.
    neuronname :        str, optional
                        Name to use for the neuron. If not provided, will use
                        filename minus extension.
    neuron_id :         int | func, optional
                        Unique identifier (essentially skeleton ID). If not
                        provided, will use filename (if numeric) or generate
                        one from scratch. If function, must accept filename
                        and return ``str``.
    import_labels :     bool, optional
                        If True, will import label column as ``.tags``
                        property of neuron.
    pre/post_label :    bool | int, optional
                        If not ``None``, will try to extract pre-/postsynapses
                        from label column.
    soma_label :        bool | int, optional
                        If not ``None``, will try to extract soma and place
                        appropriate tags on the neuron.
    include_subdirs :   bool, optional
                        If True and ``f`` is a folder, will also search
                        subdirectories for ``.swc`` files.

    Returns
    -------
    CatmaidNeuron/List

    See Also
    --------
    :func:`pymaid.to_swc`
                        Export neurons as SWC files.

    """
    if _is_iterable(f):
        return core.CatmaidNeuronList([from_swc(x,
                                                neuron_name=neuron_name,
                                                neuron_id=neuron_id,
                                                pre_label=pre_label,
                                                post_label=post_label,
                                                soma_label=soma_label,
                                                include_subdirs=include_subdirs,
                                                )
                                       for x in config.tqdm(f, desc='Importing',
                                                            disable=config.pbar_hide,
                                                            leave=config.pbar_leave)])

    header = []
    cols = ['treenode_id', 'label', 'x', 'y', 'z', 'radius', 'parent_id']
    if isinstance(f, pd.DataFrame):
        # Replace 'node_id' column with 'treenode_id'
        if 'node_id' in f.columns and 'treenode_id' not in f.columns:
            f.columns = [c.replace('node_id', 'treenode_id') for c in f.columns]

        missing = [c for c in cols if c not in f.columns]
        if missing:
            raise ValueError('SWC DataFrame is missing required columns: '
                             '{}'.format(','.join(missing)))
        nodes = f
        f = 'SWC'
    elif os.path.isdir(f):
        if not include_subdirs:
            swc = [os.path.join(f, x) for x in os.listdir(f) if
                   os.path.isfile(os.path.join(f, x)) and x.endswith('.swc')]
        else:
            swc = [y for x in os.walk(f) for y in glob(os.path.join(x[0], '*.swc'))]

        if not swc:
            raise ValueError('No .swc files found in folder "{}"'.format(f))

        return core.CatmaidNeuronList([from_swc(x,
                                                neuron_name=neuron_name,
                                                neuron_id=neuron_id,
                                                pre_label=pre_label,
                                                soma_label=soma_label,
                                                post_label=post_label)
            for x in config.tqdm(swc,
                                 desc='Reading {}'.format(f.split('/')[-1]),
                                 disable=config.pbar_hide,
                                 leave=config.pbar_leave)])
    else:
        data = []
        with open(f) as file:
            reader = csv.reader(file, delimiter=' ')
            for row in reader:
                # skip empty rows
                if not row:
                    continue
                # skip comments
                if not row[0].startswith('#'):
                    data.append(row)
                else:
                    header.append(' '.join(row))

        # Remove empty entries and generate nodes DataFrame
        nodes = pd.DataFrame([[to_float(e) for e in row if e != ''] for row in data],
                             columns=cols,
                             dtype=object)

    # Get filename
    fname = os.path.splitext(os.path.basename(f))[0]

    if not neuron_id:
        # If filename is numeric use it as skeleton ID
        if fname.isnumeric():
            neuron_id = int(fname)
        else:
            # Use 30 bit - 32bit raises error when converting to R StrVector
            neuron_id = random.getrandbits(30)
    elif callable(neuron_id):
        neuron_id = neuron_id(fname)

    if not neuron_name:
        neuron_name = fname

    # Try converting labels to int (otherwise might end up float)
    nodes.label = nodes.label.astype(int, errors='ignore')

    # If any invalid nodes are found
    if any(nodes[['treenode_id', 'parent_id', 'x', 'y', 'z']].isnull()):
        # Remove nodes without coordinates
        nodes = nodes.loc[~nodes[['treenode_id', 'parent_id', 'x', 'y', 'z']].isnull().any(axis=1)]

        # Because we removed nodes, we'll have to run a more complicated root
        # detection
        nodes.loc[~nodes.parent_id.isin(nodes.treenode_id), 'parent_id'] = None
    else:
        # Root node will have parent=-1 -> set this to None
        nodes.loc[nodes.parent_id < 0, 'parent_id'] = None

    connectors = pd.DataFrame([], columns=['treenode_id', 'connector_id',
                                           'relation', 'x', 'y', 'z'],
                              dtype=object)

    if pre_label:
        pre = nodes[nodes.label == pre_label][['treenode_id', 'x', 'y', 'z']]
        pre['connector_id'] = None
        pre['relation'] = 0
        connectors = pd.concat([connectors, pre], axis=0)

    if post_label:
        post = nodes[nodes.label == post_label][['treenode_id', 'x', 'y', 'z']]
        post['connector_id'] = None
        post['relation'] = 1
        connectors = pd.concat([connectors, post], axis=0)

    df = pd.DataFrame([[
        neuron_name,
        str(neuron_id),
        nodes,
        connectors,
        {},
    ]],
        columns=['neuron_name', 'skeleton_id',
                 'nodes', 'connectors', 'tags'],
        dtype=object
    )

    # Add confidences and creator (this is to prevent errors in other
    # functions)
    for i in range(df.shape[0]):
        df.loc[i, 'nodes']['confidence'] = 5
        df.loc[i, 'nodes']['creator_id'] = 0

    # Placeholder for graph representations of neurons
    df['igraph'] = None
    df['graph'] = None

    # Convert data to respective dtypes
    dtypes = {'treenode_id': int, 'parent_id': object, 'label': str,
              'creator_id': int, 'relation': int,
              'connector_id': object, 'x': float, 'y': float, 'z': float,
              'radius': float, 'confidence': int}

    for k, v in dtypes.items():
        for t in ['nodes', 'connectors']:
            for i in range(df.shape[0]):
                if k in df.loc[i, t]:
                    df.loc[i, t][k] = df.loc[i, t][k].astype(v, errors='ignore')

    # Generate neuron
    n = core.CatmaidNeuron(df)

    # Import labels as tags
    if import_labels:
        n.tags = n.nodes.groupby('label').treenode_id.apply(list).to_dict()

    # Make sure soma is correctly tagged (notice force convert to str)
    if soma_label:
        n.tags['soma'] = n.nodes[n.nodes.label==str(soma_label)].treenode_id.tolist()

    #n.nodes.drop('label', axis=1, inplace=True)

    # Add folder and filename to the neuron
    n.filename = fname
    n.filepath = os.path.dirname(fname)
    n.swc_header = '\n'.join(header)

    return n


def _generate_swc_table(x, export_synapses=False, min_radius=0):
    """ Generate SWC table for given neuron.

    Parameters
    ----------
    x :             CatmaidNeuron

    Returns
    -------
    swc :           pandas.DataFrame
                    SWC node table
    tn2ix :         dict
                    Dictionary mapping treenode IDs to new node indices.

    """

    # Make copy of nodes and reorder such that the parent is always before a
    # treenode
    nodes_ordered = [n for seg in x.segments for n in seg[::-1]]
    this_tn = x.nodes.set_index('treenode_id').loc[nodes_ordered]

    # Because the last treenode ID of each segment is a duplicate
    # (except for the first segment ), we have to remove them
    this_tn = this_tn[~this_tn.index.duplicated(keep='first')]

    # Add an index column (must start with "1", not "0")
    this_tn['index'] = list(range(1, this_tn.shape[0] + 1))

    # Make a dictionary treenode_id -> index
    tn2ix = this_tn['index'].to_dict()

    # Make parent index column
    this_tn['parent_ix'] = this_tn.parent_id.map(lambda x: tn2ix.get(x, -1))

    # Set Label column to 0 (undefined)
    this_tn['label'] = 0
    # Add end/branch labels
    this_tn.loc[this_tn.type == 'branch', 'label'] = 5
    this_tn.loc[this_tn.type == 'end', 'label'] = 6
    # Add soma label
    if x.soma:
        this_tn.loc[x.soma, 'label'] = 1
    if export_synapses:
        # Add synapse label
        this_tn.loc[x.presynapses.treenode_id.values, 'label'] = 7
        this_tn.loc[x.postsynapses.treenode_id.values, 'label'] = 8

    # Make sure we don't have too small radii
    if not isinstance(min_radius, type(None)):
        this_tn.loc[this_tn.radius < min_radius, 'radius'] = min_radius

    # Generate table consisting of PointNo Label X Y Z Radius Parent
    # .copy() is to prevent pandas' chaining warnings
    swc = this_tn[['index', 'label', 'x', 'y', 'z',
                   'radius', 'parent_ix']].copy()

    # Adjust column titles
    swc.columns = ['PointNo', 'Label', 'X', 'Y', 'Z', 'Radius', 'Parent']

    return swc, tn2ix


def to_swc(x, filename=None, export_synapses=False, min_radius=0):
    """ Generate SWC file from neuron(s).

    Follows the format specified
    `here <http://www.neuronland.org/NLMorphologyConverter/MorphologyFormats/SWC/Spec.html>`_.

    Important
    ---------
    Node IDs will be remapped to be continuous 1 -> ``len(x.nodes)``.

    Parameters
    ----------
    x :                 CatmaidNeuron | CatmaidNeuronList
                        If multiple neurons, will generate a single SWC file
                        for each neurons (see also ``filename``).
    filename :          None | str | list, optional
                        If ``None``, will use "neuron_{skeletonID}.swc". Pass
                        filenames as list when processing multiple neurons.
    export_synapses :   bool, optional
                        If True, will label nodes with pre- ("7") and
                        postsynapse ("8"). Because only one label can be given
                        this might drop synapses (i.e. in case of multiple
                        pre- or postsynapses on a single treenode)!
    min_radius :        int, optional
                        By default, nodes in CATMAID have a radius of -1. To
                        prevent this from causing problems in other
                        applications, set a minimum radius [nm].

    Returns
    -------
    dict
                        Mapping of old -> new node IDs.

    See Also
    --------
    :func:`pymaid.from_swc`
                        Import SWC files.

    """
    if isinstance(x, core.CatmaidNeuronList):
        if not _is_iterable(filename):
            filename = [filename] * len(x)

        for n, f in zip(x, filename):
            to_swc(n, f,
                   export_synapses=export_synapses,
                   min_radius=min_radius)

        return

    if not isinstance(x, core.CatmaidNeuron):
        raise ValueError('Can only process CatmaidNeurons, '
                         'got "{}"'.format(type(x)))

    # If not specified, generate generic filename
    if isinstance(filename, type(None)):
        filename = 'neuron_{}.swc'.format(x.skeleton_id)

    # Check if filename is of correct type
    if not isinstance(filename, str):
        raise ValueError('Filename must be str or None, '
                         'got "{}"'.format(type(filename)))

    # Make sure file ending is correct
    if os.path.isdir(filename):
        filename += 'neuron_{}.swc'.format(x.skeleton_id)
    elif not filename.endswith('.swc'):
        filename += '.swc'

    swc, tn2ix = _generate_swc_table(x,
                                     export_synapses=export_synapses,
                                     min_radius=min_radius)

    with open(filename, 'w') as file:
        # Write header
        file.write('# SWC format file\n')
        file.write('# based on specifications at http://research.mssm.edu/cnic/swc.html\n')
        file.write('# Created by pymaid (https://github.com/schlegelp/PyMaid)\n')
        file.write('# PointNo Label X Y Z Radius Parent\n')
        file.write('# Labels:\n')
        for l in ['0 = undefined', '1 = soma', '5 = fork point', '6 = end point']:
            file.write('# {}\n'.format(l))
        if export_synapses:
            for l in ['7 = presynapse', '8 = postsynapse']:
                file.write('# {}\n'.format(l))
        # file.write('\n')

        writer = csv.writer(file, delimiter=' ')
        writer.writerows(swc.astype(str).values)

    return tn2ix


def __guess_sentiment(x):
    """ Tries to classify a list of words into either <type>, <nickname>,
    <tracer> or <generic> annotations.
    """

    sent = []
    for i, w in enumerate(x):
        # If word is a number, it's most likely something generic
        if w.isdigit():
            sent.append('generic')
        elif w == 'neuron':
            # If there is a lonely "neuron" followed by a number, it's generic
            if i != len(x) and x[i + 1].isdigit():
                sent.append('generic')
            # If not, it's probably type
            else:
                sent.append('type')
        # If there is a short, all upper case word after the generic information
        elif w.isupper() and len(w) > 1 and w.isalpha() and 'generic' in sent:
            # If there is no number in that word, it's probably tracer initials
            sent.append('tracer')
        else:
            # If the word is AFTER the generic number, it's probably a nickname
            if 'generic' in sent:
                sent.append('nickname')
            # If not, it's likely type information
            else:
                sent.append('type')

    return sent


def parse_neuronname(x):
    """ Tries parsing neuron names into type, nickname, tracer and generic
    information.

    This works best if neuron name follows this convention::

    '{type} {generic} {nickname} {tracer initials}'

    Parameters
    ----------
    x :     str | CatmaidNeuron
            Neuron name.

    Returns
    -------
    type :          str
    nickname :      str
    tracer :        str
    generic :       str

    Examples
    --------
    >>> pymaid.utils.parse_neuronname('AD1b2#7 3080184 Dust World JJ PS')
    ('AD1b2#7', 'Dust World', 'JJ PS', '3080184')
    """

    if isinstance(x, core.CatmaidNeuron):
        x = x.neuron_name

    if not isinstance(x, str):
        raise TypeError('Unable to parse name: must be str, not {}'.format(type(x)))

    # Split name into single words
    words = x.split(' ')
    sentiments = __guess_sentiment(words)

    type_str = [w for w, s in zip(words, sentiments) if s == 'type']
    nick_str = [w for w, s in zip(words, sentiments) if s == 'nickname']
    tracer_str = [w for w, s in zip(words, sentiments) if s == 'tracer']
    gen_str = [w for w, s in zip(words, sentiments) if s == 'generic']

    return ' '.join(type_str), ' '.join(nick_str), ' '.join(tracer_str), ' '.join(gen_str)


def shorten_name(x, max_len=30):
    """ Shorten a neuron name by iteratively removing non-essential
    information.

    Prioritises generic -> tracer -> nickname -> type information when removing
    until target length is reached. This works best if neuron name follows
    this convention::

    '{type} {generic} {nickname} {tracers}'

    Parameters
    ----------
    x :         str | CatmaidNeuron
                Neuron name.
    max_len :   int, optional
                Max length of shortened name.

    Returns
    -------
    shortened name :    str

    Examples
    --------
    >>> pymaid.shorten_name('AD1b2#7 3080184 Dust World JJ PS', 30)
    'AD1b2#7 Dust World [..]'
    """

    if isinstance(x, core.CatmaidNeuron):
        x = x.neuron_name

    # Split into individual words and guess their type
    words = x.split(' ')
    sentiments = __guess_sentiment(words)

    # Make sure we're working on a copy of the original neuron name
    short = str(x)

    ty = ['generic', 'tracer', 'nickname', 'type']
    # Iteratively remove generic -> tracer -> nickname -> type information
    for t, (w, sent) in itertools.product(ty, zip(words[::-1], sentiments[::-1])):
        # Stop if we are below max length
        if len(short) <= max_len:
            break
        # Stop if there is only a single word left
        elif len(short.replace('[..]', '').strip().split(' ')) == 1:
            break
        # Skip if this word is not of the right sentiment
        elif t != sent:
            continue
        # Remove this word
        short = short.replace(w, '[..]').strip()
        # Make sure to merge consecutive '[..]'
        while '[..] [..]' in short:
            short = short.replace('[..] [..]', '[..]')

    return short


def to_float(x):
    """ Helper to try to convert to float.
    """
    try:
        return float(x)
    except:
        return None
