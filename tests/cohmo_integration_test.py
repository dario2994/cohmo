import os
import sys
sys.path.append(os.path.dirname(os.path.realpath(__file__)) + '/..')
import cohmo
from cohmo import app
import unittest
import tempfile
from mock import *
import time
from base64 import b64encode
from flask import json, jsonify

from cohmo.table import Table, TableStatus
from cohmo.history import HistoryManager
from cohmo.authentication_manager import AuthenticationManager
from cohmo.views import init_chief, init_authentication_manager

def generate_tempfile(content):
    with tempfile.NamedTemporaryFile(delete=False) as t_file:
        t_file.write(content.encode())
        return t_file.name

class CohmoTestCase(unittest.TestCase):
    def setUp(self):
        cohmo.app.config['TEAMS_FILE_PATH'] = generate_tempfile('FRA,ITA,ENG,USA,CHN,IND,KOR')
        cohmo.app.config['HISTORY_FILE_PATH'] = generate_tempfile('USA,T2,5,10,ID1\n' + 'ENG,T5,8,12,ID2\n' + 'CHN,T5,13,17,ID3')
        cohmo.app.config['TABLE_FILE_PATHS'] = {
            'T2': generate_tempfile('''
{
    "name": "T2",
    "problem": "3",
    "coordinators": ["Franco Anselmi", "Antonio Cannavaro"],
    "queue": ["ITA", "ENG", "IND"],
    "status": "IDLE"
}'''),
            'T5': generate_tempfile('''
{
    "name": "T5",
    "problem": "6",
    "coordinators": ["Alessandro Maschi", "Giovanni Muciaccia"],
    "queue": ["IND", "KOR", "ENG", "USA"],
    "status": "CALLING"
}'''),
            'T8': generate_tempfile('''
{
    "name": "T8",
    "problem": "1",
    "coordinators": ["Marco Faschi", "Giorgio Gigi"],
    "queue": ["KOR", "ENG", "FRA"],
    "status": "CORRECTING",
    "current_coordination_team": "USA",
    "current_coordination_start_time": 10
}'''),
        }
        cohmo.app.config['AUTHENTICATION_FILE_PATH'] = generate_tempfile('''
{
    "admin": {
        "password": "pass",
        "authorizations": [],
        "admin": true
    },
    "marco": {
        "password": "xxx",
        "authorizations": ["T2", "T5"]
    }
}''')
        cohmo.app.testing = True
        credentials = b64encode(b'admin:pass').decode('utf-8')
        self.headers = {'Authorization': 'Basic ' + credentials}

    def tearDown(self):
        os.unlink(cohmo.app.config['TEAMS_FILE_PATH'])
        os.unlink(cohmo.app.config['HISTORY_FILE_PATH'])
        for table in cohmo.app.config['TABLE_FILE_PATHS']:
            os.unlink(cohmo.app.config['TABLE_FILE_PATHS'][table])

    def test_chief_initialization(self):
        chief = cohmo.get_chief()
        self.assertTrue('T2' in chief.tables and 'T5' in chief.tables and 'T8' in chief.tables)
        self.assertEqual(chief.teams, ['FRA', 'ITA', 'ENG', 'USA', 'CHN', 'IND', 'KOR'])
        self.assertEqual(chief.tables['T2'].status, TableStatus.IDLE)
        self.assertEqual(chief.tables['T5'].status, TableStatus.CALLING)
        self.assertEqual(chief.tables['T8'].status, TableStatus.CORRECTING)
        self.assertEqual(chief.tables['T8'].current_coordination_team, 'USA')
        self.assertEqual(chief.tables['T8'].current_coordination_start_time,
                         10)
        self.assertEqual(len(chief.history_manager.corrections), 3)

    def test_history(self):
        history = HistoryManager(cohmo.app.config['HISTORY_FILE_PATH'])
        self.assertTrue(history.add('ITA', 'T2', 10, 20))
        self.assertTrue(history.add('FRA', 'T8', 20, 30))
        self.assertTrue(history.add('KOR', 'T5', 15, 30))
        self.assertFalse(history.delete('ID_NOT_EXISTENT'))
        self.assertEqual(len(history.get_corrections({'identifier':'ID2'})), 1)
        self.assertTrue(history.delete('ID2'))
        self.assertEqual(history.get_corrections({'identifier':'ID2'}), [])
        self.assertEqual(len(history.corrections), 5)

        # Constructing HistoryManager from the file written by dump_to_file.
        history = HistoryManager(cohmo.app.config['HISTORY_FILE_PATH'])
        self.assertEqual(len(history.corrections), 5)
        self.assertEqual(history.corrections[2].table, 'T2')
        self.assertEqual(history.corrections[2].team, 'ITA')
        self.assertTrue(history.add('ITA', 'T5', 20, 30))

        # Testing various calls to get_corrections.
        history = HistoryManager(cohmo.app.config['HISTORY_FILE_PATH'])
        self.assertEqual(history.get_corrections({'table':'NOWAY'}), [])
        self.assertEqual(len(history.get_corrections({'table':'T5'})), 3)
        self.assertEqual(history.get_corrections({'identifier':'ID2'}), [])
        self.assertEqual(len(history.get_corrections({'table':'T2'})), 2)
        self.assertEqual(len(history.get_corrections({'table':'T8'})), 1)
        self.assertEqual(len(history.get_corrections({'table':'T5', 'team':'KOR'})), 1)
        self.assertEqual(history.get_corrections({'table':'T5', 'team':'ROK'}), [])
        self.assertEqual(len(history.get_corrections({'start_time':(-100,100)})), 6)
        self.assertEqual(len(history.get_corrections({'end_time':(15,25)})), 2)

    def test_table(self):
        history = HistoryManager(cohmo.app.config['HISTORY_FILE_PATH'])
        table = Table(cohmo.app.config['TABLE_FILE_PATHS']['T2'], history, app.config)
        self.assertEqual(table.queue, ['ITA', 'ENG', 'IND'])
        self.assertEqual(table.status, TableStatus.IDLE)
        self.assertTrue(table.switch_to_calling())
        self.assertEqual(table.status, TableStatus.CALLING)
        self.assertTrue(table.switch_to_idle())
        self.assertFalse(table.switch_to_idle())
        self.assertEqual(table.status, TableStatus.IDLE)
        self.assertTrue(table.start_coordination('IND'))
        self.assertEqual(table.status, TableStatus.CORRECTING)
        self.assertEqual(table.current_coordination_team, 'IND')
        self.assertGreater(table.current_coordination_start_time, 100)
        self.assertTrue(table.remove_from_queue('ENG'))
        self.assertFalse(table.remove_from_queue('KOR'))
        self.assertEqual(table.queue, ['ITA', 'IND'])

        # Constructing Table from the file written by dump_to_file.
        table = Table(cohmo.app.config['TABLE_FILE_PATHS']['T2'], history, app.config)
        self.assertEqual(table.queue, ['ITA', 'IND'])
        self.assertEqual(table.status, TableStatus.CORRECTING)
        self.assertEqual(table.current_coordination_team, 'IND')
        self.assertFalse(table.switch_to_calling())
        self.assertFalse(table.switch_to_idle())
        self.assertFalse(table.start_coordination('ITA'))
        self.assertEqual(len(history.get_corrections({'table':'T2', 'team':'IND'})), 0)
        self.assertTrue(table.finish_coordination())
        self.assertEqual(table.status, TableStatus.IDLE)
        self.assertEqual(len(history.get_corrections({'table':'T2', 'team':'IND'})), 1)

        # Testing the queue modifying APIs.
        self.assertTrue(table.add_to_queue('ENG'))
        self.assertFalse(table.add_to_queue('ITA'))
        self.assertTrue(table.add_to_queue('KOR', 0))
        self.assertTrue(table.add_to_queue('CHN', 2))
        self.assertEqual(table.queue, ['KOR', 'ITA', 'CHN', 'IND', 'ENG'])
        self.assertFalse(table.remove_from_queue('FRA'))
        self.assertTrue(table.remove_from_queue('ITA'))
        self.assertFalse(table.remove_from_queue('ITA'))
        self.assertFalse(table.swap_teams_in_queue('CHN', 'CHN'))
        self.assertFalse(table.swap_teams_in_queue('FRA', 'KOR'))
        self.assertTrue(table.swap_teams_in_queue('KOR', 'IND'))
        self.assertEqual(table.queue, ['IND', 'CHN', 'KOR', 'ENG'])


    # Testing operations_num.
    def test_operations_num(self):
        history = HistoryManager(cohmo.app.config['HISTORY_FILE_PATH'])
        table = Table(cohmo.app.config['TABLE_FILE_PATHS']['T2'], history, app.config)
        ops = history.operations_num
        self.assertTrue(table.start_coordination('ITA'))
        self.assertAlmostEqual(history.operations_num, ops+1)
        self.assertTrue(table.finish_coordination())
        self.assertAlmostEqual(history.operations_num, ops+2)
        self.assertTrue(table.add_to_queue('CHN'))
        self.assertAlmostEqual(history.operations_num, ops+3)
        
    # Testing get_expected_duration.
    mock_time = Mock()
    mock_time.side_effect = [10123, 10, 3, 10, 4, 10, 2, 10, 11, 10, 10, 10, 10,
                             2, 10, 11, 10, 2, 10, 11, 10,
                             2, 10, 3, 10, 2, 10, 3, 10] # 10123 = history.operations_num
    @patch('time.time', mock_time) 
    def test_get_expected_duration(self):
        cohmo.app.config['NUM_SIGN_CORR'] = 2
        cohmo.app.config['APRIORI_DURATION'] = 3
        cohmo.app.config['MINIMUM_DURATION'] = 2
        cohmo.app.config['MAXIMUM_DURATION'] = 8
        cohmo.app.config['START_TIME'] = 0
        tmp_maximum_time = cohmo.app.config['MAXIMUM_TIME']
        cohmo.app.config['MAXIMUM_TIME'] = 25
        cohmo.app.config['BREAK_TIMES'] = [[14, 16]]
        history = HistoryManager(cohmo.app.config['HISTORY_FILE_PATH'])
        table = Table(cohmo.app.config['TABLE_FILE_PATHS']['T2'], history, app.config)

        # Testing the basic behaviour.
        self.assertEqual(history.corrections[0].duration(), 5)
        self.assertEqual(len(history.get_corrections({'table':'T2'})), 1)
        self.assertAlmostEqual(table.get_expected_duration(), 4) # 10
        self.assertTrue(table.start_coordination('ITA')) # 3, 10
        self.assertAlmostEqual(table.get_expected_duration(), 4)
        self.assertTrue(table.finish_coordination()) # 4, 10
        self.assertAlmostEqual(table.get_expected_duration(), 3)
        self.assertEqual(len(history.get_corrections({'table':'T2'})), 2)

        # Testing the imposition on the maximum_time.
        self.assertTrue(table.start_coordination('ITA')) # 2, 10
        self.assertTrue(table.finish_coordination()) # 11, 10
        self.assertAlmostEqual(table.get_expected_duration(), 13/3)

        # Testing the case when the history is empty.
        self.assertEqual(len(history.get_corrections({'table':'T2'})), 3)
        corrections = history.get_corrections({'table':'T2'})
        self.assertTrue(history.delete(corrections[0].id))
        self.assertTrue(history.delete(corrections[1].id))
        self.assertTrue(history.delete(corrections[2].id))
        self.assertEqual(len(history.get_corrections({'table':'T2'})), 0)

        # Recomputing the expected_duration and deleting almost all the queue.
        table.compute_expected_duration() # 10
        self.assertAlmostEqual(table.get_expected_duration(), 3)
        self.assertTrue(table.remove_from_queue('ENG')) # 10
        self.assertTrue(table.remove_from_queue('IND')) # 10
        self.assertAlmostEqual(table.get_expected_duration(), 3)

        # Testing the maximum_duration.
        self.assertTrue(table.start_coordination('ITA')) # 2, 10
        self.assertTrue(table.finish_coordination()) # 11, 10
        self.assertAlmostEqual(table.get_expected_duration(), 6)

        self.assertTrue(table.start_coordination('ITA')) # 2, 10
        self.assertTrue(table.finish_coordination()) # 11, 10
        self.assertAlmostEqual(table.get_expected_duration(), 8)

        # Clearing the history again.
        self.assertEqual(len(history.get_corrections({'table':'T2'})), 2)
        corrections = history.get_corrections({'table':'T2'})
        self.assertTrue(history.delete(corrections[0].id))
        self.assertTrue(history.delete(corrections[1].id))

        # Testing the minimum_duration.
        self.assertTrue(table.start_coordination('ITA')) # 2, 10
        self.assertTrue(table.finish_coordination()) # 3, 10
        self.assertAlmostEqual(table.get_expected_duration(), 2)

        self.assertTrue(table.start_coordination('ITA')) # 2, 10
        self.assertTrue(table.finish_coordination()) # 3, 10
        self.assertAlmostEqual(table.get_expected_duration(), 2)

        cohmo.app.config['MAXIMUM_TIME'] = tmp_maximum_time

    def test_authentication_manager(self):
        authentication_manager = \
            AuthenticationManager(cohmo.app.config['AUTHENTICATION_FILE_PATH'])
        self.assertFalse(authentication_manager.verify_password('', ''))
        self.assertFalse(authentication_manager.verify_password('x', 'y'))
        self.assertFalse(authentication_manager.verify_password('marco', 'x'))
        self.assertFalse(authentication_manager.verify_password('marco', 'pass'))
        self.assertFalse(authentication_manager.verify_password('admin', 'xxx'))
        self.assertTrue(authentication_manager.verify_password('marco', 'xxx'))
        self.assertTrue(authentication_manager.verify_password('admin', 'pass'))

        self.assertFalse(authentication_manager.is_authorized('T1', 'T2'))
        self.assertFalse(authentication_manager.is_authorized('marco', 'T8'))
        self.assertFalse(authentication_manager.is_authorized('marco', 'T111'))
        self.assertTrue(authentication_manager.is_authorized('marco', 'T5'))
        self.assertTrue(authentication_manager.is_authorized('marco', 'T2'))
        self.assertTrue(authentication_manager.is_authorized('admin', 'T2'))
        self.assertTrue(authentication_manager.is_authorized('admin', 'T5'))

        self.assertFalse(authentication_manager.is_admin('XXX'))
        self.assertFalse(authentication_manager.is_admin('marco'))
        self.assertTrue(authentication_manager.is_admin('admin'))

    def test_views_table_queue_modifications(self):
        cohmo.views.init_chief()
        cohmo.views.init_authentication_manager()
        client = cohmo.app.test_client()
        headers = self.headers
    
        # Testing add_to_queue.
        resp = json.loads(client.post('/table/T1/add_to_queue', headers=headers,
                                      data=json.dumps({'team': 'ITA'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'Table T1 does not exist.')
        resp = json.loads(client.post('/table/T2/add_to_queue', headers=headers,
                                      data=json.dumps({'pippo': 'USA'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'You have to specify a team.')
        resp = json.loads(client.post('/table/T2/add_to_queue', headers=headers,
                                      data=json.dumps({'team': 'VAT'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'Team VAT does not exist.')
        resp = json.loads(client.post('/table/T2/add_to_queue', headers=headers,
                                      data=json.dumps({'team': 'ENG'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'Team ENG is already in queue at table T2.')
        resp = json.loads(client.post('/table/T2/add_to_queue', headers=headers,
                                      data=json.dumps({'team': 'CHN'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == True)        
        resp = json.loads(client.get('/table/T2/get_queue').data)
        self.assertTrue('ok' in resp)
        self.assertEqual(resp['queue'], ['ITA', 'ENG', 'IND', 'CHN'])
        resp = json.loads(client.post('/table/T2/add_to_queue', headers=headers,
                                      data=json.dumps({'team': 'FRA', 'pos': 2})).data)
        self.assertTrue('ok' in resp and resp['ok'] == True)        
        resp = json.loads(client.get('/table/T2/get_queue').data)
        self.assertTrue('ok' in resp)
        self.assertEqual(resp['queue'], ['ITA', 'ENG', 'FRA', 'IND', 'CHN'])
        resp = json.loads(client.post('/table/T2/remove_from_queue', headers=headers,
                                      data=json.dumps({'team': 'FRA'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == True)        
        resp = json.loads(client.get('/table/T2/get_queue').data)
        self.assertTrue('ok' in resp)
        self.assertEqual(resp['queue'], ['ITA', 'ENG', 'IND', 'CHN'])
        

        # Testing remove_from_queue.
        resp = json.loads(client.post('/table/T1/remove_from_queue', headers=headers,
                                      data=json.dumps({'team': 'ITA'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'Table T1 does not exist.')
        resp = json.loads(client.post('/table/T2/remove_from_queue', headers=headers,
                                      data=json.dumps({'pippo': 'USA'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'You have to specify a team.')
        resp = json.loads(client.post('/table/T2/remove_from_queue', headers=headers,
                                      data=json.dumps({'team': 'VAT'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'Team VAT does not exist.')
        resp = json.loads(client.post('/table/T2/remove_from_queue', headers=headers,
                                      data=json.dumps({'team': 'KOR'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'Team KOR is not in queue at table T2.')
        resp = json.loads(client.post('/table/T2/remove_from_queue', headers=headers,
                                      data=json.dumps({'team': 'CHN'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == True)        
        resp = json.loads(client.get('/table/T2/get_queue').data)
        self.assertTrue('ok' in resp)
        self.assertEqual(resp['queue'], ['ITA', 'ENG', 'IND'])

        # Testing swap_teams_in_queue.
        resp = json.loads(client.post('/table/T1/swap_teams_in_queue', headers=headers,
                                      data=json.dumps({'teams': ['ITA', 'ENG']})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'Table T1 does not exist.')
        resp = json.loads(client.post('/table/T2/swap_teams_in_queue', headers=headers,
                                      data=json.dumps({'pippo': ['USA']})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'You have to specify the teams to be swapped.')
        resp = json.loads(client.post('/table/T2/swap_teams_in_queue', headers=headers,
                                      data=json.dumps({'teams': ['VAT']})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'You have to give exactly two teams to be swapped.')
        resp = json.loads(client.post('/table/T2/swap_teams_in_queue', headers=headers,
                                      data=json.dumps({'teams': ['VAT', 'ENG']})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'Team VAT does not exist.')
        resp = json.loads(client.post('/table/T2/swap_teams_in_queue', headers=headers,
                                      data=json.dumps({'teams': ['ITA', 'KOR']})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'Team KOR is not in queue at table T2.')
        resp = json.loads(client.post('/table/T2/swap_teams_in_queue', headers=headers,
                                      data=json.dumps({'teams': ['ENG', 'ITA']})).data)
        self.assertTrue('ok' in resp and resp['ok'] == True)        
        resp = json.loads(client.get('/table/T2/get_queue').data)
        self.assertTrue('ok' in resp)
        self.assertEqual(resp['queue'], ['ENG', 'ITA', 'IND'])

    def test_views_table_coordination_management(self):
        cohmo.app.config['SKIPPED_POSITIONS'] = 1
        cohmo.views.init_chief()
        cohmo.views.init_authentication_manager()
        client = cohmo.app.test_client()
        headers = self.headers

        # Testing start_coordination.
        resp = json.loads(client.post('/table/T1/start_coordination', headers=headers,
                                      data=json.dumps({'team': 'ITA'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'Table T1 does not exist.')
        resp = json.loads(client.post('/table/T2/start_coordination', headers=headers,
                                      data=json.dumps({'pippo': 'USA'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'You have to specify a team.')
        resp = json.loads(client.post('/table/T2/start_coordination', headers=headers,
                                      data=json.dumps({'team': 'VAT'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'Team VAT does not exist.')
        resp = json.loads(client.post('/table/T2/start_coordination', headers=headers,
                                      data=json.dumps({'team': 'KOR'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'Team KOR is not in queue at table T2.')
        resp = json.loads(client.post('/table/T2/start_coordination', headers=headers,
                                      data=json.dumps({'team': 'ITA'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == True)
        resp = json.loads(client.get('/table/T2/get_queue').data)
        self.assertTrue('ok' in resp)
        self.assertEqual(resp['queue'], ['ENG', 'IND'])
        resp = json.loads(client.get('/table/T2/get_all').data)
        self.assertTrue('ok' in resp and 'table_data' in resp)
        table_data = json.loads(resp['table_data'])
        self.assertEqual(table_data['status'], 1)

        # Testing finish_coordination.
        resp = json.loads(client.post('/table/T1/finish_coordination', headers=headers).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'Table T1 does not exist.')
        resp = json.loads(client.post('/table/T2/finish_coordination', headers=headers).data)
        self.assertTrue('ok' in resp and resp['ok'] == True)
        resp = json.loads(client.get('/table/T2/get_queue').data)
        self.assertTrue('ok' in resp)
        self.assertEqual(resp['queue'], ['ENG', 'IND'])
        resp = json.loads(client.get('/table/T2/get_all').data)
        self.assertTrue('ok' in resp and 'table_data' in resp)
        table_data = json.loads(resp['table_data'])
        self.assertEqual(table_data['status'], 2)
        resp = json.loads(client.post('/table/T2/finish_coordination', headers=headers).data)
        self.assertTrue('ok' in resp and resp['ok'] == False)

        # Testing pause_coordination.
        resp = json.loads(client.post('/table/T2/add_to_queue', headers=headers,
                                      data=json.dumps({'team': 'CHN'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == True)
        resp = json.loads(client.post('/table/T2/start_coordination', headers=headers,
                                      data=json.dumps({'team': 'ENG'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == True)
        resp = json.loads(client.get('/table/T2/get_queue').data)
        self.assertTrue('ok' in resp)
        self.assertEqual(resp['queue'], ['IND', 'CHN'])
        resp = json.loads(client.post('/table/T1/pause_coordination', headers=headers).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'Table T1 does not exist.')
        resp = json.loads(client.post('/table/T2/pause_coordination', headers=headers).data)
        self.assertTrue('ok' in resp and resp['ok'] == True)
        resp = json.loads(client.get('/table/T2/get_queue').data)
        self.assertTrue('ok' in resp)
        self.assertEqual(resp['queue'], ['IND', 'CHN', 'ENG'])

        # Testing switch_to_calling.
        resp = json.loads(client.post('/table/T1/switch_to_calling', headers=headers).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'Table T1 does not exist.')
        resp = json.loads(client.post('/table/T2/switch_to_calling', headers=headers).data)
        self.assertTrue('ok' in resp and resp['ok'] == True)
        resp = json.loads(client.get('/table/T2/get_all').data)
        self.assertTrue('ok' in resp and 'table_data' in resp)
        table_data = json.loads(resp['table_data'])
        self.assertEqual(table_data['status'], 0)      

        # Testing switch_to_idle.
        resp = json.loads(client.post('/table/T1/switch_to_idle', headers=headers).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'Table T1 does not exist.')
        resp = json.loads(client.post('/table/T2/switch_to_idle', headers=headers).data)
        self.assertTrue('ok' in resp and resp['ok'] == True)
        resp = json.loads(client.get('/table/T2/get_all').data)
        self.assertTrue('ok' in resp and 'table_data' in resp)
        table_data = json.loads(resp['table_data'])
        self.assertEqual(table_data['status'], 2)
        resp = json.loads(client.get('/table/T2/get_queue').data)
        self.assertTrue('ok' in resp)
        self.assertEqual(resp['queue'], ['IND', 'CHN', 'ENG'])

        # Testing call_team
        resp = json.loads(client.post('/table/T1/call_team', headers=headers).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'Table T1 does not exist.')
        resp = json.loads(client.post('/table/T2/call_team', headers=headers,
                                      data=json.dumps({'pippo': 'USA'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'You have to specify a team.')
        resp = json.loads(client.post('/table/T2/call_team', headers=headers,
                                      data=json.dumps({'team': 'VAT'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'Team VAT does not exist.')
        resp = json.loads(client.post('/table/T2/call_team', headers=headers,
                                      data=json.dumps({'team': 'KOR'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == True)
        resp = json.loads(client.get('/table/T2/get_queue').data)
        self.assertTrue('ok' in resp)
        self.assertEqual(resp['queue'], ['KOR', 'IND', 'CHN', 'ENG'])        
        resp = json.loads(client.get('/table/T2/get_all').data)
        self.assertTrue('ok' in resp and 'table_data' in resp)
        table_data = json.loads(resp['table_data'])
        self.assertEqual(table_data['status'], 0)

        resp = json.loads(client.post('/table/T2/call_team', headers=headers,
                                      data=json.dumps({'team': 'IND'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == True)
        resp = json.loads(client.get('/table/T2/get_queue').data)
        self.assertTrue('ok' in resp)
        self.assertEqual(resp['queue'], ['IND', 'KOR', 'CHN', 'ENG'])        
        resp = json.loads(client.get('/table/T2/get_all').data)
        self.assertTrue('ok' in resp and 'table_data' in resp)
        table_data = json.loads(resp['table_data'])
        self.assertEqual(table_data['status'], 0)

        resp = json.loads(client.post('/table/T2/switch_to_idle', headers=headers).data)
        self.assertTrue('ok' in resp and resp['ok'] == True)
        resp = json.loads(client.get('/table/T2/get_all').data)
        self.assertTrue('ok' in resp and 'table_data' in resp)
        table_data = json.loads(resp['table_data'])
        self.assertEqual(table_data['status'], 2)
        resp = json.loads(client.post('/table/T2/remove_from_queue', headers=headers,
                                      data=json.dumps({'team': 'KOR'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == True)
        resp = json.loads(client.get('/table/T2/get_queue').data)
        self.assertTrue('ok' in resp)
        self.assertEqual(resp['queue'], ['IND', 'CHN', 'ENG'])
        
                
        # Testing skip_to_next.
        resp = json.loads(client.post('/table/T1/skip_to_next', headers=headers).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'Table T1 does not exist.')
        resp = json.loads(client.post('/table/T2/skip_to_next', headers=headers).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'You can not skip to call the next team if you are not calling.')
        resp = json.loads(client.post('/table/T2/switch_to_calling', headers=headers,).data)
        self.assertTrue('ok' in resp and resp['ok'] == True)
        resp = json.loads(client.post('/table/T2/skip_to_next', headers=headers).data)
        self.assertTrue('ok' in resp and resp['ok'] == True)
        resp = json.loads(client.get('/table/T2/get_all').data)
        self.assertTrue('ok' in resp and 'table_data' in resp)
        table_data = json.loads(resp['table_data'])
        self.assertEqual(table_data['status'], 0)
        resp = json.loads(client.get('/table/T2/get_queue').data)
        self.assertTrue('ok' in resp)
        self.assertEqual(resp['queue'], ['CHN', 'IND', 'ENG'])
        resp = json.loads(client.post('/table/T2/remove_from_queue', headers=headers,
                                      data=json.dumps({'team': 'ENG'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == True)
        resp = json.loads(client.post('/table/T2/remove_from_queue', headers=headers,
                                      data=json.dumps({'team': 'IND'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == True)
        resp = json.loads(client.post('/table/T2/skip_to_next', headers=headers).data) 
        self.assertTrue('ok' in resp and resp['ok'] == True and
                        resp['message'] == 'There is only a team to correct yet.')
        resp = json.loads(client.post('/table/T2/remove_from_queue', headers=headers,
                                      data=json.dumps({'team': 'CHN'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == True)
        resp = json.loads(client.post('/table/T2/skip_to_next', headers=headers).data)
        self.assertTrue('ok' in resp and resp['ok'] == True and
                        resp['message'] == 'There are no teams to correct.')

    def test_views_table_get(self):
        cohmo.app.config['MINIMUM_DURATION'] = 1
        cohmo.views.init_chief()
        client = cohmo.app.test_client()

        # Testing get_queue.
        resp = json.loads(client.get('/table/T1/get_queue').data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'Table T1 does not exist.')
        resp = json.loads(client.get('/table/T2/get_queue').data)
        self.assertTrue('ok' in resp)
        self.assertEqual(resp['queue'], ['ITA', 'ENG', 'IND'])

        # Testing get_all.
        resp = json.loads(client.get('/table/T1/get_all').data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'Table T1 does not exist.')
        resp = json.loads(client.get('/table/T2/get_queue').data)
        self.assertTrue('ok' in resp)
        self.assertEqual(resp['queue'], ['ITA', 'ENG', 'IND'])
        resp = json.loads(client.get('/table/T2/get_all').data)
        self.assertTrue('ok' in resp and 'table_data' in resp)
        table_data = json.loads(resp['table_data'])
        self.assertEqual(table_data, {'name': 'T2', 'problem': '3',
                                      'coordinators': ['Franco Anselmi', 'Antonio Cannavaro'],
                                      'queue': ['ITA', 'ENG', 'IND'],
                                      'status': 2,
                                      'current_coordination_start_time': None,
                                      'current_coordination_team': None,
                                      'expected_duration': 4.0})

        # Testing tables get_all.
        resp = json.loads(client.get('/tables/get_all',
                                     data=json.dumps({})).data)
        self.assertTrue('ok' in resp and resp['ok'])
        self.assertEqual(len(json.loads(resp['tables'])), 3)
        self.assertEqual(resp['changed'], True)
        last_update = resp['last_update']
        resp = json.loads(client.get('/tables/get_all',
                                     query_string = {'last_update': last_update}).data)
        self.assertTrue('ok' in resp and resp['ok'])
        self.assertFalse(resp['changed'])

        resp = json.loads(client.get('/tables/get_all',
                                     query_string = {'last_update': last_update-1}).data)
        self.assertTrue('ok' in resp and resp['ok'])
        self.assertEqual(len(json.loads(resp['tables'])), 3)
        self.assertEqual(resp['changed'], True)

    def test_views_history(self):
        cohmo.app.config['NUM_SIGN_CORR'] = 2
        cohmo.app.config['APRIORI_DURATION'] = 3
        cohmo.views.init_chief()
        cohmo.views.init_authentication_manager()
        client = cohmo.app.test_client()
        headers = self.headers

        # Testing history_add.
        resp = json.loads(client.post('/history/add', headers=headers,
                                      data=json.dumps({'pippo': 'ITA'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'You have to specify a team.')
        resp = json.loads(client.post('/history/add', headers=headers,
                                      data=json.dumps({'team': 'ITA'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'You have to specify a table.')
        resp = json.loads(client.post('/history/add', headers=headers,
                                      data=json.dumps({'team': 'ITA',
                                                       'table': 'T8'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'You have to specify a start time.')
        resp = json.loads(client.post('/history/add', headers=headers,
                                      data=json.dumps({'team': 'ITA',
                                                       'table': 'T8',
                                                       'start_time': 10})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'You have to specify an end time.')
        resp = json.loads(client.post('/history/add', headers=headers,
                                      data=json.dumps({'team': 'ITA',
                                                       'table': 'T8',
                                                       'start_time': 10,
                                                       'end_time': 25})).data)
        self.assertTrue('ok' in resp and resp['ok'] == True)

        # Testing history_delete.
        resp = json.loads(client.post('/history/delete', headers=headers,
                                      data=json.dumps({'pippo': 'ITA'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'You have to specify a correction id.')
        resp = json.loads(client.post('/history/delete', headers=headers,
                                      data=json.dumps({'correction_id': 'ID2'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == True)

        # Testing history_get_corrections.
        resp = json.loads(client.get('/history/get_corrections',
                                     data=json.dumps({'pippo': 'USA'})).data)
        self.assertTrue('ok' in resp and resp['ok'] == False and
                        resp['message'] == 'You have to specify filters.')
        resp = json.loads(client.get('/history/get_corrections',
                                     data=json.dumps({'filters': {'team':'USA'}})).data)
        self.assertTrue('ok' in resp and resp['ok'] == True and
                        'corrections' in resp and len(resp['corrections']) == 1)
        correction = resp['corrections'][0]
        self.assertEqual(correction, {'team': 'USA', 'table': 'T2',
                                      'start_time': 5, 'end_time': 10,
                                      'id': 'ID1'})
        

if __name__ == '__main__':
    unittest.main()
