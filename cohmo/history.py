import sys
from base64 import b32encode
from os import urandom
import csv
import shutil
import time

# Simple class to store a correction.
class Correction:
    def __init__(self, team, table, start_time, end_time, identifier=None):
        assert(end_time >= start_time)
        self.team = team
        self.table = table
        self.start_time = start_time # timestamp in seconds
        self.end_time = end_time # timestamp in seconds
        if identifier: self.id = identifier
        else: self.id = b32encode(urandom(10)) # Generating a unique id

    # Returns the duration in seconds.
    def duration(self):
        return self.end_time - self.start_time

# The manager of the past corrections.
# The internal state is simply a list of corrections.
# It can load (and dump) the history from a csv file.
class HistoryManager:
    # Loads the corrections from a file.
    # Can raise a ValueError if the file is malformed.
    # The file must be a csv file where each row contains a correction in the
    # form:
    #   team, table, start_time, end_time, id
    # The first line must contain the number of past operations happened.
    def __init__(self, path):
        self.path = path
        self.corrections = []
        self.expected_durations = {}
        # An increasing variable keeping track of the number of operations
        # related to tables ever happened.
        # This is useful for caching. Exactly for caching reason it is
        # initialized to a value that is reasonably larger than any value that
        # could have been realized in a previous run.
        self.operations_num = int(time.time())
        try:
            with open(path) as history_file:
                history_reader = csv.reader(
                    history_file, delimiter=',', quotechar='"')
                for row in history_reader:
                    if not row: continue
                    assert(len(row) == 5)
                    self.corrections.append(Correction(
                        row[0].strip(), row[1].strip(), int(row[2]),
                        int(row[3]), row[4].strip()))
        except AssertionError:
            raise ValueError('The file \'{0}\' is malformed.'.format(path))

    # Dumps all the corrections to a file. The format is the same used by
    # the constructor, see the header comment of __init__ for the
    # specifications.
    def dump_to_file(self, path=None):
        if path is None:
            path = self.path
            shutil.copyfile(path, path + '.backup')
        with open(path, 'w') as history_file:
            history_writer = csv.writer(history_file, delimiter=',',
                                        quotechar='"',
                                        quoting=csv.QUOTE_MINIMAL)
            for correction in self.corrections:
                history_writer.writerow([correction.team, correction.table,
                                        correction.start_time,
                                        correction.end_time, correction.id])

    # Appends a single correction to a csv file.
    def append_to_file(self, new_correction, path=None):
        if path is None: path = self.path
        with open(path, 'a') as history_file:
            history_writer = csv.writer(history_file, delimiter=',',
                                        quotechar='"',
                                        quoting=csv.QUOTE_MINIMAL)
            history_writer.writerow([new_correction.team, new_correction.table,
                                     new_correction.start_time,
                                     new_correction.end_time, new_correction.id])

    # Adds a single correction to the history (updating the expected_duration
    # of the related table).
    def add(self, team, table, start_time, end_time):
        if start_time > end_time: return False # Maybe raise ValueError
        new_correction = Correction(team, table, start_time, end_time)
        self.corrections.append(new_correction)
        self.append_to_file(new_correction)
        # ~ self.compute_expected_duration(table)
        return True

    # Deletes a correction (updating the expected_duration of the related table)
    # and returns True if it was succesfully deleted.
    def delete(self, correction_id):
        for correction in self.corrections:
            if correction.id == correction_id:
                self.corrections.remove(correction)
                # ~ self.compute_expected_duration(correction.table)
                self.dump_to_file()
                return True
        return False

    # Returns a (eventually empty) list of corrections that satisfies all the
    # given filters. If all corrections are desired, no property should be
    # specified.
    # The filters have to be passed as a dictionary and the possible
    # arguments are:
    # identifier: The unique id of the correction.
    # table: The table that performed the correction.
    # team: The team concerned by the correction.
    # start_time (range): A pair of timestamps. All corrections that start in
    #                     the range are returned.
    # end_time (range): Exactly as start_time, but the corrections that end
    #                   in the range are returned.
    def get_corrections(self, filters):
        result = []
        for correction in self.corrections:
            filtered_correction = True
            if 'identifier' in filters:
                filtered_correction &= correction.id == filters['identifier']
            if 'table' in filters:
                filtered_correction &= correction.table == filters['table']
            if 'team' in filters:
                filtered_correction &= correction.team == filters['team']
            if 'start_time' in filters:
                filtered_correction &= (
                    filters['start_time'][0]
                    <= correction.start_time
                    <= filters['start_time'][1])
            if 'end_time' in filters:
                filtered_correction &= (
                    filters['end_time'][0]
                    <= correction.end_time
                    <= filters['end_time'][1])
            
            if filtered_correction: result.append(correction)
        return result
