import json

import demistomock as demisto  # noqa: F401
import requests
from CommonServerPython import *  # noqa: F401

requests.packages.urllib3.disable_warnings()


def http_request(method, url_suffix, json=None):
    """
    Helper function to perform http request
    """
    try:
        api_suffix = "/api/v1"
        base_url = demisto.params().get('base_url')
        if base_url.endswith("/"):  # remove slash in the end
            base_url = base_url[:-1]
        api_key = demisto.params().get('apikey')

        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': str(api_key)
        }
        r = requests.request(
            method,
            base_url + api_suffix + url_suffix,
            json=json,
            headers=headers,
            verify=False
        )

        if r.status_code == 422:
            return_error(message='Authentication parameters are invalid, '
                                 'Please check your URL address and your API token')

        if r.status_code not in (200, 204):
            return_error(message='The following API call response status code is [%d] - %s '
                                 % (r.status_code, r.reason))
        try:
            return r.json()
        except ValueError:
            return None
    except Exception as e:
        return_error(message='Error occurred on API call: %s. Error is: %s'
                             % (base_url + api_suffix + url_suffix, str(e)))


def get_specific_device():
    """
    Get specific device by id
    """
    device_id = demisto.args().get('device_id')
    result = http_request('GET', "/devices/%s" % str(device_id))
    ec = {'DeepInstinct.Devices(val.id && val.id == obj.id)': result}

    return_outputs(
        readable_output=tableToMarkdown('Device', result),
        outputs=ec,
        raw_response=result
    )


def get_events():
    """
    Get events
    """
    first_event_id = demisto.args().get('first_event_id')
    result = http_request('GET', '/events?after_event_id=' + str(first_event_id))
    events = {}
    if 'events' in result:
        events = result['events']
    ec = {'DeepInstinct.Events(val.id && val.id == obj.id)': events}

    return_outputs(
        readable_output=tableToMarkdown('Events', events),
        outputs=ec,
        raw_response=events
    )


def get_all_groups():
    """
    Get all groups

    """
    result = http_request('GET', "/groups")
    ec = {'DeepInstinct.Groups(val.id && val.id == obj.id)': result}

    return_outputs(
        readable_output=tableToMarkdown('Groups', result),
        outputs=ec,
        raw_response=result
    )


def get_all_policies():
    """
    Get all policies

    """
    result = http_request('GET', "/policies")
    ec = {'DeepInstinct.Policies(val.id && val.id == obj.id)': result}

    return_outputs(
        readable_output=tableToMarkdown('Policies', result),
        outputs=ec,
        raw_response=result
    )


def add_hash_to_denylist():
    """
    Add hash to deny-list
    """
    policy_id = demisto.args().get('policy_id')
    file_hash = demisto.args().get('file_hash')
    comment = demisto.args().get('comment') or ""
    http_request('POST', '/policies/%s/deny-list/hashes/%s' % (str(policy_id), file_hash), json={"comment": comment})
    demisto.results('ok')


def add_hash_to_allowlist():
    """
    Add hash to allow-list
    """
    policy_id = demisto.args().get('policy_id')
    file_hash = demisto.args().get('file_hash')
    comment = demisto.args().get('comment') or ""
    http_request('POST', '/policies/%s/allow-list/hashes/%s' % (str(policy_id), file_hash), json={"comment": comment})
    demisto.results('ok')


def remove_hash_from_denylist():
    """
    Remove hash from deny-list
    """
    policy_id = demisto.args().get('policy_id')
    file_hash = demisto.args().get('file_hash')
    http_request('DELETE', '/policies/%s/deny-list/hashes/%s' % (str(policy_id), file_hash))
    demisto.results('ok')


def remove_hash_from_allowlist():
    """
    Remove hash from allow-list
    """
    policy_id = demisto.args().get('policy_id')
    file_hash = demisto.args().get('file_hash')
    http_request('DELETE', '/policies/%s/allow-list/hashes/%s' % (str(policy_id), file_hash))
    demisto.results('ok')


def add_devices_to_group():
    """
    Add devices to specific group
    """
    group_id = demisto.args().get('group_id')
    device_ids_input = demisto.args().get('device_ids')
    device_ids = [int(num) for num in device_ids_input.split(",")]
    http_request('POST', '/groups/%s/add-devices' % str(group_id), json={"devices": device_ids})
    demisto.results('ok')


def remove_devices_from_group():
    """
    Remove devices from group
    """
    group_id = demisto.args().get('group_id')
    device_ids_input = demisto.args().get('device_ids')
    device_ids = [int(num) for num in device_ids_input.split(",")]

    http_request('POST', '/groups/%s/remove-devices' % str(group_id), json={"devices": device_ids})
    demisto.results('ok')


