"""Smart Paper Finder: academic paper search with optional journal quartile matching.

Run: python main.py
Dependencies: pip install requests pandas openpyxl
Ranking CSVs are user-provided; see README.md.
"""
import re
import time
import logging
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import query
from config import CONFIG

LOG = logging.getLogger('smart-paper-finder')
ROOT = Path(__file__).resolve().parent
FIELDS = ['title', 'abstract', 'url', 'doi', 'publication_date', 'year', 'journal',
          'issn', 'paper_sources', 'quartile', 'quartile_source', 'quartile_year', 'quartile_category']


def session():
    s = requests.Session()
    retry = Retry(total=4, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=['GET'], respect_retry_after_header=True)
    s.mount('https://', HTTPAdapter(max_retries=retry))
    s.headers.update({'User-Agent': 'SmartPaperFinder/1.0 (academic metadata research)'})
    return s


def get_json(s, url, params=None, headers=None):
    r = s.get(url, params=params, headers=headers, timeout=45)
    r.raise_for_status()
    return r.json()


def clean_doi(value):
    if not value:
        return None
    v = str(value).strip().lower()
    v = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', v)
    v = re.sub(r'^doi:\s*', '', v)
    return v or None


def clean_text(value):
    if not value:
        return ''
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', str(value))).strip()


def norm_title(value):
    value = unicodedata.normalize('NFKD', value or '').casefold()
    return re.sub(r'[^a-z0-9]+', '', value)


def issns(value):
    if isinstance(value, list):
        return [str(v).strip().upper().replace('-', '') for v in value if v]
    if value is None or pd.isna(value):
        return []
    return [v.strip().upper().replace('-', '') for v in re.split(r'[;,|]', str(value)) if v.strip()]


def abstract_from_index(idx):
    if not idx:
        return ''
    pairs = [(int(pos), word) for word, positions in idx.items() for pos in positions]
    return ' '.join(word for _, word in sorted(pairs))


def date_from_parts(parts):
    if not parts:
        return None
    for key in ('date-parts',):
        if parts.get(key):
            values = parts[key][0]
            try:
                return date(int(values[0]), int(values[1]) if len(values) > 1 else 1,
                            int(values[2]) if len(values) > 2 else 1).isoformat()
            except (ValueError, TypeError, IndexError):
                return None
    return None


def record(title, abstract, doi, url, pubdate, journal, issn, source):
    pubdate = (str(pubdate)[:10] if pubdate else None)
    year = int(pubdate[:4]) if pubdate and re.match(r'^\d{4}', pubdate) else None
    doi = clean_doi(doi)
    return {'title': clean_text(title), 'abstract': clean_text(abstract),
            'url': f'https://doi.org/{doi}' if doi else url, 'doi': doi,
            'publication_date': pubdate, 'year': year, 'journal': clean_text(journal),
            'issn': ';'.join(issns(issn)), 'paper_sources': source}


def openalex(s, cfg):
    key = cfg.get('openalex_api_key')
    # Search title + abstract only (plain `search` also matches full text, which the
    # local filter would discard). Commas separate filters, so strip them from the query.
    search = query.to_openalex(cfg['query_ast']).replace(',', ' ')
    params = {'per_page': min(200, cfg['max_results_per_source']), 'cursor': '*',
              'filter': f'title_and_abstract.search:{search},type:article',
              'select': 'id,doi,title,publication_date,primary_location,abstract_inverted_index'}
    if key:
        params['api_key'] = key
    if cfg.get('start_date'):
        params['filter'] += ',from_publication_date:' + cfg['start_date']
    if cfg.get('end_date'):
        params['filter'] += ',to_publication_date:' + cfg['end_date']
    count = 0
    while count < cfg['max_results_per_source']:
        data = get_json(s, 'https://api.openalex.org/works', params=params)
        works = data.get('results', [])
        if not works:
            break
        for w in works:
            src = ((w.get('primary_location') or {}).get('source') or {})
            yield record(w.get('title'), abstract_from_index(w.get('abstract_inverted_index')),
                         w.get('doi'), w.get('id'), w.get('publication_date'),
                         src.get('display_name'), src.get('issn') or src.get('issn_l'), 'openalex')
            count += 1
            if count >= cfg['max_results_per_source']:
                break
        params['cursor'] = (data.get('meta') or {}).get('next_cursor')
        if not params['cursor']:
            break


