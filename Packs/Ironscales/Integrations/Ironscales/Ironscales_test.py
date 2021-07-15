import json
import io
from Packs.Ironscales.Integrations.Ironscales.Ironscales import fetch_incidents

def util_load_json(path):
    with io.open(path, mode='r', encoding='utf-8') as f:
        return json.loads(f.read())


def test_ironscales_fetch_incident(mocker):
    last_run = {"data":[0]}
    mocked_client = mocker.Mock()
    mocked_client.get_open_incidents.return_value = {"incident_ids" : [0,1]}
    mocked_client.get_incident.return_value = util_load_json('test_get_open_incidents.json')
    result = fetch_incidents(mocked_client,last_run).outputs
    result_to_compare =[
        {
            "name" : "Ironscales incident: IS-1",
            "occurred": "2021-07-06T06:34:00.070Z",
            "rawJSON" : util_load_json('test_get_open_incidents.json'),
        }
    ]
    assert result == ([0,1],result_to_compare)
