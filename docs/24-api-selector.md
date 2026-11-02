# API reference: the version selector
> Generated from `src/uiops`'s own AST; never hand-typed. Regenerate with `docs/_build/apidoc.py`.

The **version selector** -- the entry point that returns the UIOOPS engine; this package ships one, v3.5. It dispatches and computes nothing: no number changes because a call came through here.

**See also** [CLI reference](13-cli-reference.md) · [Reference](08-reference.md).

## `uiops.__init__`

Choose which UIOOPS translation processes your data.

### `VERSIONS`

```python
VERSIONS: versions
```

### `DEFAULT_VERSION`

```python
DEFAULT_VERSION: str
```

### `Engine`

```python
class Engine
```

A chosen UIOOPS version, and the modules that implement it.

### `engine`

```python
def engine(version: str | None=None) -> Engine
```

The engine for ``version``, or `DEFAULT_VERSION` if none is named.

### `UnknownVersion`

```python
class UnknownVersion(ValueError)
```

A version string that is not one of `VERSIONS`.

### `UnknownModule`

```python
class UnknownModule(KeyError)
```

A module name that is not in `CATALOGUE`.

### `CATALOGUE`

*(re-exported from elsewhere; not defined in this module)*

### `Entry`

```python
class Entry
```

One module of the UIOOPS v3.1.4 translation, and how v3.5 covers it.

``sources`` names the MATLAB/C++ file(s) the module translates, so the
classification can be checked against the UIOOPS v3.1.4 and v3.5 sources.
``v35`` is the v3.5 module that replaces it, if there is one.

### `OVERRIDDEN`

```python
OVERRIDDEN: str
```

### `SHARED`

```python
SHARED: str
```

### `TOOLING`

```python
TOOLING: str
```

### `FORK_ONLY`

```python
FORK_ONLY: str
```

### `READ_SHARED`

```python
READ_SHARED: str
```
