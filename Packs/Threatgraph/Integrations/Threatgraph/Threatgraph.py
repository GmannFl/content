import demistomock as demisto  # noqa: F401
from CommonServerPython import *  # noqa: F401

"""
    Crowdstrike have deprecated the ThreatGraph API but no replacement is ready
    This integration replicates the get-tree REST call which provides
    parent/child sensor/process information including src/dest IP and type information

    Version History:
    # v2.1.4 add back in conversion to strings for ids after changing to argToList and fix lint warnings
    # v2.1.3 lint tidy
    # v2.1.2 no change, just reversioned following git restructuring and changed tags for deployment
    # v1.1.1 fix bugs where multiple items not working
    # v1.1.0 Threatgraph api for the deprecated Crowdstrike Threatgraph
    # as soon as Crowdstrike create a replacement then this integration can be removed
"""

import requests

BASE_URL = demisto.params()['url'][:-1] if demisto.params()['url'].endswith('/') else demisto.params()['url']
USERNAME = demisto.params().get('apikey')
PASSWORD = demisto.params().get('apisecret')


def get_tree(args):
    """ the main entry point, for a given list of sensors and process ids
        find the graph of resources associated with these and return

    Args:
        args (_type_): array of sensor_id and process_id, as defined in the integration

    Returns:
        _type_: dictionary of parent/child process information along with IP and type details
    """
    sensor_ids = argToList(args.get("sensor_ids"))
    process_ids = argToList(args.get("process_ids"))

    all_results: Dict[str, Any] = {}
    all_ips = []
    all_sources = []
    all_destinations = []
    all_key_data = ""

    for sensor_id in sensor_ids:
        sensor_id_str = str(sensor_id)
        for process_id in process_ids:
            process_id_str = str(process_id)
            main_process = query_process(sensor_id_str, process_id_str)
            if main_process.status_code != 200:
                continue
            results: Dict[str, Any] = {}
            json_response = main_process.json()
            for vertex in json_response["resources"]:
                if vertex["vertex_type"] == "process":
                    results["main_process"] = {"sensor_id": sensor_id_str,
                                               "process_id": process_id_str,
                                               "properties": vertex["properties"]}
                    ips, sources, destinations = parse_indicators(json_response["resources"][0])
                    all_ips += ips
                    all_sources += sources
                    all_destinations += destinations
                    mdata = extract_extra_data("main", sensor_id_str, process_id_str, vertex["properties"])
                    all_key_data += mdata
                    for edge in vertex["edges"]:
                        if edge == "parent_process":
                            parent_data = query_process(vertex["edges"][edge][0]["device_id"],
                                                        vertex["edges"][edge][0]["object_id"])
                            if parent_data.status_code == 200:
                                parent_json = parent_data.json()
                                results["parent_process"] = {"device_id": vertex["edges"][edge][0]["device_id"],
                                                             "process_id": vertex["edges"][edge][0]["object_id"],
                                                             "properties": parent_json["resources"][0]["properties"]}
                                ips, sources, destinations = parse_indicators(parent_json["resources"][0])
                                all_ips += ips
                                all_sources += sources
                                all_destinations += destinations
                                pdata = extract_extra_data("parent",
                                                           sensor_id_str,
                                                           process_id_str,
                                                           parent_json["resources"][0]["properties"])
                                all_key_data += pdata
                            else:
                                results["parent_process"] = {"device_id": vertex["edges"][edge][0]["device_id"],
                                                             "process_id": vertex["edges"][edge][0]["object_id"],
                                                             "properties": "No response for parent"}
                        if edge == "child_process":
                            results["child_processes"] = []
                            for child in vertex["edges"][edge]:
                                child_data = query_process(child["device_id"], child["object_id"])
                                child_json = child_data.json()
                                if child_data.status_code == 200:
                                    results["child_processes"].append({"device_id": child["device_id"],
                                                                       "process_id": child["object_id"],
                                                                       "properties": child_json["resources"][0]["properties"]})
                                    ips, sources, destinations = parse_indicators(child_json["resources"][0])
                                    all_ips += ips
                                    all_sources += sources
                                    all_destinations += destinations
                                    cdata = extract_extra_data("child",
                                                               sensor_id_str,
                                                               process_id_str,
                                                               child_json["resources"][0]["properties"])
                                    all_key_data += cdata
                                else:
                                    results["child_processes"].append({"device_id": child["device_id"],
                                                                       "process_id": child["object_id"],
                                                                       "properties": "No response for child"})
            if results:
                all_results[process_id_str] = results

    all_results["ip_addresses"] = all_ips
    ip_string = ''
    for ip in all_sources:
        ip_string += ip + ':s,'
    for ip in all_destinations:
        ip_string += ip + ':d,'
    ip_string = ip_string.rstrip(',')
    all_results["source_ip_addresses"] = all_sources
    all_results["destination_ip_addresses"] = all_destinations
    all_results["ip_type_string"] = ip_string
    all_results["process_data"] = all_key_data

    result_incident = createContext(all_results, id=None, keyTransform=underscoreToCamelCase, removeNull=True)
    ec = {
        'ThreatGraph_data(val.Id && val.Id === obj.Id)': result_incident
    }
    entry = {
        'Type': entryTypes['note'],
        'Contents': result_incident,
        'ContentsFormat': formats['json'],
        'ReadableContentsFormat': formats['markdown'],
        'HumanReadable': result_incident,
        'EntryContext': ec
    }
    return entry


