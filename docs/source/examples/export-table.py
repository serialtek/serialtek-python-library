"""Iterate over trace events and export TLPs as an HTML table

usage: python export-table.py <trace-path> <output-path>

This script is intended as a simple example of how to iterate over events using the
kodiak API.
"""

import argparse
from serialtek import Kodiak
from serialtek.filter import Filter

p = argparse.ArgumentParser()
p.add_argument("trace", help="The path to the trace on the analyzer to export")
p.add_argument("output", help="The path on this machine to save HTML output to.")
args = p.parse_args()

# Log into a kodiak using `stcli login` before running this script, and this line will
# use that session.
kodiak = Kodiak()


HTML_HEADER = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>TLP Export</title>
<style>
table { border-collapse: collapse; }
th, td { border: 1px solid #ccc; padding: 4px 8px; text-align: left; }
th { background: #f0f0f0; }
</style>
</head>
<body>
<table>
<tr><th>Timestamp</th><th>Payload</th></tr>
"""

HTML_ROW = "<tr><td>{timestamp}</td><td>{payload}</td></tr>\n"

HTML_FOOTER = """\
</table>
</body>
</html>
"""

with kodiak.open_trace(args.trace) as trace, open(args.output, "w") as output:
    output.write(HTML_HEADER)
    # Iterating over all events in a trace can take a long time. It is recommended to
    # filter events to just the ones relevant to the script.
    with trace.open_cursor(filter=Filter.In({"data.tlp.all": True})) as cursor:

        # For the sake of the example, we will limit the number of events to process.
        # Omit the count argument to go until the end of the trace.
        for event in cursor.get(500):
            assert event.payload is not None
            output.write(
                HTML_ROW.format(
                    timestamp=str(event.timestamp),
                    payload=event.payload.bytes.hex(sep=" "),
                )
            )
    output.write(HTML_FOOTER)
