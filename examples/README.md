# Demo projects with deliberate mistakes

Two small projects whose bugs are known, so you can see what the review finds. Try them from the UI (*Add project* → *Local folder*, needs `ALLOW_LOCAL_PATHS=true`) or from the command line:

```bash
python -m app.review examples/python-demo --fail-on never
python -m app.review examples/react-demo  --fail-on never
```

## `python-demo` (Python, JavaScript, HTML, JSON)
| File | Line | Mistake | Rule |
|---|---|---|---|
| `app.py` | 2 | imports `calculate_etaa`, which `services/eta.py` does not define | `PY-IMPORT` |
| `app.py` | 11 | `self.nmae` (the attribute is `name`) | `PY-ATTR` |
| `app.py` | 16 | `itmes` (the variable is `items`) | `PY-UNDEFINED` |
| `app.py` | 17 | `calculate_eta(item, 5, 6)`: the function takes 2 arguments | `PY-ARITY` |
| `app.py` | 18 | `os.pth` (it is `os.path`) | `PY-MODATTR` |
| `oops.py` | 1 | missing `:` after `def broken(x)` | `PY-SYNTAX` |
| `data.json` | 1 | trailing comma | `JSON-SYNTAX` |
| `static/app.js` | 6 | `if (sum = 0)` assignment in a condition | `JS-ASSIGNCOND` |
| `static/app.js` | 9 | `summ` (the variable is `sum`) | `JS-UNDEFINED` |
| `static/app.js` | 13 | extra `}` | `JS-SYNTAX` |
| `static/index.html` | 1 | `<span>` never closed | `HTML-UNCLOSED` |

## `react-demo` (React + Vite style project)
| File | Line | Mistake | Rule |
|---|---|---|---|
| `src/App.jsx` | 2 | `NameStep` is imported as a default export but the module has none | `JS-EXPORT` |
| `src/screens/NameStep.jsx` | 2 | `Banner` is not exported by `Header.jsx` | `JS-EXPORT` |
| `src/screens/NameStep.jsx` | 3 | `'../components/Footr'` does not exist | `JS-IMPORT` |
| `src/screens/NameStep.jsx` | 4 | `'../context/SignupContext'` does not exist | `JS-IMPORT` |
| `src/screens/NameStep.jsx` | 5 | package `axioss` is not in `package.json` | `JS-PACKAGE` |
| `src/screens/NameStep.jsx` | 9 | `useSate` (the hook is `useState`) | `JS-UNDEFINED` |
| `src/screens/NameStep.jsx` | 15 | `<Hedaer />` (the component is `Header`) | `JS-UNDEFINED` |
| `src/screens/NameStep.jsx` | 17 | `nmae` (the variable is `name`) | `JS-UNDEFINED` |
| `src/screens/NameStep.jsx` | 18 | `<Spinner />` is never imported | `JS-UNDEFINED` |
| `src/screens/NameStep.jsx` | 19 | `onClick={() => { next() }>` is missing a `}` | `JS-SYNTAX` |