def crossref(s, cfg):
    # Crossref has no boolean search: retrieve by the positive terms, then filter locally.
    params = {'query.bibliographic': ' '.join(query.terms(cfg['query_ast'], positive_only=True)),
              'rows': min(1000, cfg['max_results_per_source']), 'cursor': '*',
              'filter': 'type:journal-article',
              'select': 'DOI,title,abstract,URL,published,published-print,published-online,'
                        'container-title,ISSN'}
    if cfg.get('start_date'):
        params['filter'] += ',from-pub-date:' + cfg['start_date']
    if cfg.get('end_date'):
        params['filter'] += ',until-pub-date:' + cfg['end_date']
    if cfg.get('email'):
        params['mailto'] = cfg['email']
    count = 0
    while count < cfg['max_results_per_source']:
        data = get_json(s, 'https://api.crossref.org/works', params=params)
        works = data.get('message', {}).get('items', [])
        if not works:
            break
        for w in works:
            pub = (date_from_parts(w.get('published')) or date_from_parts(w.get('published-print'))
                   or date_from_parts(w.get('published-online')))
            yield record((w.get('title') or [''])[0], w.get('abstract'), w.get('DOI'),
                         w.get('URL'), pub, (w.get('container-title') or [''])[0],
                         w.get('ISSN'), 'crossref')
            count += 1
            if count >= cfg['max_results_per_source']:
                break
        params['cursor'] = data.get('message', {}).get('next-cursor')
        if not params['cursor']:
            break
        time.sleep(.2)


def semantic_scholar(s, cfg):
    # Bulk search supports boolean queries and returns up to 1000 papers per request.
    key = cfg.get('semantic_scholar_api_key')
    headers = {'x-api-key': key} if key else None
    params = {'query': query.to_semantic_scholar(cfg['query_ast']),
              'fields': 'title,abstract,url,externalIds,publicationDate,year,journal'}
    if cfg.get('start_date') or cfg.get('end_date'):
        params['publicationDateOrYear'] = f"{cfg.get('start_date') or ''}:{cfg.get('end_date') or ''}"
    count = 0
    while count < cfg['max_results_per_source']:
        data = get_json(s, 'https://api.semanticscholar.org/graph/v1/paper/search/bulk',
                        params=params, headers=headers)
        works = data.get('data') or []
        if not works:
            break
        for w in works:
            journal = w.get('journal') or {}
            ids = w.get('externalIds') or {}
            yield record(w.get('title'), w.get('abstract'), ids.get('DOI'), w.get('url'),
                         w.get('publicationDate') or (str(w['year']) if w.get('year') else None),
                         journal.get('name'), None, 'semantic_scholar')
            count += 1
            if count >= cfg['max_results_per_source']:
                break
        if not data.get('token'):
            break
        params['token'] = data['token']
        time.sleep(1.1)


SOURCES = {'openalex': openalex, 'crossref': crossref, 'semantic_scholar': semantic_scholar}


def fetch(name, cfg):
    """Run one source with its own HTTP session; keep partial results on failure."""
    batch = []
    try:
        for item in SOURCES[name](session(), cfg):
            batch.append(item)
        LOG.info('%s: %s retrieved', name, len(batch))
    except (requests.RequestException, ValueError) as exc:
        LOG.warning('%s failed after %s records: %s', name, len(batch), exc)
    return batch


