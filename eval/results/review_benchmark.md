# Strict review benchmark

54 seeded mistakes: **54 found** (100%), **53 on exactly the right line** (98%). 6 clean programs: **0 false alarms** at high/medium severity. Took 0.09 s.

| Category | Seeded mistakes | Found | Right line |
|---|---|---|---|
| Python | 38 | 38 | 38 |
| JavaScript / React | 12 | 12 | 11 |
| Data & markup | 4 | 4 | 4 |

## Clean-code check on real code (high/medium findings should be zero for working code)

| Folder | Files | Time | High | Medium | Low |
|---|---|---|---|---|---|
| `app` | 130 | 1712 ms | 0 | 4 | 51 |
| `frontend/src` | 118 | 1675 ms | 0 | 0 | 21 |

## Every case

| Case | Expected | Found | Right line |
|---|---|---|---|
| missing colon after def | `PY-SYNTAX @ m.py:1` | yes | yes |
| unclosed parenthesis | `PY-SYNTAX @ m.py:2` | yes | yes |
| extra closing parenthesis | `PY-SYNTAX @ m.py:2` | yes | yes |
| misspelled keyword (retrun) | `PY-SYNTAX @ m.py:2` | yes | yes |
| bad indentation | `PY-SYNTAX @ m.py:3` | yes | yes |
| unterminated string | `PY-SYNTAX @ m.py:1` | yes | yes |
| missing comma in call | `PY-SYNTAX @ m.py:1` | yes | yes |
| undefined variable | `PY-UNDEFINED @ m.py:2` | yes | yes |
| misspelled loop variable | `PY-UNDEFINED @ m.py:3` | yes | yes |
| misspelled function call | `PY-UNDEFINED @ m.py:5` | yes | yes |
| Python 2 leftover (xrange) | `PY-UNDEFINED @ m.py:1` | yes | yes |
| self attribute typo | `PY-ATTR @ m.py:5` | yes | yes |
| stdlib attribute typo | `PY-MODATTR @ m.py:2` | yes | yes |
| math function typo | `PY-MODATTR @ m.py:2` | yes | yes |
| import of a name that does not exist | `PY-IMPORT @ m.py:1` | yes | yes |
| import of a module that does not exist | `PY-IMPORT @ m.py:1` | yes | yes |
| too many arguments | `PY-ARITY @ m.py:5` | yes | yes |
| missing argument | `PY-ARITY @ m.py:5` | yes | yes |
| misspelled keyword argument | `PY-ARITY @ m.py:5` | yes | yes |
| wrong arity across files | `PY-ARITY @ m.py:4` | yes | yes |
| self method called without argument | `PY-ARITY @ m.py:5` | yes | yes |
| method without self | `PY-NOSELF @ m.py:2` | yes | yes |
| division by literal zero | `PY-DIVZERO @ m.py:2` | yes | yes |
| assert on a tuple | `PY-ASSERT @ m.py:2` | yes | yes |
| string plus number | `PY-TYPEMIX @ m.py:1` | yes | yes |
| mutable default argument | `PY-MUTDEF @ m.py:1` | yes | yes |
| function defined twice | `PY-REDEF @ m.py:5` | yes | yes |
| unreachable code | `PY-UNREACHABLE @ m.py:3` | yes | yes |
| duplicate dict key | `PY-DUPKEY @ m.py:1` | yes | yes |
| format placeholder count | `PY-FORMAT @ m.py:1` | yes | yes |
| is with a literal | `PY-ISLIT @ m.py:2` | yes | yes |
| bare except | `PY-BAREEXCEPT @ m.py:3` | yes | yes |
| shell=True | `PY-SHELL @ m.py:2` | yes | yes |
| SQL injection by concatenation | `PY-SQLI @ m.py:2` | yes | yes |
| yaml.load without a loader | `PY-YAML @ m.py:2` | yes | yes |
| hard-coded password | `SECRET @ m.py:1` | yes | yes |
| hard-coded API token in a class | `SECRET @ m.py:2` | yes | yes |
| TLS verification disabled | `PY-TLS @ m.py:2` | yes | yes |
| import path typo | `JS-IMPORT @ src/A.jsx:1` | yes | yes |
| name that the module does not export | `JS-EXPORT @ src/A.jsx:1` | yes | yes |
| package name typo | `JS-PACKAGE @ src/A.jsx:1` | yes | yes |
| misspelled component | `JS-UNDEFINED @ src/A.jsx:2` | yes | yes |
| hook used without import | `JS-UNDEFINED @ src/A.jsx:1` | yes | yes |
| misspelled variable in JSX | `JS-UNDEFINED @ src/A.jsx:2` | yes | yes |
| unclosed JSX expression | `JS-SYNTAX @ src/A.jsx:2` | yes | yes |
| extra closing brace | `JS-SYNTAX @ src/A.jsx:4` | yes | yes |
| missing closing brace | `JS-SYNTAX @ src/A.jsx:3` | yes | NO |
| assignment inside a condition | `JS-ASSIGNCOND @ src/A.jsx:2` | yes | yes |
| empty catch | `JS-EMPTYCATCH @ src/A.jsx:2` | yes | yes |
| debugger left in | `JS-DEBUGGER @ src/A.jsx:2` | yes | yes |
| trailing comma in JSON | `JSON-SYNTAX @ d.json:1` | yes | yes |
| unclosed HTML tag | `HTML-UNCLOSED @ i.html:1` | yes | yes |
| bad YAML indentation | `YAML-SYNTAX @ c.yaml:3` | yes | yes |
| unclosed CSS rule | `BRACE @ s.css:1` | yes | yes |
