import pytest

from cdr_terms.executable_imports import literal_imports


@pytest.mark.parametrize('source', ["require /* comment */ ('./dependency')", "import // comment\n ('./dependency')",
    "require/*a*//*b*/\n('./dependency')", "import/*a*/{ x }/*b*/from/*c*/'./dependency';",
    "export/*a*/{x}/*b*/from './dependency';", "const text = `value ${require /* c */ ('./dependency')}`;"])
def test_comment_separated_literal_dependencies_are_found(source):
    assert literal_imports(source) == ['./dependency']


@pytest.mark.parametrize('source', ["const x = \"require /* text */ ('./not-code')\";",
    "const x = 'import from ./not-code';", "const text = `import('./not-code')`;",
    "// require('./not-code')\nconst value = 1;", "const pattern = /require\\('x'\\)/;",
    "export const description = 'module import words';"])
def test_text_and_comments_are_not_dependencies(source):
    assert literal_imports(source) == []


@pytest.mark.parametrize('source', ["require/*x*/('./prefix' + suffix)", "import/*x*/(name)",
    "require /* c */ (`./dependency`)", "const alias = require;", "import.meta.resolve('./x')"])
def test_unclassified_module_syntax_is_refused(source):
    with pytest.raises(ValueError, match='unsupported'):
        literal_imports(source)


@pytest.mark.parametrize('prefix', ['if (x)', 'while (x)', 'for (;x;)', 'if (x) {}', 'else', 'do'])
def test_ambiguous_statement_regex_cannot_hide_dependency(prefix):
    source = prefix + ' /"/.test(x); require(\'./hidden\'); //"'
    with pytest.raises(ValueError, match='unsupported'):
        literal_imports(source)


@pytest.mark.parametrize('operator', ['*', '%', '+', '-', '~', '^', '&', '|', '<', '>'])
def test_unclassified_operator_regex_cannot_hide_dependency(operator):
    with pytest.raises(ValueError, match='unsupported'):
        literal_imports('const n = 1 ' + operator + ' /"/.test(x); require(\'./hidden\'); //"')


def test_quoted_operator_is_a_division_operand_not_a_regex_prefix():
    assert literal_imports("const n = '=' / 2; require('hidden-package'); /abc/;") == ['hidden-package']


@pytest.mark.parametrize('source', [
    'label: while (x) { if (y) break label\n /"/.test(x); require(\'./hidden\'); //"\n}',
    'label: while (x) { if (y) continue label\n /"/.test(x); require(\'./hidden\'); //"\n}',
    "const n = value! / 2; require('hidden-package'); /abc/;",
    'break label /*\n*/ /"/.test(x); require(\'./hidden\'); //"',
    'break label\u2028 /"/.test(x); require(\'./hidden\'); //"',
])
def test_asi_and_typescript_ambiguous_goals_are_refused(source):
    with pytest.raises(ValueError, match='unsupported'):
        literal_imports(source)


def test_property_named_keyword_remains_division_operand_or_is_refused():
    with pytest.raises(ValueError, match='unsupported'):
        literal_imports("const n = obj.return / 2; require('hidden-package'); /abc/;")


@pytest.mark.parametrize('name', ['}', '{', ';', '(', ')', 'from'])
def test_quoted_export_names_do_not_change_clause_nesting(name):
    assert literal_imports('export { "' + name + '" as x } from \'./hidden\';') == ['./hidden']


def test_unary_regex_prefix_is_distinct_from_typescript_postfix():
    assert literal_imports("const n = ! /x/.test(x); require('./hidden');") == ['./hidden']


@pytest.mark.parametrize('newline', ['\r', '\n', '\r\n', '\u2028', '\u2029'])
def test_all_javascript_line_comment_terminators_preserve_code(newline):
    assert literal_imports('// comment' + newline + "require('./hidden');") == ['./hidden']


def test_unclassified_nested_regex_class_refuses():
    with pytest.raises(ValueError, match='unsupported'):
        literal_imports("const r = /[[a]--[b]]/v; require('./hidden');")


def test_oversized_export_clause_is_not_silently_truncated():
    source = 'export {' + ','.join('x' + str(i) for i in range(600)) + "} from './hidden';"
    with pytest.raises(ValueError, match='bound exceeded'):
        literal_imports(source)
    assert literal_imports('export { x };') == []
