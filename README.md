# example-cloud-detector

Prebuilt cloud detectors that read imagery from a public STAC collection and write cloud masks.

## Install

```bash
pip install example-cloud-detector          # once published
pip install -e ".[dev]"                     # from a clone, for development
```

## Usage

```bash
cloud-detect fetch <catalog-url> <collection-id> --max-items 3 --out data
```

## Development

```bash
pytest
python -m build          # builds sdist + wheel into dist/
twine check dist/*
```
