
from planning.output_formatters.json_event import JsonEventFormatter
from copy import deepcopy
from flask import json
from newsroom.formatter import BaseFormatter

agenda_json_fields = [
    'name',
    'slugline',
    'headline',
    'definition',
    'dates',
    'coverages',
    'service',
    'category',
    'place',
    'content_type',
]


class JsonFormatter(BaseFormatter):

    MIMETYPE = 'application/json'
    FILE_EXTENSION = 'json'

    formatter = JsonEventFormatter()

    def format_coverages(self, item):
        for coverage in item.get('coverages', []):
            coverage.pop('delivery_id', None)
            coverage.pop('delivery_href', None)
            coverage.pop('coverage_id', None)
            coverage.pop('coverage_provider', None)
            coverage.pop('planning_id', None)

    def format_item(self, item, item_type='items'):
        if item_type == 'wire':
            raise Exception('Undefined format for wire')

        output_item = deepcopy(item)
        output_item['event_contact_info'] = self.formatter._expand_contact_info(item)

        self.format_coverages(output_item)

        if output_item.get('place'):
            output_item['place'] = [{'name': p.get('name')} for p in output_item.get('place', [])
                                    if p.get('name')]

        if output_item.get('subject'):
            output_item['category'] = [{
                'name': s.get('name')} for s in output_item.get('subject', [])
                if s.get('name')]

        if output_item.get('definition_long'):
            output_item['definition'] = output_item.get('definition_long')

        if output_item.get('genre'):
            output_item['content_type'] = output_item.get('genre')

        filtered_output_item = {k: output_item[k] for k in agenda_json_fields if k in output_item}

        return json.dumps(filtered_output_item, indent=2).encode()
