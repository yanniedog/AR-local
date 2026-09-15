"""Conservative bounded lexical scan of supported literal module references.

Comments and quoted text are tokenized, never mistaken for module syntax.
This is not a universal JavaScript dependency or execution verifier.
"""
import re

IDENT = re.compile(r'[A-Za-z_$][A-Za-z0-9_$]*')
REGEX_PREFIX = {'=', '(', '[', '{', ',', ':', ';', '?', '=>', '&&', '||'}
RESERVED = frozenset(('await break case catch class const continue debugger default delete do else enum export '
    'extends finally for function if implements import in instanceof interface let new package private '
    'protected public return static super switch throw try typeof var void while with yield').split())


def _lex(text, start=0, *, stop_brace=False, nesting=0):
    if nesting > 32:
        raise ValueError('Executable source lexical nesting bound exceeded')
    tokens, i, braces, parentheses = [], start, 0, []
    line_break = False
    while i < len(text):
        if len(tokens) > 200000:
            raise ValueError('Executable source token bound exceeded')
        char = text[i]
        if char.isspace():
            line_break = line_break or char in '\r\n\u2028\u2029'
            i += 1
            continue
        if text.startswith('//', i):
            endings = [position for value in '\r\n\u2028\u2029' if (position := text.find(value, i + 2)) >= 0]
            end = min(endings) if endings else -1
            i = len(text) if end < 0 else end + 1
            line_break = True
            continue
        if text.startswith('/*', i):
            end = text.find('*/', i + 2)
            if end < 0:
                raise ValueError('Executable unterminated source comment')
            line_break = line_break or any(c in text[i:end] for c in '\r\n\u2028\u2029')
            i = end + 2
            continue
        preceded_by_line_break, line_break = line_break, False
        if char in "'\"":
            quote, begin, escaped = char, i + 1, False
            i += 1
            while i < len(text) and text[i] != quote:
                if text[i] == '\\':
                    escaped = True
                    i += 2
                elif text[i] in '\r\n':
                    raise ValueError('Executable unsupported multiline quoted source')
                else:
                    i += 1
            if i >= len(text):
                raise ValueError('Executable unterminated source string')
            tokens.append(('escaped_string' if escaped else 'string', text[begin:i]))
            i += 1
            continue
        if char == '`':
            tokens.append(('template', '`'))
            i += 1
            while i < len(text) and text[i] != '`':
                if text[i] == '\\':
                    i += 2
                elif text.startswith('${', i):
                    nested, i = _lex(text, i + 2, stop_brace=True, nesting=nesting + 1)
                    tokens.extend(nested)
                else:
                    i += 1
            if i >= len(text):
                raise ValueError('Executable unterminated template literal')
            i += 1
            tokens.append(('template_end', '`'))
            continue
        previous = tokens[-1] if tokens else None
        regex_goal = previous is None or (previous[0] == 'punctuation' and previous[1] in REGEX_PREFIX) or previous == ('prefix', '!')
        if previous == ('identifier', 'return') and (len(tokens) < 2 or tokens[-2] not in {('punctuation', '.'), ('punctuation', '?.')}):
            regex_goal = True
        if char == '/' and regex_goal:
            i += 1
            in_class = False
            while i < len(text):
                if text[i] == '\\':
                    i += 2
                    continue
                if text[i] == '[':
                    if in_class:
                        raise ValueError('Executable nested regex character class unsupported')
                    in_class = True
                elif text[i] == ']':
                    in_class = False
                elif text[i] == '/' and not in_class:
                    break
                if text[i] in '\r\n':
                    raise ValueError('Executable unsupported regex literal')
                i += 1
            if i >= len(text):
                raise ValueError('Executable unterminated regex literal')
            i += 1
            while i < len(text) and text[i].isalpha():
                i += 1
            tokens.append(('regex', '/'))
            continue
        if char == '/':
            # A slash after a control-condition ')' or statement '}' can start
            # a regex. Without a full JS parser those boundaries are ambiguous;
            # refusing them prevents regex quotes from swallowing later code.
            # Division is allowed only after a classified operand. Unknown
            # operator/statement goals fail closed instead of consuming quotes
            # under an assumed division goal.
            operand = previous is not None and (
                previous[0] in {'string', 'escaped_string', 'template_end', 'regex', 'number'}
                or previous[0] == 'identifier' and previous[1] not in RESERVED
                or previous[0] == 'punctuation' and previous[1] in {')', ']'}
            )
            if not operand or preceded_by_line_break:
                raise ValueError('Executable ambiguous slash syntax unsupported')
        match = IDENT.match(text, i)
        if match:
            tokens.append(('identifier', match.group()))
            i = match.end()
            continue
        if char == '\\':
            raise ValueError('Executable escaped source identifier unsupported')
        if char == '}' and stop_brace and braces == 0:
            return tokens, i + 1
        if char == '{':
            braces += 1
        elif char == '}':
            braces -= 1
        pair = text[i:i + 2]
        value = pair if pair in {'?.', '=>', '&&', '||'} else char
        kind = 'number' if char.isascii() and char.isdigit() else 'punctuation'
        if value == '!' and (not tokens or tokens[-1][0] == 'punctuation' and tokens[-1][1] in REGEX_PREFIX):
            kind = 'prefix'
        if value == '(':
            previous = tokens[-1] if tokens else None
            parentheses.append(previous is not None and previous[0] == 'identifier'
                and previous[1] in {'if', 'while', 'for', 'with', 'switch', 'catch', 'await'})
        elif value == ')':
            if not parentheses:
                raise ValueError('Executable unbalanced source parentheses unsupported')
            if parentheses.pop():
                kind = 'control_close'
        tokens.append((kind, value))
        i += len(value)
    if stop_brace:
        raise ValueError('Executable unterminated template expression')
    return tokens, i


