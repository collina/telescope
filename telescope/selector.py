#!/usr/bin/env python
# -*- coding: UTF-8 -*-
#
# Copyright 2014 Measurement Lab
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import datetime
import json
import logging
import re
import itertools

import iptranslation
import utils


class Selector(object):
  """Represents the data required to select a dataset from the M-Lab data.

   Attributes:
     start_time: (datetime) Time at which selection window begins.
     duration: (int) Duration of time window in seconds.
     metric: (str) Specifies the metric for which to retrieve data.
     ip_translation_spec: (iptranslation.IPTranslationStrategySpec) Specifies
       how to translate the IP address information.
     client_provider: (str) Name of provider for which to retrieve data.
     site_name: (str) Name of M-Lab site for which to retrieve data.
     mlab_project: (str) Name of project which holds the desired data.
  """

  def __init__(self):
    self.start_time = None
    self.duration = None
    self.metric = None
    self.ip_translation_spec = None
    self.client_provider = None
    self.site = None
    self.mlab_project = None

  def __repr__(self):
    return ("<Selector Object (site: {0}, client_provider: {1}, metric: {2}, " +
            "start_time: {3}, duration: {4})>").format(self.site,
                self.client_provider, self.metric, self.start_time.strftime("%Y-%m-%d"),
                self.duration)

class SelectorFileParser(object):
  """Parser for Telescope selector files.

  Parses selector files, the primary mechanism for specification of measurement
  targets.
  """
  # Not implemented -- 'hop_count': 'paris-traceroute',

  supported_metrics = {
      'download_throughput': 'ndt',
      'upload_throughput': 'ndt',
      'minimum_rtt': 'ndt',
      'average_rtt': 'ndt',
      'packet_retransmit_rate': 'ndt'
      }

  def __init__(self):
    self.logger = logging.getLogger('telescope')

  def parse(self, selector_filepath):
    """Parses a selector file into one or more Selector objects.

    Each Selector object corresponds to one discrete dataset to retrieve
    from BigQuery. For fields in the selector file that contain lists of
    values (e.g. metrics, sites), the parser will create a separate
    Selector object for each combination of those values (e.g. if the file
    specifies metrics [A, B] and sites: [X, Y, Z] the parser will create
    Selectors for (A, X), (A, Y), (A, Z), (B, X), (B, Y), (B,Z)).

    Args:
      selector_filepath: (str) Path to selector file to parse.

    Returns:
      list: A list of parsed selector objects.
    """
    with open(selector_filepath, 'r') as selector_fileinput:
      return self._parse_file_contents(selector_fileinput.read())

  def _parse_file_contents(self, selector_file_contents):
    selector_input_json = json.loads(selector_file_contents)
    self._validate_selector_input(selector_input_json)

    selectors = self._parse_input_for_selectors(selector_input_json)

    return selectors

  def _parse_input_for_selectors(self, selector_json):
    """ Parse the selector JSON dictionary and return a list of dictionaries
      flattened for each combination.

      Args:
        selector_json (dict): Unprocessed Selector JSON file represented as a
          dict.

      Returns:
        list: List of dictaries representing the possible combinations of
          the selector query.
    """
    selectors = []
    has_not_recursed = True

    start_times = selector_json['start_times']
    client_providers = selector_json['client_providers']
    sites = selector_json['sites']
    metrics = selector_json['metrics']

    for start_time, client_provider, site, metric in \
            itertools.product(start_times, client_providers, sites, metrics):
        selector = Selector()
        selector.ip_translation_spec = self._parse_ip_translation(selector_json['ip_translation'])
        selector.duration = self._parse_duration(selector_json['duration'])
        selector.start_time = self._parse_start_time(start_time)
        selector.client_provider = client_provider
        selector.site = site
        selector.metric = metric
        selector.mlab_project = SelectorFileParser.supported_metrics[selector.metric]
        selectors.append(selector)

    return selectors

  def _parse_start_time(self, start_time_string):
    """Parse the time window start time.

    Parse the start time from the expected timestamp format to Python datetime
    format. Must be in UTC time.

    Args:
      start_time_string: (str) Timestamp in format YYYY-MM-DDTHH-mm-SS.

    Returns:
      datetime: Python datetime for set timestamp string.
    """
    try:
      timestamp = (
          datetime.datetime.strptime(start_time_string, '%Y-%m-%dT%H:%M:%SZ'))
      return utils.make_datetime_utc_aware(timestamp)
    except ValueError:
      raise ValueError('UnsupportedSubsetDateFormat')

  def _parse_duration(self, duration_string):
    """Parse the time window duration.

    Parse the time window duration from the expected timespan format to integer
    number of seconds.

    Args:
      duration_string: (str) length in human-readable format, must follow number
      + time type format. (d=days, h=hours, m=minutes, s=seconds), e.g. 30d.

    Returns:
      int: Number of seconds in specified time period.
    """
    duration_seconds_to_return = 0
    duration_string_segments = re.findall('[0-9]+[a-zA-Z]+', duration_string)

    if duration_string_segments:
      for segment in duration_string_segments:
        numerical_amount = int(re.search('[0-9]+', segment).group(0))
        duration_type = re.search('[a-zA-Z]+', segment).group(0)

        if duration_type == 'd':
          duration_seconds_to_return += (
              datetime.timedelta(days=numerical_amount).total_seconds())
        elif duration_type == 'h':
          duration_seconds_to_return += (
              datetime.timedelta(hours=numerical_amount).total_seconds())
        elif duration_type == 'm':
          duration_seconds_to_return += (
              datetime.timedelta(minutes=numerical_amount).total_seconds())
        elif duration_type == 's':
          duration_seconds_to_return += numerical_amount
        else:
          raise ValueError('UnsupportedSelectorDurationType')
    else:
      raise ValueError('UnsupportedSelectorDuration')

    return duration_seconds_to_return

  def _parse_ip_translation(self, ip_translation_dict):
    """Parse the ip_translation field into an IPTranslationStrategySpec object.

    Args:
      ip_translation_dict: (dict) An unprocessed dictionary of
      ip_translation data from the input selector file.

    Returns:
      IPTranslationStrategySpec: An IPTranslationStrategySpec, which specifies
      properties of the IP translation strategy according to the selector file.
    """
    try:
      ip_translation_spec = iptranslation.IPTranslationStrategySpec
      ip_translation_spec.strategy_name = ip_translation_dict['strategy']
      ip_translation_spec.params = ip_translation_dict['params']
      return ip_translation_spec
    except KeyError as e:
      raise ValueError('Missing expected field in ip_translation dict: %s' %
                       e.args[0])

  def _validate_selector_input(self, selector_dict):
    if not selector_dict.has_key('file_format_version'):
        raise ValueError('NoSelectorVersionSpecified')
    elif selector_dict['file_format_version'] == 1.0:
        raise ValueError('DeprecatedSelectorVersion')
    elif selector_dict['file_format_version'] == 1.1:
        parser_validator = SelectorFileValidator1_1()
    else:
        raise ValueError('UnsupportedSelectorVersion')

    parser_validator.validate(selector_dict)


