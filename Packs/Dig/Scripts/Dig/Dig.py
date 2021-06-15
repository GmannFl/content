import re
import subprocess
import traceback
from typing import Any, Dict

import demistomock as demisto  # noqa: F401
from CommonServerPython import *  # noqa: F401

''' STANDALONE FUNCTION '''


# Run Dig command on the server and get A record for the specified host
def dig_result(server: str, name: str):
    try:
        if server:
            server = f"@{server}"
            dig_output = subprocess.check_output(
                ['dig', server, name, '+short', '+identify'], stderr=subprocess.STDOUT, universal_newlines=True
            )

            if not dig_output:
                raise ValueError("Couldn't find A record for:\n" + name)

            resolved_addresses, dns_server = regex_result(dig_output, reverse_lookup=False)

            return {"name": name, "resolvedaddresses": resolved_addresses, "nameserver": dns_server}

        else:
            dig_output = subprocess.check_output(
                ['dig', name, '+short', '+identify'], stderr=subprocess.STDOUT, universal_newlines=True
            )

            if not dig_output:
                raise ValueError("Couldn't find A record for:\n" + name)

            resolved_addresses, dns_server = regex_result(dig_output, reverse_lookup=False)

            return {"name": name, "resolvedaddresses": resolved_addresses, "nameserver": dns_server}

    except Exception as e:
        if isinstance(e, subprocess.CalledProcessError):
            msg = e.output  # pylint: disable=no-member
        else:
            msg = str(e)
        return_error(msg)


# Run Dig command on the server and get PTR record for the specified IP
def reverse_dig_result(server: str, name: str):
    try:
        if server:
            server = f"@{server}"
            dig_output = subprocess.check_output(
                ['dig', server, '+answer', '-x', name, '+short', '+identify'], stderr=subprocess.STDOUT, universal_newlines=True
            )

            if not dig_output:
                raise ValueError("Couldn't find PTR record for:\n" + name)

            resolved_addresses, dns_server = regex_result(dig_output, reverse_lookup=True)

            return {"name": name, "resolveddomain": resolved_addresses, "nameserver": dns_server}

        else:
            dig_output = subprocess.check_output(
                ['dig', '+answer', '-x', name, '+short', '+identify'], stderr=subprocess.STDOUT, universal_newlines=True
            )

            if not dig_output:
                raise ValueError("Couldn't find PTR record for:\n" + name)

            resolved_addresses, dns_server = regex_result(dig_output, reverse_lookup=True)

            return {"name": name, "resolveddomain": resolved_addresses, "nameserver": dns_server}

    except Exception as e:
        if isinstance(e, subprocess.CalledProcessError):
            msg = e.output  # pylint: disable=no-member
        else:
            msg = str(e)
        return_error(msg)


def regex_result(dig_output: str, reverse_lookup: bool):
    try:
        if not reverse_lookup:
            regex_results_ip = re.findall(
                r"\b(?:(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])(?:\[\.\]|\.)){3}(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\b", dig_output)
            if not regex_results_ip:
                raise ValueError("Couldn't find results:\n")
            resolved_addresses = regex_results_ip[::2]
            dns_server = regex_results_ip[1]
        else:
            regex_results_domain = re.findall(
                r"\b^[\S]+|(?:(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])(?:\[\.\]|\.)){3}(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\b", dig_output)
            if not regex_results_domain:
                raise ValueError("Couldn't find results:\n")
            resolved_addresses = regex_results_domain[0]
            dns_server = regex_results_domain[1]
    except Exception as e:
        return_error(str(e))
    return resolved_addresses, dns_server


''' COMMAND FUNCTION '''


def dig_command(args: Dict[str, Any]) -> CommandResults:

    server = args.get('server', None)
    name = args.get('name', None)
    reverse_lookup = True if args.get("reverseLookup") == "True" else False

    if reverse_lookup:
        result = reverse_dig_result(server, name)
    else:
        result = dig_result(server, name)

    return CommandResults(
        outputs_prefix='digresults',
        outputs=result,
        ignore_auto_extract=True
    )


''' MAIN FUNCTION '''


def main():
    try:
        return_results(dig_command(demisto.args()))
    except Exception as ex:
        demisto.error(traceback.format_exc())  # print the traceback
        return_error(f'Failed to execute BaseScript. Error: {str(ex)}')


''' ENTRY POINT '''


if __name__ in ('__main__', '__builtin__', 'builtins'):
    main()
