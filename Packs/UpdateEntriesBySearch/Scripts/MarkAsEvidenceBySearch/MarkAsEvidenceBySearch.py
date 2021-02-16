import fnmatch
import re
from typing import Any, Dict, Iterator, List

import demistomock as demisto  # noqa: F401
from CommonServerPython import *  # noqa: F401


def to_string(value: Any) -> Optional[str]:
    if isinstance(value, (List, Dict)) or value is None:
        return None
    try:
        return str(value)
    except ValueError:
        return None


def build_pattern(pattern_algorithm: str, pattern: str, case_insensitive: bool) -> re.Pattern[str]:
    """
    Build a matching object from the pattern given.

    :param pattern_algorithm: A pattern matching algorithm.
    :param pattern: A pattern text.
    :param case_insensitive: True if the matching is performed in case-insensitive, False otherwise.
    :return A matching object built.
    """
    if pattern_algorithm == 'basic':
        pattern = re.escape(pattern)
    elif pattern_algorithm == 'wildcard':
        pattern = fnmatch.translate(pattern)
    elif pattern_algorithm == 'regex':
        pass
    else:
        raise ValueError(f'Invalid pattern algorithm: {pattern_algorithm}')

    return re.compile(pattern, re.IGNORECASE if case_insensitive else 0)


class EntryFilter:
    def __init__(self, include_pattern: re.Pattern[str], exclude_pattern: Optional[re.Pattern[str]], node_paths: List[str]):
        """
        Initialize the filter with the matching conditions.

        :param include_pattern: A pattern to perform matching.
        :param exclude_pattern: A pattern to exclude.
        :param node_paths: The list of node path of entries to which the pattern matching is performed.
        """
        self.__include_pattern = include_pattern
        self.__exclude_pattern = exclude_pattern
        self.__node_paths = node_paths

    def match(self, entry: Dict[str, Any]) -> Optional[re.Match]:
        """
        Search the entry for the pattern.

        :param entry: The entry data.
        :return: re.Match if the pattern matched with the entry, None otherwise.
        """
        def iterate_value(value: Any) -> Iterator[Any]:
            if isinstance(value, list):
                for v in value:
                    yield from iterate_value(v)

            elif isinstance(value, dict):
                for k, v in value.items():
                    yield from iterate_value(v)
            else:
                yield value

        matched = None
        for node_path in self.__node_paths:
            for val in iterate_value(demisto.get(entry, node_path)):
                s = to_string(val)
                if s is not None:
                    if self.__exclude_pattern and self.__exclude_pattern.search(s):
                        return None

                    if not matched:
                        matched = self.__include_pattern.search(s)
        return matched


class Entry:
    def __init__(self, entry: Dict[str, Any], match: Optional[re.Match]):
        self.entry = entry
        self.match = match


def iterate_entries(incident_id: Optional[str], query_filter: Dict[str, Any],
                    entry_filter: Optional[EntryFilter] = None) -> Iterator[Entry]:
    """
    Iterate war room entries

    :param incident_id: The incident ID to search entries from.
    :param query_filter: Filters to search entries.
    :param entry_filter: Filters to filter entries.
    :return: An iterator to retrieve entries.
    """
    query_filter = dict(**query_filter)
    first_id = 1
    while True:
        query_filter['firstId'] = str(first_id)

        ents = demisto.executeCommand('getEntries', assign_params(
            id=incident_id,
            filter=query_filter
        ))
        if not ents:
            break

        if is_error(ents[0]):
            if first_id == 1:
                return_error('Unable to retrieve entries')
            break

        for ent in ents:
            if not entry_filter:
                yield Entry(ent, None)
            else:
                match = entry_filter.match(ent)
                if match:
                    yield Entry(ent, match)

        # Set the next ID
        last_id = ent['ID']
        m = re.match('([0-9]+)', last_id)
        if not m:
            raise ValueError(f'Invalid entry ID: {last_id}')
        next_id = int(m[1]) + 1
        if next_id <= first_id:
            break
        first_id = next_id


def main():
    args = demisto.args()

    build_pattern_args = assign_params(
        pattern_algorithm=args.get('algorithm', 'basic'),
        case_insensitive=argToBoolean(args.get('case_insensitive', False))
    )
    build_pattern_args['pattern'] = args['pattern']
    include_pattern = build_pattern(**build_pattern_args)
    exclude_pattern = None
    if args.get('exclude_pattern'):
        build_pattern_args['pattern'] = args['exclude_pattern']
        exclude_pattern = build_pattern(**build_pattern_args)

    filter_options = argToList(args.get('filter_options', []))
    output_option = args.get('summary', 'basic')

    exclude_ids = []
    if 'exclude_this_entry' in filter_options:
        exclude_ids.append(demisto.parentEntry()['id'])

    ents = []
    for ent in iterate_entries(
        incident_id=args.get('incident_id'),
        query_filter=assign_params(
            categories=argToList(args.get('filter_categories')),
            tags=argToList(args.get('filter_tags'))
        ),
        entry_filter=EntryFilter(
            include_pattern=include_pattern,
            exclude_pattern=exclude_pattern,
            node_paths=argToList(args.get('node_paths', 'Contents'))
        )
    ):
        if ent.entry['ID'] not in exclude_ids:
            rent = {'ID': ent.entry['ID']}
            if 'verbose' == output_option and ent.match:
                rent['Summary'] = ent.match[0][:128]
            ents.append(rent)

    if 'first_entry' in filter_options:
        if 'last_entry' in filter_options:
            del ents[1:-1]
        else:
            ents = ents[:1]
    elif 'last_entry' in filter_options:
        ents = ents[-1:]

    if not ents:
        return_outputs('No entries matched')
    else:
        dry_run = argToBoolean(args.get('dry_run', False))

        tags = argToList(args.get('tags', []))
        for ent in ents:
            ent['Tags'] = ','.join(tags)

        if not dry_run:
            description = args.get('description', '')

            for ent in ents:
                entry_id = ent['ID']
                res = demisto.executeCommand('markAsEvidence', {
                    'id': entry_id,
                    'tags': ent['Tags'],
                    'description': description
                })
                if not res or is_error(res[0]):
                    return_error(f'Failed to mark an entrie as evidence: entryID={entry_id}')

        md = f'**Matched entries:** {len(ents)}'
        if output_option != 'quiet':
            header = assign_params(
                ID='Entry ID',
                Tags='Tags',
                Summary='Summary' if 'verbose' == output_option else None
            )
            md += '\n' + tblToMd('', ents, headers=header.keys(), headerTransform=lambda h: header.get(h, ''))
        return_outputs(md)


if __name__ in ('__builtin__', 'builtins'):
    main()
