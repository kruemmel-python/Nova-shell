# Installation

## Anforderungen

- Python `3.12+`
- Windows oder Linux

## Installation aus dem Quellbaum

```bash
git clone <repository-url>
cd Nova-shell-main
python -m pip install -e .
```

## Direkter Start ohne Paketinstallation

```bash
python -m nova_shell
```

## Paketinstallation

```bash
python -m pip install .
```

Danach:

```bash
nova-shell
```

## Optionale Extras

Das Projekt bietet optionale Feature-Sets fuer:

- Observability
- Guard
- Arrow
- WASM
- GPU
- Atheria
- Release

## Verifikation

```bash
nova-shell --no-plugins -c "py 1 + 1"
```