def literal_imports(text):
    tokens, _ = _lex(text)
    references = []
    for index, token in enumerate(tokens):
        if token[0] != 'identifier' or token[1] not in {'import', 'require', 'export'}:
            continue
        kind = token[1]
        next_index = index + 1
        following = tokens[next_index] if next_index < len(tokens) else None
        if kind in {'import', 'require'} and following == ('punctuation', '('):
            if index + 3 >= len(tokens) or tokens[index + 2][0] != 'string' or tokens[index + 3] != ('punctuation', ')'):
                raise ValueError('Executable nonliteral dynamic import unsupported')
            references.append(tokens[index + 2][1])
        elif kind == 'require':
            raise ValueError('Executable unsupported require reference')
        elif kind == 'import' and following and following[0] == 'string':
            references.append(following[1])
        else:
            if kind == 'export':
                if following == ('identifier', 'type'):
                    next_index += 1
                if next_index >= len(tokens) or tokens[next_index] not in {('punctuation', '{'), ('punctuation', '*')}:
                    continue  # Exported declaration, not a module reference.
            # Bound static clauses; identifiers inside named imports are not `from` syntax.
            braces, found = 0, False
            for offset in range(next_index, min(len(tokens), next_index + 1024)):
                item = tokens[offset]
                if item == ('punctuation', ';'):
                    break
                if item == ('punctuation', '{'):
                    braces += 1
                elif item == ('punctuation', '}'):
                    braces -= 1
                if not braces and item == ('identifier', 'from'):
                    if offset + 1 >= len(tokens) or tokens[offset + 1][0] != 'string':
                        raise ValueError('Executable unsupported module specifier')
                    references.append(tokens[offset + 1][1])
                    found = True
                    break
            else:
                if next_index + 1024 < len(tokens) or braces:
                    raise ValueError('Executable static module clause bound exceeded')
            if kind == 'import' and not found:
                raise ValueError('Executable unsupported import syntax')
    return references