def validate(cfg):
    if cfg.get('query') and cfg.get('keywords'):
        raise ValueError('set either query or keywords, not both')
    if not cfg.get('query'):
        if not cfg.get('keywords') or not all(isinstance(x, str) and x.strip() for x in cfg['keywords']):
            raise ValueError('set query, e.g. "flood susceptibility" AND (chenab OR indus)')
        if cfg['keyword_mode'] not in ('AND', 'OR'):
            raise ValueError('keyword_mode must be AND or OR')
        cfg['query'] = query.from_keywords(cfg['keywords'], cfg['keyword_mode'])
    cfg['query_ast'] = query.parse(cfg['query'])
    if not cfg.get('paper_sources'):
        cfg['paper_sources'] = ['openalex']
    if set(cfg['paper_sources']) - {'openalex', 'crossref', 'semantic_scholar'}:
        raise ValueError('Unsupported paper source')
    if cfg.get('quartile_source') not in (None, 'scimago', 'jcr'):
        raise ValueError('quartile_source must be None, scimago or jcr')
    if set(cfg.get('quartiles', [])) - {'Q1', 'Q2', 'Q3', 'Q4'}:
        raise ValueError('Invalid quartile value')
    if cfg.get('quartiles') and not cfg.get('quartile_source'):
        raise ValueError('quartiles require quartile_source')
    if cfg.get('quartile_year') not in ('publication_year', 'latest'):
        raise ValueError('quartile_year must be publication_year or latest')
    if cfg.get('missing_abstract_policy') not in ('keep', 'exclude'):
        raise ValueError('missing_abstract_policy must be keep or exclude')
    if cfg.get('output_format') not in ('csv', 'json', 'xlsx'):
        raise ValueError('Invalid output_format')
    if cfg['max_papers'] < 1 or cfg['max_results_per_source'] < 1:
        raise ValueError('Paper limits must be positive')
    for field in ('start_date', 'end_date'):
        if cfg.get(field):
            date.fromisoformat(cfg[field])
    if cfg.get('start_date') and cfg.get('end_date') and cfg['start_date'] > cfg['end_date']:
        raise ValueError('start_date is after end_date')


def search_text(paper):
    return (paper['title'] + ' ' + paper['abstract']).casefold()


def filter_steps(cfg):
    """Ordered (label, predicate) filters; main() logs the count left after each."""
    steps = [('has title', lambda p: bool(p['title'])),
             ('matches query', lambda p: query.evaluate(cfg['query_ast'], search_text(p)))]
    if cfg['missing_abstract_policy'] == 'exclude':
        steps.append(('has abstract', lambda p: bool(p['abstract'])))
    if cfg.get('start_date'):
        steps.append((f"on/after {cfg['start_date']}",
                      lambda p: bool(p['publication_date']) and p['publication_date'] >= cfg['start_date']))
    if cfg.get('end_date'):
        steps.append((f"on/before {cfg['end_date']}",
                      lambda p: bool(p['publication_date']) and p['publication_date'] <= cfg['end_date']))
    return steps


def merge_papers(papers):
    merged = {}
    title_keys = {}
    for p in papers:
        dk = 'doi:' + p['doi'] if p['doi'] else None
        tk = norm_title(p['title'])
        key = (merged.get(dk) and dk) or title_keys.get(tk) if tk else None
        if key is None:
            key = dk or ('title:' + tk)
            if key in merged:
                key += ':' + str(len(merged))
            merged[key] = p.copy()
        else:
            old = merged[key]
            old['paper_sources'] = ';'.join(sorted(set(old['paper_sources'].split(';') + [p['paper_sources']])))
            for field in ('title', 'abstract', 'url', 'doi', 'publication_date', 'year', 'journal', 'issn'):
                if not old.get(field) or (field == 'abstract' and len(str(p.get(field) or '')) > len(str(old[field]))):
                    old[field] = p.get(field)
        if tk:
            title_keys[tk] = key
    return list(merged.values())


def load_rankings(cfg):
    source = cfg.get('quartile_source')
    if not source:
        return None
    path = ROOT / cfg['ranking_files'][source]
    if not path.exists():
        raise FileNotFoundError(f'Ranking file missing: {path}. See README.md for CSV format.')
    df = pd.read_csv(path, dtype=str).fillna('')
    required = {'issn', 'year', 'category', 'quartile'}
    if not required.issubset(df.columns):
        raise ValueError(f'{path}: required columns are {sorted(required)}')
    df['quartile'] = df['quartile'].str.strip().str.upper()
    df['year'] = pd.to_numeric(df['year'], errors='coerce')
    df['category_norm'] = df['category'].str.strip().str.casefold()
    df = df[df['quartile'].isin(['Q1', 'Q2', 'Q3', 'Q4']) & df['year'].notna()].copy()
    df['issn_list'] = df['issn'].apply(issns)
    return df.explode('issn_list')


