---
name: test
description: Run tests for the GeoDetective Envs project. Use when the user asks to test, validate, or run pytest. Filters by argument when provided.
---

# /test — Run project tests

Corre los tests del proyecto. Acepta argumentos para filtrar.

## Uso

```
/test                            # corre tests del directorio default (cuando exista)
/test tests/tools/test_X.py      # archivo específico
/test -k pattern                 # filtra por keyword
```

## Reglas

- **Solo después de cambiar código.** No como ritual.
- **Nunca** correr la suite completa salvo pedido explícito del user.
- Si falla import: arreglar el import, no re-correr.
- En duda: NO correr, preguntar.

## Comando

Por ahora (sin pyproject.toml ni tests):

```bash
echo "No tests todavía. Crear pyproject.toml + tests/ primero."
```

Cuando exista:

```bash
conda activate geodetective && pytest $ARGUMENTS -v
```

Linter:

```bash
ruff check src/ tests/
```
