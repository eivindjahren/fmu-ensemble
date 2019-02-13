# -*- coding: utf-8 -*-
"""Contains the VirtualRealization class"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import fnmatch
import shutil
import pandas as pd

from fmu import config

fmux = config.etc.Interaction()
logger = fmux.basiclogger(__name__)


class VirtualRealization(object):
    """A computed or archived realization.

    Computed or archived, one cannot assume to have access to the file
    system containing original data.

    Datatables that in a ScratchRealization was available through the
    files dataframe, is now available as dataframes in a dict accessed
    by the localpath in the files dataframe from ScratchRealization-

    """
    def __init__(self, description=None, data=None, longdescription=None):
        self._description = description
        self._longdescription = longdescription
        if data:
            self.data = data
        else:
            self.data = {}

    def keys(self):
        """Return the keys of all data in internal datastore"""
        return self.data.keys()

    def __getitem__(self, localpath):
        """Retrieve data for a specific key. Wrapper for get_df(),
        shorthands are allowed."""
        return self.get_df(localpath)

    def __delitem__(self, localpath):
        """Delete a key from the internal datastore. The key must be fully
        qualified, no shorthands."""
        if localpath in self.keys():
            del self.data[localpath]

    def append(self, key, dataframe, overwrite=False):
        """Append data to the datastore.

        No checks performed on the dataframe coming in. If key exists,
        nothing will be appended unless overwrite is set to True
        """
        if key in self.data.keys() and not overwrite:
            logger.warning('Ignoring %s, data already exists', key)
            return
        self.data[key] = dataframe

    def __repr__(self):
        """Represent the realization. Show only the last part of the path"""
        return "<VirtualRealization, {}>".format(self._description)

    def to_disk(self, filesystempath, delete=False):
        """Write the virtual realization to the filesystem.

        All data will be dumped to the requested directory according
        to their localpaths (keys).

        Args:
            filesystempath : string with a directory, absolute or
                relative. If it exists already, it must be empty,
                otherwise we give up.
        """
        if os.path.exists(filesystempath):
            if delete:
                shutil.rmtree(filesystempath)
                os.mkdir(filesystempath)
            else:
                if os.listdir(filesystempath):
                    logger.critical("Refusing to write to non-empty directory")
                    raise IOError("Directory %s not empty" % filesystempath)
        else:
            os.mkdir(filesystempath)

        with open(os.path.join(filesystempath, '_description'),
                  'w') as fhandle:
            fhandle.write(self._description)
        if self._longdescription:
            with open(os.path.join(filesystempath, '_longdescription'),
                      'w') as fhandle:
                fhandle.write(str(self._longdescription))
        with open(os.path.join(filesystempath, '__repr__'), 'w') as fhandle:
            fhandle.write(self.__repr__())

        for key in self.keys():
            dirname = os.path.join(filesystempath, os.path.dirname(key))
            if dirname:
                if not os.path.exists(dirname):
                    os.makedirs(dirname)

            data = self.get_df(key)
            filename = os.path.join(dirname, os.path.basename(key))
            if isinstance(data, pd.DataFrame):
                logger.info("Dumping %s", key)
                data.to_csv(filename, index=False)
            elif isinstance(data, dict):
                with open(filename, 'w') as fhandle:
                    for paramkey in data.keys():
                        fhandle.write(paramkey + " " +
                                      str(data[paramkey]) + "\n")
            elif (isinstance(data, str) or isinstance(data, float) or
                  isinstance(data, int)):
                with open(filename, 'w') as fhandle:
                    fhandle.write(str(data))
            else:
                logger.warning("Don't know how to dump %s " +
                               "of type %s to disk", key, type(key))

    def load_disk(self, filesystempath):
        """Load data for a virtual realization from disk.

        Existing data in the current object will be wiped,
        this function is intended for initialization

        WARNING: This code is really shaky. We need metafiles written
        by to_json() for robust parsing of files on disk, f.ex. are
        txt files really key-value data (dicts) or csv files?

        Currently, the file format is guessed based on the contents
        of the two first lines:
        * CSV files contains commas, and more than one line
        * key-value files contains two space-separated values, and at least one line
        * scalar files contain only one item and one line

        Args:
            filesystempath: path to a directory that to_disk() has
                written to (or a really careful user)
        """
        logger.info("Loading virtual realization from %s", filesystempath)
        for root, _, filenames in os.walk(filesystempath):
            for filename in filenames:
                if filename == '_description':
                    self._description = ' '.join(open(os.path.join(
                        root, filename)).readlines())
                    logger.info('got name as %s', self._description)
                elif filename == 'STATUS':
                    self.append('STATUS', pd.read_csv(os.path.join(root,
                                                                   filename)))
                    logger.info('got STATUS')
                elif filename == '__repr__':
                    # Not implemented..
                    continue
                else:
                    # GUESS scalar, key-value txt or CSV from the first
                    # two lines. SHAKY!
                    commafields = 0
                    spacefields = 0
                    linecount = 0
                    with open(os.path.join(root, filename)) as realfile:
                        line1 = realfile.next()
                        commafields = len(line1.split(','))
                        spacefields = len(line1.split())
                        try:
                            realfile.next()
                            linecount = 2
                        except StopIteration:
                            linecount = 1
                    print(filename, commafields, spacefields, linecount)
                    if spacefields == 2 and commafields == 1:
                        # key-value txt file!
                        self.append(filename,
                                    pd.read_table(os.path.join(root, filename),
                                                  sep=r'\s+', index_col=0,
                                                  header=None)[1].to_dict())
                        logger.info('Read txt file %s', filename)
                    elif (spacefields == 1 and linecount == 1 and
                          commafields == 1):
                        # scalar file
                        value = pd.read_table(os.path.join(root, filename),
                                              header=None,
                                              engine='python').iloc[0, 0]
                        logger.info('Read scalar file %s', filename)
                        self.append(filename, value)
                    elif (spacefields == 1 and linecount > 1 and
                          commafields > 1):
                        # CSV file!
                        self.append(filename,
                                    pd.read_csv(os.path.join(root, filename)))
                        logger.info('Read csv file %s', filename)

    def to_json(self):
        """
        Dump realization data to json.

        Resulting json string is compatible with the
        accompanying load_json() function
        """
        raise NotImplementedError

    def get_df(self, localpath):
        """Access the internal datastore which contains dataframes, dicts
        or scalars.

        Shorthand is allowed, if the fully qualified localpath is
            'share/results/volumes/simulator_volume_fipnum.csv'
        then you can also get this dataframe returned with these alternatives:
         * simulator_volume_fipnum
         * simulator_volume_fipnum.csv
         * share/results/volumes/simulator_volume_fipnum

        but only as long as there is no ambiguity. In case of ambiguity, a
        ValueError will be raised.

        Args:
            localpath: the idenfier of the data requested

        Returns:
            dataframe or dictionary
        """
        data = None
        if localpath in self.keys():
            data = self.data[localpath]
        fullpath = self.shortcut2path(localpath)

        if fullpath in self.keys():
            data = self.data[fullpath]
        else:
            raise ValueError("Could not find {}".format(localpath))

        if isinstance(data, pd.DataFrame):
            return data
        elif isinstance(data, pd.Series):
            return data.to_dict()
        elif isinstance(data, dict):
            return data
        elif (isinstance(data, str) or isinstance(data, int) or
              isinstance(data, float)):
            return data
        else:
            raise ValueError("BUG: Unknown datatype")

    def shortcut2path(self, shortpath):
        """
        Convert short pathnames to fully qualified pathnames
        within the datastore.

        If the fully qualified localpath is
            'share/results/volumes/simulator_volume_fipnum.csv'
        then you can also access this with these alternatives:
         * simulator_volume_fipnum
         * simulator_volume_fipnum.csv
         * share/results/volumes/simulator_volume_fipnum

        but only as long as there is no ambiguity. In case
        of ambiguity, the shortpath will be returned.
        """
        basenames = [os.path.basename(x) for x in self.keys()]
        if basenames.count(shortpath) == 1:
            shortcut2path = {os.path.basename(x): x for x in self.keys()}
            return shortcut2path[shortpath]
        noexts = [''.join(x.split('.')[:-1]) for x in self.keys()]
        if noexts.count(shortpath) == 1:
            shortcut2path = {''.join(x.split('.')[:-1]): x
                             for x in self.keys()}
            return shortcut2path[shortpath]
        basenamenoexts = [''.join(os.path.basename(x).split('.')[:-1])
                          for x in self.keys()]
        if basenamenoexts.count(shortpath) == 1:
            shortcut2path = {''.join(os.path.basename(x).split('.')[:-1]): x
                             for x in self.keys()}
            return shortcut2path[shortpath]
        # If we get here, we did not find anything that
        # this shorthand could point to. Return as is, and let the
        # calling function handle further errors.
        return shortpath

    def get_smry(self, column_keys=None, time_index=None):
        """Analog function to get_smry() in ScratchRealization

        Accesses the internalized summary data and performs
        interpolation if needed.

        Returns data for those columns that are known, unknown
        columns will be issued a warning for.

        BUG: If some columns are available only in certain dataframes,
        we might miss them (e.g. we ask for yearly FOPT, and we have
        yearly smry with only WOPT data, and FOPT is only in daily
        smry). Resolution is perhaps to merge all relevant data
        upfront.

        Args:
            column_keys: str or list of str with column names,
                may contain wildcards (glob-style)
            time_index: str or list of datetimes

        """
        column_keys = self._glob_smry_keys(column_keys)
        if not column_keys:
            raise ValueError("No column keys found")
        if not time_index:
            time_index = 'monthly'
        elif isinstance(time_index, str):
            time_index_dt = self._get_smry_dates(time_index)
        elif isinstance(time_index, list):
            time_index_dt = time_index
        else:
            raise TypeError

        # Determine which of the internalized dataframes we should use
        # for interpolation. Or, should we merge some of them for even
        # higher accuracy?

        # Get a list ala ['yearly', 'daily']
        available_smry = [x.split('/')[-1]
                          .replace('.csv', '')
                          .replace('unsmry-', '') for x in self.keys()
                          if 'unsmry' in x]

        if isinstance(time_index, str) and time_index not in available_smry:
            # Suboptimal code, we always pick the finest available
            # time resolution:
            priorities = ['raw', 'daily', 'monthly', 'weekly', 'yearly']
            # (could also sort them by number of rows, or we could
            #  even merge them all)
            # (could have priorities as a dict, for example so we
            #  can interpolate from monthly if we ask for yearly)
            chosen_smry = ''
            for candidate in priorities:
                if candidate in available_smry:
                    chosen_smry = candidate
                    break
            if not chosen_smry:
                logger.error("No internalized summary data "
                             + "to interpolate from")
                return pd.DataFrame()

        smry = self.get_df('unsmry-' + chosen_smry)[
            ['DATE'] + column_keys]

        # Add the extra datetimes to interpolate at.
        smry.set_index('DATE', inplace=True)
        smry.index = pd.to_datetime(smry.index)
        smry = smry.append(pd.DataFrame(index=pd.to_datetime(time_index_dt)))
        # Drop duplicated dates. It is always the first one which is the
        # original.
        smry = smry[~smry.index.duplicated(keep='first')]

        smry.sort_index(inplace=True)
        smry = smry.apply(pd.to_numeric)

        # Hmm, there must be a neater way of utilizing the mask..:
        cummask = self._smry_cumulative(column_keys)
        cum_columns = [column_keys[i] for i in range(len(column_keys))
                       if cummask[i]]
        noncum_columns = [column_keys[i] for i in range(len(column_keys))
                          if not cummask[i]]
        smry[cum_columns] = smry[cum_columns]\
                            .interpolate(method='time')\
                            .fillna(method='ffill')\
                            .fillna(method='bfill')
        smry[noncum_columns] = smry[noncum_columns]\
                               .fillna(method='bfill')\
                               .fillna(value=0)

        return smry.loc[pd.to_datetime(time_index_dt)]

    def _get_smry_dates(self, freq='monthly', normalize=False):
        """Return list of datetimes available in the realization

        Similar to the function in ScratchRealization,
        but start and end date is taken from internalized
        smry dataframes.

                Args:
            freq: string denoting requested frequency for
                the list of datetimes.
                'daily', 'monthly' and 'yearly'.
                'last' will give out the last date (maximum),
                as a list with one element.
            normalize: Whether to normalize backwards at the start
                and forwards at the end to ensure the entire
                date range is covered.
        Returns:
            list of datetimes. Empty if no summary data is available.
        """
        available_smry = [x for x in self.keys()
                          if 'unsmry' in x]
        if not available_smry:
            raise ValueError("No summary to get start and end date from")

        # Infer start and end-date from internalized smry data
        available_dates = set()
        for smry in available_smry:
            available_dates = available_dates.union(
                self.get_df(smry)['DATE'].values)

        # Parse every date to datetime, needed?
        available_dates = \
            [pd.to_datetime(x) for x in list(available_dates)]
        start_date = min(available_dates)
        end_date = max(available_dates)
        pd_freq_mnenomics = {'monthly': 'MS',
                             'yearly': 'YS',
                             'daily': 'D'}
        if normalize:
            raise NotImplementedError
            # (start_date, end_date) = normalize_dates(start_date, end_date,
            #                                         freq)
        if freq not in pd_freq_mnenomics:
            raise ValueError('Requested frequency %s not supported' % freq)
        datetimes = pd.date_range(start_date, end_date,
                                  freq=pd_freq_mnenomics[freq])
        # Convert from Pandas' datetime64 to datetime.date:
        return [x.date() for x in datetimes]

    def _glob_smry_keys(self, column_keys):
        """Glob a list of column keys

        Given a list of wildcard summary vectors,
        expand the list to the known summary vectors
        (in any internalized smry dataframe)

        Returns empty list if no columns match the
        wildcard(s). This will also happen if there
        is no internalized smry dataframes

        Args:
            column_keys: str or list of str, like
                ['F*PR', 'F*PT']

        Returns:
            list of strings
        """
        if isinstance(column_keys, str):
            column_keys = [column_keys]

        # Get a list ala ['yearly', 'daily']
        available_smry = [x for x in self.keys()
                          if 'unsmry' in x]

        if not available_smry:
            raise ValueError("No summary data to glob from")

        # Merge all internalized columns:
        available_keys = set()
        for smry in available_smry:
            available_keys = available_keys.union(
                self.get_df(smry).columns)

        matches = set()
        for key in column_keys:
            matches = matches.union(
                [x for x in available_keys
                 if fnmatch.fnmatch(x, key)])
        return list(matches)

    def _smry_cumulative(self, column_keys):
        """Determine whether smry vectors are cumulative

        Returns list of booleans, indicating whether a certain
        column_key in summary dataframes corresponds to a cumulative
        column.

        The current implementation checks for the letter 'T' in the
        column key, but this behaviour is not guaranteed in the
        future, in case the cumulative information gets internalized

        Since the current implementation might not be reliable (but
        sufficient for use in the interpolation code), it is not
        exposed as a public API.

        Warning: This code is duplicated in realization.py, even though
        a ScratchRealization has access to the EclSum object which can
        give the true answer

        Args:
            column_keys: str or list of strings with summary vector
                names
        Returns:
            list of booleans, corresponding to each inputted
                summary vector name.
        """
        if isinstance(column_keys, str):
            column_keys = [column_keys]
        if not isinstance(column_keys, list):
            raise TypeError("column_keys must be str or list of str")
        return [(x.endswith('T') and ':' not in x and 'CT' not in x)
                or ('T:' in x and 'CT:' not in x) for x in column_keys]

    @property
    def parameters(self):
        """Convenience getter for parameters.txt"""
        return self.data['parameters.txt']

    @property
    def name(self):
        """Return name of ensemble"""
        return self._description
