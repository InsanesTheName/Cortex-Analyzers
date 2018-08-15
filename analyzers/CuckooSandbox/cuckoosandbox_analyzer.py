#!/usr/bin/env python
# encoding: utf-8

from cortexutils.analyzer import Analyzer

import requests
import time
from os.path import basename


class CuckooSandboxAnalyzer(Analyzer):
    def __init__(self):
        Analyzer.__init__(self)
        self.url = self.get_param('config.url', None, 'CuckooSandbox url is missing')
        self.url = self.url + "/" if not self.url.endswith("/") else self.url
        # self.analysistimeout = self.get_param('config.analysistimeout', 30*60, None)
        # self.networktimeout = self.get_param('config.networktimeout', 30, None)

    def summary(self, raw):
        taxonomies = []
        level = "safe"
        namespace = "Cuckoo"
        predicate = "Malscore"
        value = "0"

        result = {
            'service': self.data_type + '_analysis',
            'dataType': self.data_type,
            'malscore': raw.get('malscore', None),
            'malfamily': raw.get('malfamily', None)
        }

        if result["malscore"] > 6.5:
            level = "malicious"
        elif result["malscore"] > 2:
            level = "suspicious"
        elif result["malscore"] > 0:
            level = "safe"

        taxonomies.append(self.build_taxonomy(level, namespace, predicate, "{}".format(result["malscore"])))
        taxonomies.append(self.build_taxonomy(level, namespace, "Malfamily", "{}".format(result["malfamily"])))

        return {"taxonomies": taxonomies}

    def run(self):
        Analyzer.run(self)

        try:

            # file analysis
            if self.data_type == 'file':
                filepath = self.get_param('file', None, 'File is missing')
                filename = self.get_param('filename', basename(filepath))
                with open(filepath, "rb") as sample:
                    files = {"file": (filename, sample)}
                    response = requests.post(self.url + 'tasks/create/file', files=files)
                task_id = response.json()['task_ids'][0] if 'task_ids' in response.json().keys() \
                    else response.json()['task_id']

            # url analysis
            elif self.data_type == 'url':
                data = {"url": self.get_data()}
                response = requests.post(self.url + 'tasks/create/url', data=data)
                task_id = response.json()['task_id']

            else:
                self.error('Invalid data type !')

            finished = False
            tries = 0
            while not finished and tries <= 15:  # wait max 15 mins
                time.sleep(60)
                response = requests.get(self.url + 'tasks/view/' + str(task_id))
                content = response.json()['task']['status']
                if content == 'reported':
                    finished = True
                tries += 1
            if not finished:
                self.error('CuckooSandbox analysis timed out')

            # Download the report
            response = requests.get(self.url + 'tasks/report/' + str(task_id) + '/json')
            resp_json = response.json()
            list_description = [x['description'] for x in resp_json['signatures']]
            if 'suricata' in resp_json.keys() and 'alerts' in resp_json['suricata'].keys():
                if any('dstport' in x for x in resp_json['suricata']['alerts']):
                    suri_alerts = [(x['signature'], x['dstip'], x['dstport'], x['severity']) for x in
                                   resp_json['suricata']['alerts'] if 'dstport' in x.keys()]
                elif any('dst_port' in x for x in resp_json['suricata']['alerts']):
                    suri_alerts = [(x['signature'], x['dst_ip'], x['dst_port'], x['severity']) for x in
                                   resp_json['suricata']['alerts']]
                else:
                    suri_alerts = []
            else:
                suri_alerts = []
            if 'snort' in resp_json.keys() and 'alerts' in resp_json['snort'].keys():
                if any('dstport' in x for x in resp_json['snort']['alerts']):
                    snort_alerts = [(x['message'], x['dstip'], x['dstport'], x['priority']) for x in
                                    resp_json['snort']['alerts']]
                elif any('dst_port' in x for x in resp_json['snort']['alerts']):
                    snort_alerts = [(x['message'], x['dst_ip'], x['dst_port'], x['priority']) for x in
                                    resp_json['snort']['alerts']]
                else:
                    snort_alerts = []
            else:
                snort_alerts = []
            try:
                hosts = [(x['ip'], x['hostname'], x['country_name']) for x in
                         resp_json['network']['hosts']] if 'hosts' in resp_json['network'].keys() else None
            except TypeError as e:
                hosts = [x for x in resp_json['network']['hosts']] if 'hosts' in resp_json['network'].keys() else []
            uri = [(x['uri']) for x in resp_json['network']['http']] if 'http' in resp_json['network'].keys() else []
            if self.data_type == 'url':
                self.report({
                    'signatures': list_description,
                    'suricata_alerts': suri_alerts,
                    'snort_alerts': snort_alerts,
                    'hosts': hosts,
                    'uri': uri,
                    'malscore': resp_json['malscore'] if 'malscore' in resp_json.keys() else resp_json['info'].get(
                        'score', None),
                    'malfamily': resp_json.get('malfamily', None),
                    'file_type': 'url',
                    'yara': resp_json['target']['url'] if 'target' in resp_json.keys() and 'url' in resp_json[
                        'target'].keys() else '-'
                })
            else:
                self.report({
                    'signatures': list_description,
                    'suricata_alerts': suri_alerts,
                    'snort_alerts': snort_alerts,
                    'hosts': hosts,
                    'uri': uri,
                    'malscore': resp_json['malscore'] if 'malscore' in resp_json.keys() else resp_json['info'].get(
                        'score', None),
                    'malfamily': resp_json.get('malfamily', None),
                    'file_type': "".join([x for x in resp_json['target']['file']['type']]),
                    'yara': [
                        x['name'] + " - " + x['meta']['description'] if 'description' in x['meta'].keys() else x['name']
                        for x in resp_json['target']['file']['yara']]
                })

        except requests.exceptions.RequestException as e:
            self.error(e)

        except Exception as e:
            self.unexpectedError(e)


if __name__ == '__main__':
    CuckooSandboxAnalyzer().run()
