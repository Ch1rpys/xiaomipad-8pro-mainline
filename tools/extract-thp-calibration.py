#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Extract finger electrode geometry from a user-supplied piano THP configuration.

The vendor file uses named blocks and C-style numeric arrays, not standard INI.
Only the required numeric assignments are interpreted, using the Python lexer
and literal parser. Output is private calibration, not a redistributable asset.
"""
import argparse
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import tokenize


def assignments(text):
    ignored = {tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.COMMENT}
    tokens = [(token.type, token.string) for token in tokenize.generate_tokens(io.StringIO(text).readline)
              if token.type not in ignored]

    def value(name):
        matches = [i for i, token in enumerate(tokens[:-1])
                   if token == (tokenize.NAME, name) and tokens[i + 1] == (tokenize.OP, '=')]
        if len(matches) != 1:
            raise ValueError(f'Need exactly one numeric assignment for {name}')
        start = matches[0] + 2
        if tokens[start] == (tokenize.OP, '{'):
            end = start + 1
            while end < len(tokens) and tokens[end] != (tokenize.OP, '}'):
                end += 1
            if end == len(tokens):
                raise ValueError(f'Unclosed numeric array: {name}')
            literal = [(tokenize.OP, '[')] + tokens[start + 1:end] + [(tokenize.OP, ']')]
            result = ast.literal_eval(tokenize.untokenize(literal))
            if not all(type(item) is int for item in result):
                raise ValueError(f'Non-integer electrode value in {name}')
            return result
        result = ast.literal_eval(tokens[start][1])
        if type(result) is not int:
            raise ValueError(f'Non-integer field: {name}')
        return result
    return value


def extract(source):
    data = source.read_bytes()
    value = assignments(data.decode())
    rows, columns = value('hal_row_num'), value('hal_col_num')
    units = value('normal_super_resolution')
    if (rows, columns, units) != (40, 60, 10):
        raise ValueError('Unsupported matrix or processing units')
    xmap, ymap = value('default_mapping_x'), value('default_mapping_y')
    if len(xmap) != rows * columns or len(ymap) != rows * columns:
        raise ValueError('Electrode table size differs from the matrix')
    row_map = [xmap[row * columns] for row in range(rows)]
    column_map = ymap[:columns]
    if any(xmap[row * columns + col] != row_map[row] or ymap[row * columns + col] != column_map[col]
           for row in range(rows) for col in range(columns)):
        raise ValueError('Non-separable electrode mapping needs a different coordinate model')
    edges = [value('cfg_lcd_' + suffix + '_edge') for suffix in ('x_l', 'x_r', 'y_u', 'y_d')]
    gains = [value('cfg_k_' + suffix + '_edge') for suffix in ('x_l', 'x_r', 'y_u', 'y_d')]
    if len(set(edges)) != 1 or len(set(gains)) != 1:
        raise ValueError('Asymmetric edge mapping is not supported by this processing core')
    return {
        'schema': 1, 'rows': rows, 'columns': columns, 'units_per_pixel': units,
        'source_sha256': hashlib.sha256(data).hexdigest(),
        # Stock panel identity of the source file (CSOT 4, BOE 26); piano-thp-live reports a
        # calibration that does not belong to the panel the kernel detects.
        'project_vendor_id': value('project_vendor_id'),
        'scope': 'Private extracted electrode calibration; does not establish physical touch support or orientation',
        'calibration': {
            'row_map': row_map, 'column_map': column_map,
            'row_maximum': value('display_x_resolution') * units,
            'column_maximum': value('display_y_resolution') * units,
            'edge_base': value('cfg_lcd_base_edge') * units,
            'edge_size': edges[0] * units, 'edge_gain': gains[0] * units,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = extract(args.input)
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print('Wrote private calibration; do not commit or redistribute the output.')


if __name__ == '__main__':
    main()
