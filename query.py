r"""Boolean search queries, e.g. "'flood susceptibility' AND (chenab OR indus) NOT review".

Syntax: phrases in single or double quotes, or single words; AND, OR, NOT (uppercase);
parentheses. Inside a phrase, escape its own quote with a backslash: 'children\'s health'.
An apostrophe inside an unquoted word (children's) needs no escape.
Adjacent terms without an operator are ANDed. Precedence: NOT > AND > OR.
Matching is a case-insensitive literal substring check, so `flood` also matches `floods`.
"""
import re

# Phrases in "..." or '...'; a word is anything else up to whitespace, a paren or a quote.
# A backslash escapes the next character (e.g. \' inside a single-quoted phrase).
TOKEN = re.compile(r'''\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'|((?:[^\s()"'\\]|\\.)(?:[^\s()"\\]|\\.)*))''')
ESCAPE = re.compile(r'\\(.)')
OPERATORS = {'AND', 'OR', 'NOT'}


def tokenize(text):
    tokens, pos, text = [], 0, text.strip()
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise ValueError(f'query: cannot parse near {text[pos:]!r} (unbalanced quote?)')
        pos = m.end()
        lp, rp, dq, sq, word = m.groups()
        phrase = dq if dq is not None else sq
        if lp or rp:
            tokens.append(('(', None) if lp else (')', None))
        elif phrase is not None:
            phrase = ESCAPE.sub(r'\1', phrase).strip()
            if phrase:
                tokens.append(('term', phrase))
        elif word in OPERATORS:
            tokens.append((word, None))
        else:
            tokens.append(('term', ESCAPE.sub(r'\1', word)))
    return tokens


def parse(text):
    """Return an AST: ('term', s) | ('and', [..]) | ('or', [..]) | ('not', node)."""
    tokens = tokenize(text)
    if not tokens:
        raise ValueError('query is empty')
    pos = 0

    def peek():
        return tokens[pos][0] if pos < len(tokens) else None

    def take(kind):
        nonlocal pos
        if peek() != kind:
            found = peek() or 'end of query'
            raise ValueError(f'query: expected {kind}, found {found}')
        pos += 1
        return tokens[pos - 1]

    def or_expr():
        items = [and_expr()]
        while peek() == 'OR':
            take('OR')
            items.append(and_expr())
        return items[0] if len(items) == 1 else ('or', items)

    def and_expr():
        items = [not_expr()]
        while peek() in ('AND', 'NOT', 'term', '('):
            if peek() == 'AND':
                take('AND')
            items.append(not_expr())
        return items[0] if len(items) == 1 else ('and', items)

    def not_expr():
        if peek() == 'NOT':
            take('NOT')
            return ('not', not_expr())
        if peek() == '(':
            take('(')
            node = or_expr()
            take(')')
            return node
        return ('term', take('term')[1])

    node = or_expr()
    if pos != len(tokens):
        raise ValueError(f'query: unexpected {tokens[pos][0]} {tokens[pos][1] or ""}'.strip())
    return node


def from_keywords(keywords, mode):
    """Legacy `keywords` + `keyword_mode` settings as a query string."""
    return f' {mode} '.join(f'"{k}"' for k in keywords)


def evaluate(node, text):
    """`text` must already be casefolded."""
    kind, value = node
    if kind == 'term':
        return value.casefold() in text
    if kind == 'not':
        return not evaluate(value, text)
    combine = all if kind == 'and' else any
    return combine(evaluate(child, text) for child in value)


def terms(node, positive_only=False):
    """Distinct terms in order of appearance; positive_only skips terms under NOT."""
    kind, value = node
    if kind == 'term':
        return [value]
    if kind == 'not':
        return [] if positive_only else terms(value)
    out = []
    for child in value:
        out += [t for t in terms(child, positive_only) if t not in out]
    return out


def _render(node, and_op, or_op, not_op, quote_all):
    kind, value = node
    if kind == 'term':
        value = value.replace('"', ' ').strip()  # APIs only understand double-quoted phrases
        return f'"{value}"' if quote_all or ' ' in value else value
    if kind == 'not':
        return not_op + _render(value, and_op, or_op, not_op, quote_all)
    op = and_op if kind == 'and' else or_op
    return '(' + op.join(_render(c, and_op, or_op, not_op, quote_all) for c in value) + ')'


def to_openalex(node):
    """OpenAlex `search` boolean syntax."""
    return _render(node, ' AND ', ' OR ', 'NOT ', quote_all=False)


def to_semantic_scholar(node):
    """Semantic Scholar bulk search syntax: + AND, | OR, - NOT."""
    return _render(node, ' + ', ' | ', '-', quote_all=False)