def delete_files_remotely():
    """
    Delete given file ids remotely
    """
    event_ids_input = demisto.args().get('event_ids')
    event_ids = [int(num) for num in event_ids_input.split(",")]
    http_request('POST', '/devices/actions/delete-remote-files', json={"ids": event_ids})
    demisto.results('ok')


def terminate_remote_processes():
    """
    Terminate remove processes by given event ids
    """
    event_ids_input = demisto.args().get('event_ids')
    event_ids = [int(num) for num in event_ids_input.split(",")]
    http_request('POST', '/devices/actions/terminate-remote-process', json={"ids": event_ids})
    demisto.results('ok')


def close_events():
    """
    Close events by event ids
    """
    event_ids_input = demisto.args().get('event_ids')
    event_ids = [int(num) for num in event_ids_input.split(",")]
    http_request('POST', '/events/actions/close', json={"ids": event_ids})
    demisto.results('ok')


def fetch_incidents():
    incidents = []
    last_id = demisto.params().get('first_fetch_id')

    last_run = demisto.getLastRun()
    if last_run and last_run.get('last_id') is not None:
        last_id = last_run.get('last_id')

    events = http_request('GET', '/events?after_event_id=' + str(last_id))
    while events and events['events']:
        for event in events['events']:
            incident = {
                'name': "DeepInstinct_" + str(event['id']),  # name is required field, must be set
                'occurred': event['insertion_timestamp'],
                'rawJSON': json.dumps(event)
            }
        incidents.append(incident)

        demisto.setLastRun({'last_id': events['last_id']})
        events = http_request('GET', '/events?after_event_id=' + str(events['last_id']))

    demisto.incidents(incidents)


def test_module():
    http_request('GET', "/health_check")
    demisto.results("ok")


def get_suspicious_events():
    """
    Get suspicious events
    """
    first_event_id = demisto.args().get('first_event_id')
    result = http_request('GET', '/suspicious-events?after_event_id=' + str(first_event_id))
    events = {}
    if 'events' in result:
        events = result['events']
    ec = {'DeepInstinct.Events(val.id && val.id == obj.id)': events}

    return_outputs(
        readable_output=tableToMarkdown('Events', events),
        outputs=ec,
        raw_response=events
    )


def main():
    # Commands
    if demisto.command() == 'test-module':
        """
         test module
        """
        test_module()

    if demisto.command() == 'deepinstinct-get-device':
        """
        Get device by id
        """
        get_specific_device()

    if demisto.command() == 'deepinstinct-get-events':
        """
        Get events
        """
        get_events()

    if demisto.command() == 'deepinstinct-get-suspicious-events':
        """
        Get events
        """
        get_suspicious_events()

    if demisto.command() == 'deepinstinct-get-all-groups':
        """
        Get all groups
        """
        get_all_groups()

    if demisto.command() == 'deepinstinct-get-all-policies':
        """
        Get all policies
        """
        get_all_policies()

    if demisto.command() == 'deepinstinct-add-hash-to-deny-list':
        """
        Add hash to deny-list
        """
        add_hash_to_denylist()

    if demisto.command() == 'deepinstinct-add-hash-to-allow-list':
        """
        Add hash to allow-list
        """
        add_hash_to_allowlist()

    if demisto.command() == 'deepinstinct-remove-hash-from-deny-list':
        """
        Remove hash from deny-list
        """
        remove_hash_from_denylist()

    if demisto.command() == 'deepinstinct-remove-hash-from-allow-list':
        """
        Remove hash from allow-list
        """
        remove_hash_from_allowlist()

    if demisto.command() == 'deepinstinct-add-devices-to-group':
        """
        Add devices to groups
        """
        add_devices_to_group()

    if demisto.command() == 'deepinstinct-remove-devices-from-group':
        """
        Remove devices from group
        """
        remove_devices_from_group()

    if demisto.command() == 'deepinstinct-delete-files-remotely':
        """
        Delete files remotely by event ids
        """
        delete_files_remotely()

    if demisto.command() == 'deepinstinct-terminate-processes':
        """
        Terminate processes by event ids
        """
        terminate_remote_processes()

    if demisto.command() == 'deepinstinct-close-events':
        """
        Close events by event ids
        """
        close_events()

    if demisto.command() == 'fetch-incidents':
        """
        fetch events
        """
        fetch_incidents()


if __name__ in ('__builtin__', 'builtins'):
    main()
