from cohmo.table import Table
from cohmo.history import HistoryManager
from collections import OrderedDict

# This class is the global handler of both the tables and the history.
# The name of the class is inspired from the real-world name of the person
# that is in charge of organizing and overseeing all the
# coordination-related tasks.
# It is constructed directly reading information from files.
# teams_path and history_path are paths, whereas table_paths is a dictionary
# of the form: table_name: table_path.
class ChiefCoordinator:
    def __init__(self, teams_path, table_paths, history_path, additional_config):
        self.teams_path = teams_path
        self.table_paths = table_paths
        self.history_path = history_path

        with open(teams_path) as teams_file:
            lines = teams_file.readlines()
            assert(len(lines) >= 1)
            self.teams = [team.strip() for team in lines[0].split(',')]
        self.history_manager = HistoryManager(history_path)

        self.tables = OrderedDict()
        for name in table_paths:
            self.tables[name] = Table(table_paths[name], self.history_manager, additional_config)
            assert(name == self.tables[name].name)
        self.skipped_positions = additional_config['SKIPPED_POSITIONS']
        self.start_time = additional_config['START_TIME']
        self.maximum_time = additional_config['MAXIMUM_TIME']
        self.break_times = additional_config['BREAK_TIMES']

    # Saves the current states of tables and history to the given files.
    # The default files are the ones passed to the constructor.
    def dump_to_file(self, table_paths=None, history_path=None):
        if table_paths is None: table_paths = self.table_paths
        if history_path is None: history_path = self.history_path
        self.history_manager.dump_to_file(history_path)
        for name in table_paths:
            self.tables[name].dump_to_file(table_paths[name])
