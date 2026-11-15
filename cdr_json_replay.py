"""Exact stdlib indent=2 top-level JSON, with explicitly replayable arrays."""
import json
from cdr_replay_rows import ReplayRows


def write_json_object(stream, data):
    if not any(isinstance(value, ReplayRows) for value in data.values()):
        json.dump(data, stream, indent=2, ensure_ascii=False)
        return
    encoder = json.JSONEncoder(indent=2, ensure_ascii=False)
    stream.write('{')
    for index, (key, value) in enumerate(data.items()):
        if not isinstance(key, str): raise TypeError('streamed export keys must be strings')
        stream.write(',\n' if index else '\n')
        stream.write('  ' + json.dumps(key, ensure_ascii=False) + ': ')
        if isinstance(value, ReplayRows):
            if not len(value): stream.write('[]'); continue
            stream.write('[\n')
            for number, row in enumerate(value):
                if number: stream.write(',\n')
                stream.write('    ')
                for chunk in encoder.iterencode(row): stream.write(chunk.replace('\n', '\n    '))
            stream.write('\n  ]')
        else:
            for chunk in encoder.iterencode(value): stream.write(chunk.replace('\n', '\n  '))
    stream.write('\n}' if data else '}')