class SelectorFileValidator(object):
    def validate(self, selector_dict):
        raise NotImplementedError('Subclasses must implement this function.')
    def validate_common(self, selector_dict):
        if not selector_dict.has_key('duration'):
            raise ValueError('UnsupportedDuration')

        if not selector_dict.has_key('metrics') or \
            type(selector_dict['metrics']) != list:
                raise ValueError('MetricsRequiresList')
        else:
            for metric in selector_dict['metrics']:
                if metric not in SelectorFileParser.supported_metrics:
                    raise ValueError('UnsupportedMetric')


class SelectorFileValidator1_1(SelectorFileValidator):
    def validate(self, selector_dict):
        self.validate_common(selector_dict)
        if selector_dict.has_key('subsets'):
            raise ValueError('SubsetsNoLongerSupported')


class SelectorJsonEncoder(json.JSONEncoder):
  """Encode Telescope selector into JSON."""

  def default(self, obj):
    if isinstance(obj, Selector):
      return self._encode_selector(obj)
    return json.JSONEncoder.default(self, obj)

  def _encode_selector(self, selector):
    return {
        'file_format_version': 1.0,
        'duration': self._encode_duration(selector.duration),
        'metric': selector.metric,
        'ip_translation': self._encode_ip_translation(
            selector.ip_translation_spec),
        'subsets': [
            {
                'site': selector.site_name,
                'client_provider': selector.client_provider,
                'start_time': datetime.datetime.strftime(selector.start_time,
                                                         '%Y-%m-%dT%H:%M:%SZ')
            }
            ]
        }

  def _encode_duration(self, duration):
    return str(duration) + 'd'

  def _encode_ip_translation(self, ip_translation):
    return {
        'strategy': ip_translation.strategy_name,
        'params': ip_translation.params,
        }