def apply_rankings(papers, cfg):
    ranks = load_rankings(cfg)
    if ranks is None:
        return papers
    categories = {x.casefold().strip() for x in cfg.get('subject_categories', [])}
    if categories:
        ranks = ranks[ranks['category_norm'].isin(categories)]
    by_issn = {k: group for k, group in ranks.groupby('issn_list') if k}
    result = []
    for p in papers:
        candidates = [by_issn[k] for k in issns(p.get('issn')) if k in by_issn]
        if not candidates:
            if not cfg.get('quartiles'):
                result.append(p)
            continue
        options = pd.concat(candidates).drop_duplicates()
        if cfg['quartile_year'] == 'publication_year':
            options = options[options['year'] == p.get('year')]
        elif not options.empty:
            options = options[options['year'] == options['year'].max()]
        if cfg.get('quartiles'):
            options = options[options['quartile'].isin(cfg['quartiles'])]
        if options.empty:
            if not cfg.get('quartiles'):
                result.append(p)
            continue
        # Preserve multiple category-specific rankings by emitting one row per distinct ranking.
        for _, r in options.drop_duplicates(subset=['year', 'category', 'quartile']).iterrows():
            item = p.copy()
            item.update(quartile=r['quartile'], quartile_source=cfg['quartile_source'],
                        quartile_year=int(r['year']), quartile_category=r['category'])
            result.append(item)
    return result


def main():
    cfg = CONFIG.copy()
    validate(cfg)
    LOG.info('Query: %s', cfg['query'])
    names = cfg['paper_sources']
    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        batches = list(pool.map(lambda name: fetch(name, cfg), names))
    collected = [p for batch in batches for p in batch]
    if not collected:
        LOG.warning('No records retrieved; check network, API credentials and query.')
    LOG.info('Filter counts:')
    LOG.info('  %6s  %s', len(collected), 'retrieved (all sources)')
    papers = merge_papers(collected)
    LOG.info('  %6s  %s', len(papers), 'after deduplication')
    with_abstract = sum(1 for p in papers if p['abstract'])
    LOG.info('  %6s    %s', with_abstract, '- with abstract')
    for term in query.terms(cfg['query_ast']):
        hits = sum(1 for p in papers if term.casefold() in search_text(p))
        LOG.info('  %6s    %s', hits, f'- contains "{term}"')
    for label, check in filter_steps(cfg):
        papers = [p for p in papers if check(p)]
        LOG.info('  %6s  %s', len(papers), label)
    if collected and not papers:
        LOG.warning('No record matches the query in its title/abstract; '
                    'check the per-term counts above and loosen the query (e.g. use OR).')
    papers = papers[:cfg['max_papers']]
    LOG.info('  %6s  %s', len(papers), f"max_papers ({cfg['max_papers']})")
    papers = apply_rankings(papers, cfg)
    if cfg.get('quartile_source'):
        ranked = sum(1 for p in papers if p.get('quartile'))
        label = f"rankings ({cfg['quartile_source']}{', ' + '/'.join(cfg['quartiles']) if cfg.get('quartiles') else ''})"
        LOG.info('  %6s  %s rows, %s with quartile', len(papers), label, ranked)
    df = pd.DataFrame(papers).reindex(columns=FIELDS)
    output = ROOT / cfg['output_path']
    output.parent.mkdir(parents=True, exist_ok=True)
    if cfg['output_format'] == 'csv':
        df.to_csv(output, index=False, encoding='utf-8-sig')
    elif cfg['output_format'] == 'json':
        df.to_json(output, orient='records', force_ascii=False, indent=2)
    else:
        df.to_excel(output, index=False)
    LOG.info('Saved %s rows to %s', len(df), output)
    return df


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    main()
