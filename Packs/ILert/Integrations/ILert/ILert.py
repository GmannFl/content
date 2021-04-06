import demistomock as demisto  # noqa: F401
from CommonServerPython import *  # noqa: F401

# Disable insecure warnings
requests.packages.urllib3.disable_warnings()

''' GLOBAL VARS '''
# iLert API works only with secured communication.
USE_SSL = not demisto.params().get('insecure', False)

USE_PROXY = demisto.params().get('proxy', True)
INTEGRATION_KEY = demisto.params()['integrationKey']

CREATE_EVENT_URL = 'https://api.ilert.com/api/v1/events'

DEFAULT_HEADERS = {
    'accept': 'application/json',
    'content-type': 'application/json'
}

'''HANDLE PROXY'''
if not USE_PROXY:
    del os.environ['HTTP_PROXY']
    del os.environ['HTTPS_PROXY']
    del os.environ['http_proxy']
    del os.environ['https_proxy']

'''TABLE NAMES'''
NEW_EVENT = 'New Event'
ACKNOWLEDGE_EVENT = 'Acknowledge Event'
RESOLVE_EVENT = 'Resolve Event'

''' HELPER FUNCTIONS '''


def test_module():
    create_new_incident_event(summary="Test incident")
    demisto.results('ok')


def http_request(method, url, params_dict=None, data=None):
    LOG('running %s request with url=%s\nparams=%s' % (method, url, json.dumps(params_dict)))
    try:
        res = requests.request(method,
                               url,
                               verify=USE_SSL,
                               params=params_dict,
                               headers=DEFAULT_HEADERS,
                               data=data
                               )
        res.raise_for_status()

        return res.json()

    except Exception as e:
        LOG(e)
        raise


def create_new_incident_event(eventType="ALERT", summary='', details='No description',
                              incidentKey=None, priority=None, integrationKey=INTEGRATION_KEY):
    """Create a new incident event in the iLert instance."""

    if integrationKey is None:
        raise Exception('You must enter a integrationKey at the integration '
                        'parameters or in the command to process this action.')

    if eventType == 'ALERT' and not summary:
        raise Exception('You must enter a summary in the command to process this action.')

    if eventType != 'ALERT' and incidentKey is None:
        raise Exception('You must enter a incidentKey in the command to process this action.')

    payload = {
        'apiKey': integrationKey,
        'eventType': eventType,
        'summary': summary,
        'details': details,
        'incidentKey': incidentKey,
        'priority': priority
    }

    return http_request('POST', CREATE_EVENT_URL, data=json.dumps(payload))


def submit_new_event_command(eventType='ALERT', summary='', details='No description',
                             incidentKey=None, priority=None, integrationKey=INTEGRATION_KEY):
    """Create new incident event."""

    res = create_new_incident_event(eventType, summary, details, incidentKey,
                                    priority, integrationKey)
    r = CommandResults(
        outputs_prefix="iLert.Event",
        outputs=res,
        readable_output=tableToMarkdown(NEW_EVENT, res),
        raw_response=res
    )
    return r


def submit_acknowledge_event_command(summary, incidentKey=None, integrationKey=INTEGRATION_KEY):
    """Create new incident acknowledge event."""

    res = create_new_incident_event(eventType='ACCEPT', summary=summary, incidentKey=incidentKey,
                                    integrationKey=integrationKey)
    r = CommandResults(
        outputs_prefix="iLert.Event",
        outputs=res,
        readable_output=tableToMarkdown(ACKNOWLEDGE_EVENT, res),
        raw_response=res
    )
    return r


def submit_resolve_event_command(summary, incidentKey=None, integrationKey=INTEGRATION_KEY):
    """Create new incident resolve event."""

    res = create_new_incident_event(eventType='RESOLVE', summary=summary, incidentKey=incidentKey,
                                    integrationKey=integrationKey)
    r = CommandResults(
        outputs_prefix="iLert.Event",
        outputs=res,
        readable_output=tableToMarkdown(RESOLVE_EVENT, res),
        raw_response=res
    )
    return r


''' EXECUTION CODE '''


def main():
    LOG('command is %s' % (demisto.command(),))
    try:
        if demisto.command() == 'test-module':
            test_module()
        elif demisto.command() == 'iLert-submit-event':
            demisto.results(submit_new_event_command(**demisto.args()))
        elif demisto.command() == 'iLert-acknowledge-event':
            demisto.results(submit_acknowledge_event_command(**demisto.args()))
        elif demisto.command() == 'iLert-resolve-event':
            demisto.results(submit_resolve_event_command(**demisto.args()))
    except Exception as err:
        return_error(err)


if __name__ in ['__main__', '__builtin__', 'builtins']:
    main()
