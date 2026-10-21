"""Load search settings from config.json (local, gitignored).

Copy config.example.json to config.json and edit it. Set CONFIG_PATH to use a
different file. config.json also holds your API keys, so never commit it.
"""
import json
import logging
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXAMPLE_PATH = ROOT / 'config.example.json'

DEFAULTS = {
    'query': '',  # boolean search, e.g. '"flood susceptibility" AND (chenab OR indus) NOT review'
    'keywords': [],  # legacy alternative to query: list of terms combined with keyword_mode
    'keyword_mode': 'OR',  # OR or AND; used only with keywords
    'start_date': None,
    'end_date': None,
    'paper_sources': ['openalex', 'crossref', 'semantic_scholar'],
    'quartile_source': None,  # None, 'scimago', 'jcr'
    'quartiles': [],  # e.g. ['Q1', 'Q2']; requires quartile_source
    'quartile_year': 'publication_year',  # or 'latest'
    'subject_categories': [],  # empty means any category
    'ranking_files': {'scimago': 'data/scimago.csv', 'jcr': 'data/jcr.csv'},
    'missing_abstract_policy': 'keep',  # keep or exclude
    'max_papers': 300,  # maximum merged, deduplicated papers
    'max_results_per_source': 300,
    'output_format': 'csv',  # csv, json, xlsx
    'output_path': 'output/papers.csv',
    'email': None,  # optional polite pool email for Crossref
    'openalex_api_key': None,  # required to page past the first OpenAlex results
    'semantic_scholar_api_key': None,  # optional; avoids shared-rate-limit 429s
}


def load_config():
    path = Path(os.getenv('CONFIG_PATH') or ROOT / 'config.json')
    if not path.is_absolute():
        path = ROOT / path
    if path.is_dir():
        # Docker creates an empty directory when a missing file is bind-mounted.
        raise FileNotFoundError(f'{path} is a directory, not a file. Remove it, then copy '
                                'config.example.json to config.json.')
    if not path.exists():
        if not EXAMPLE_PATH.exists():
            raise FileNotFoundError(f'{path} not found. Copy config.example.json to config.json.')
        logging.getLogger('smart-paper-finder').warning(
            '%s not found; using config.example.json. Copy it to config.json to customise.', path.name)
        path = EXAMPLE_PATH
    with open(path, encoding='utf-8') as f:
        try:
            user = json.load(f)
        except json.JSONDecodeError as exc:
            hint = (" In JSON, write an escaped apostrophe as \\\\' (e.g. 'children\\\\'s health')."
                    if 'escape' in exc.msg else '')
            raise ValueError(f'{path}: invalid JSON: {exc}.{hint}') from None
    if not isinstance(user, dict):
        raise ValueError(f'{path}: top level must be a JSON object')
    unknown = sorted(set(user) - set(DEFAULTS))
    if unknown:
        raise ValueError(f'{path}: unknown setting(s) {unknown}')
    return {**DEFAULTS, **user}


CONFIG = load_config()