def extract_extra_data(level, sid, pid, data):
    result = f"{level}/{pid}/{sid}: "
    try:
        if not data:
            result += " No data found"
            return
        cl = data.get("CommandLine", "CMD not found").replace("\\", "/").replace("\"", "'")
        im = data.get("ImageFileName", "Image not found").replace("\\", "/").replace("\"", "'")
        sh = data.get("SHA256HashData", "SHA not found").replace("\\", "/").replace("\"", "'")

        return f"{result} CommandLine {cl}, ImageFile {im}, SHA256 {sh}.   "

    except Exception as e:
        return str(e)


def query_process(sensor_id, process_id):
    """ For a given sensor and process, find the data graph

    Args:
        sensor_id (_type_): the sensor ID to be found
        process_id (_type_): the process ID to be found

    Returns:
        _type_: resource data for the given sensor and process id
    """
    url = f'{BASE_URL}/threatgraph/combined/processes/summary/v1?ids=pid:{sensor_id}:{process_id}&scope=device'
    return query_threatgraph(url)


def query_threatgraph(url):
    """ Helper method to run a query on ThreatGraph

    Args:
        url (_type_): _description_

    Returns:
        _type_: _description_
    """
    r = requests.get(url, auth=(USERNAME, PASSWORD))
    return r


def parse_indicators(resources):
    """ For a given Resource from a ThreatGraph result, returns the relevant
        information required, i.e. indicators, src/dst IP

    Args:
        resources (_type_): _description_

    Returns:
        _type_: _description_
    """
    indicators = set()
    source = set()
    destination = set()
    for edge in resources["edges"]:
        if edge == "ipv4":
            for ip in resources["edges"][edge]:
                source.add(ip["properties"]["LocalAddressIP4"])
                indicators.add(ip["properties"]["LocalAddressIP4"])
                destination.add(ip["properties"]["RemoteAddressIP4"])
                indicators.add(ip["properties"]["RemoteAddressIP4"])

    return indicators, source, destination


def test():
    """Test method for integration, makes a basic call and accepts OK or Not Found REST response
    """
    try:
        url = f'{BASE_URL}/threatgraph/combined/processes/summary/v1?ids=pid:1:1&scope=device'
        r = requests.get(url, auth=(USERNAME, PASSWORD))

        if r.status_code == 200 or r.status_code == 404:
            return_results('ok')
        else:
            return_results("Failed to login with error: " + str(r.status_code))
    except Exception as e:
        return_results(e)


def main():
    demisto.info(f'Command is {demisto.command}')
    try:
        args = demisto.args()
        if demisto.command() == 'test-module':
            demisto.results(test())
        if demisto.command() == 'bt-get-tree':
            demisto.results(get_tree(args))
    except Exception as e:
        demisto.error(e)
        raise


if __name__ in ('__main__', '__builtin__', 'builtins'):
    main()
