# Smart Paper Finder

Find journal papers across OpenAlex, Crossref and Semantic Scholar with one boolean query, e.g. `'flood susceptibility' AND (chenab OR indus) NOT review`. Smart Paper Finder searches all sources in parallel, deduplicates the results, optionally attaches journal quartiles (SCImago/JCR), and exports CSV, JSON or XLSX.

## Setup

You can run the tool locally with Python, or in a container with Docker Compose (no local Python needed; see [Running with Docker Compose](#running-with-docker-compose-recommended)). Either way, first create your configuration (next section).

### Local Python

Python 3.10+ recommended.

```bash
pip install -r requirements.txt
python main.py
```

## Configuration

Search settings live in a JSON file, not in code:

- `config.example.json`: a committed template with every setting.
- `config.json`: your own settings. It is listed in `.gitignore`, so your searches stay out of the repository.

Create your copy and edit it:

Linux/macOS:

```bash
cp config.example.json config.json
```

Windows (PowerShell):

```powershell
Copy-Item config.example.json config.json
```

If `config.json` is missing, the tool falls back to `config.example.json` and logs a warning. To use another file, set the `CONFIG_PATH` environment variable (e.g. `CONFIG_PATH=configs/flood.json`). Settings you leave out use the defaults in `config.py`. Unknown setting names are rejected, which catches typos.

| Setting | Default | Description |
|---|---|---|
| `query` | *(required)* | One-line boolean search, see [Query syntax](#query-syntax) |
| `start_date` / `end_date` | `null` | ISO dates (`"2024-01-01"`) or `null` for no limit |
| `paper_sources` | all three | Any of `"openalex"`, `"crossref"`, `"semantic_scholar"` |
| `quartile_source` | `null` | `null`, `"scimago"` or `"jcr"` (see [Ranking datasets](#ranking-datasets)) |
| `quartiles` | `[]` | e.g. `["Q1", "Q2"]`; requires `quartile_source` |
| `quartile_year` | `"publication_year"` | `"publication_year"` or `"latest"` |
| `subject_categories` | `[]` | Ranking categories to match; empty means any |
| `ranking_files` | `data/scimago.csv`, `data/jcr.csv` | Paths to normalized ranking CSVs |
| `missing_abstract_policy` | `"keep"` | `"keep"` or `"exclude"` papers without an abstract |
| `max_papers` | `300` | Maximum papers after deduplication and filtering |
| `max_results_per_source` | `300` | Retrieval budget per API |
| `output_format` | `"csv"` | `"csv"`, `"json"` or `"xlsx"` |
| `output_path` | `"output/papers.csv"` | Output file; keep it under `output/` when using Docker |
| `email` | `null` | Optional contact email for the Crossref polite pool |
| `openalex_api_key` | `""` | OpenAlex API key; needed to page past the first results |
| `semantic_scholar_api_key` | `""` | Optional Semantic Scholar API key; avoids `429` rate-limit errors |

The older `keywords` (list) + `keyword_mode` (`"AND"`/`"OR"`) settings still work in place of `query`, but you can't use both.

### Query syntax

```json
"query": "'flood susceptibility' AND (chenab OR indus OR punjab) NOT review"
```

| Syntax | Meaning | Example |
|---|---|---|
| `word` | single term | `chenab` |
| `'two words'` or `"two words"` | exact phrase | `'flood susceptibility'` |
| `A AND B` | both | `flood AND mapping` |
| `A B` | same as `A AND B` | `flood mapping` |
| `A OR B` | either | `chenab OR indus` |
| `NOT A` | exclude | `NOT review` |
| `( ... )` | grouping | `(chenab OR indus) AND flood` |
| `\'` | apostrophe inside a `'...'` phrase | `'children\'s health'` |

- Operators must be **UPPERCASE**; lowercase `and`/`or`/`not` are treated as search words.
- Precedence: `NOT` > `AND` > `OR`, so `a OR b AND c` means `a OR (b AND c)`. Use parentheses when in doubt.
- Use single quotes for phrases in `config.json`, so they don't clash with the JSON string's double quotes.
- Matching is a case-insensitive **substring** check on title + abstract, so `flood` also matches `floods` and `flooding`.

#### Apostrophes and escaping

A backslash makes the next character literal. Use it for an apostrophe inside a single-quoted phrase: the query `'children\'s health'` searches for the phrase *children's health*.

JSON treats the backslash as its own escape character, so **in `config.json` you must write it twice**:

```json
"query": "'children\\'s health' AND flood"
```

A single backslash (`\'`) is invalid JSON and stops the run with an `invalid JSON` error.

| You want to match | Write in `config.json` |
|---|---|
| the phrase *flood susceptibility* | `'flood susceptibility'` |
| the phrase *children's health* | `'children\\'s health'` |
| the single word *children's* | `children's` (no escape needed outside quotes) |

How each source uses the query:

| Source | Server-side search | Then |
|---|---|---|
| OpenAlex | Full boolean query on title + abstract | Local check |
| Semantic Scholar | Full boolean query (bulk search, translated to `+`, `\|`, `-`) | Local check |
| Crossref | Positive terms only (Crossref has no boolean search) | Local check applies the full query |

Every paper is checked locally against the full query, so results are consistent across sources.

### API keys

API keys go in `config.json` along with the other settings, so you only have one file to manage:

```json
"openalex_api_key": "your-openalex-key",
"semantic_scholar_api_key": "your-semantic-scholar-key"
```

- OpenAlex: get a free key at <https://openalex.org/settings/api>.
- Semantic Scholar: request a free key at <https://www.semanticscholar.org/product/api>.

Leave a key as `""` to run without it. `config.json` is gitignored, so the keys stay out of the repository. Never put real keys in `config.example.json`, because that file is committed.

## Ranking datasets

Set `quartile_source` to `null` to disable quartile lookup, or to `"scimago"` / `"jcr"` to enable it. Ranking datasets are **not included**. Obtain and use them under the publisher's license, then place a normalized CSV at `data/scimago.csv` or `data/jcr.csv` (or edit `ranking_files`).

CSV columns: `issn,year,category,quartile`. See [`data/ranking_template.csv`](data/ranking_template.csv) for the expected format. Its single row (`1234-5678,2024,Remote Sensing,Q1`) is illustrative, not a real ranking, and the file itself is never read by the tool. It is the only CSV tracked by git; `.gitignore` excludes all other `*.csv` files so licensed ranking data is never committed.

For source spreadsheets with different column names, transform to this schema. Include one row per journal, year, subject category, and quartile. Use print or electronic ISSNs as available, separated with semicolons. JCR and SJR quartiles are different systems; categories and years must correspond to the source you selected. Missing journal matches are kept with empty quartile if `quartiles` is `[]`, but excluded when an explicit quartile filter is active.

When `quartile_year` is `"publication_year"`, only exact publication-year matches are accepted. With `"latest"`, only the latest available ranking year **per journal** is used. A journal can have multiple category quartiles, so output can contain multiple rows for one paper. `subject_categories` matches category names exactly, case-insensitively. If you need a single row per paper, select one subject category.

## API details and limitations

- Sources are queried **in parallel**, and each requests only the fields it needs (OpenAlex 200 per page, Crossref up to 1000, Semantic Scholar up to 1000), so a typical run takes seconds.
- OpenAlex: `title_and_abstract.search` filter; abstracts are reconstructed from the inverted index. An API key is required for paging beyond the first page of results (without one you get `401 Unauthorized`); set `openalex_api_key` in `config.json`.
- Crossref: metadata and abstracts where available; many records lack abstracts. Uses `query.bibliographic` with the positive query terms as a relevance search, so many candidates are dropped by the local check. Set `email` to use Crossref's faster polite pool.
- Semantic Scholar: bulk search API (boolean queries, up to 1000 papers per request); optional `semantic_scholar_api_key` in `config.json`. Unauthenticated requests share a rate limit and may fail with `429 Too Many Requests`.
- If a source fails partway through, the records it already retrieved are kept.
- All sources may rank/retrieve candidates differently; the local query check uses case-insensitive **literal substring** matching against title + abstract. Papers without an abstract can only match on their title, so strict `AND` queries may miss them.
- `max_results_per_source` is the retrieval budget per API, not a guarantee of exhaustive results. `max_papers` is applied after deduplication and query/date filtering, **before** journal ranking filters; increase limits when quartile filtering yields few papers.
- Date checks are exact when metadata contains a full date; sources with year-only dates may be represented as January 1 of that year. This is an approximation; be cautious with mid-year boundaries.
- Deduplication uses DOI and normalized title, which can occasionally merge different versions. Semantic Scholar journal records may not include ISSNs; if Crossref/OpenAlex supplies the same paper's ISSN, merging can enrich it.
- Some records may not be journal articles despite source type filters. Review results for rigorous systematic reviews.
- API availability, pricing, pagination, and rate limits change; consult each service's documentation. No API results are guaranteed without valid access and network connectivity.

## Output

`output/papers.csv` by default; set `output_format` and matching `output_path` to use JSON or XLSX. Columns: title, abstract, url, doi, publication_date, year, journal, issn, paper_sources, quartile, quartile_source, quartile_year, quartile_category.

## Running with Docker Compose (recommended)

Docker Compose runs the tool in a container, so you don't need Python or any packages installed locally. The service is defined in `compose.yaml` and the image is built from `Dockerfile`.

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/macOS), or Docker Engine with the Compose plugin (Linux).
- Check the installation with `docker compose version`.
- Outbound internet access (the paper APIs are called at runtime).

### What the container mounts

| Host path     | Container path     | Mode       | Purpose                                          |
|---------------|--------------------|------------|--------------------------------------------------|
| `config.json` | `/app/config.json` | read-only  | Search settings (query, dates, sources)          |
| `data/`       | `/app/data`        | read-only  | Optional ranking CSVs (`scimago.csv`, `jcr.csv`) |
| `output/`     | `/app/output`      | read-write | Results (`papers.csv` / `.json` / `.xlsx`)       |

API keys are read from `config.json` as well.

### Quick start

1. **Create and edit `config.json`** (see [Configuration](#configuration)). Do this **before** the first run: if `config.json` doesn't exist, Docker creates an empty *directory* with that name in its place. If that happens, delete the directory and copy the example again.

   Linux/macOS:

   ```bash
   cp config.example.json config.json
   ```

   Windows (PowerShell):

   ```powershell
   Copy-Item config.example.json config.json
   ```

2. **(Recommended) Add your API keys** to `config.json` (see [API keys](#api-keys)).

3. **(Optional) Add ranking data.** If `quartile_source` is set, place a normalized `data/scimago.csv` or `data/jcr.csv` in `data/` (see [Ranking datasets](#ranking-datasets)).

4. **Create the output folder, then build and run.**

   Linux/macOS:

   ```bash
   mkdir -p output
   docker compose up --build
   ```

   Windows (PowerShell):

   ```powershell
   New-Item -ItemType Directory -Force output | Out-Null
   docker compose up --build
   ```

   The container fetches the papers, writes the output file, and exits. Results go to `./output/` on your host, e.g. `output/papers.csv`.

### Everyday commands

| Task | Command |
|------|---------|
| Run again after editing `config.json` (no rebuild needed) | `docker compose run --rm smart-paper-finder` |
| Rebuild after changing `main.py`, `config.py` or `requirements.txt` | `docker compose build` (or `docker compose up --build`) |
| Run in the background and follow the logs | `docker compose up -d` then `docker compose logs -f` |
| Remove stopped containers and the network | `docker compose down` |
| Remove the built image too | `docker compose down --rmi local` |

### Notes and troubleshooting

- **Config changes:** `config.json` is bind-mounted, so edits take effect on the next run without rebuilding. Code changes require `docker compose build`.
- **`config.json is a directory`:** Docker created it because the file didn't exist when the container started. Delete the `config.json` folder, copy `config.example.json` to `config.json`, and run again.
- **`401 Unauthorized` from OpenAlex / `429` from Semantic Scholar:** set the API keys in `config.json` (see [API keys](#api-keys)), or remove that source from `paper_sources`.
- **`Saved 0 rows`:** the `Filter counts` log shows how many records were retrieved, how many contain each query term, and how many survive each filter. Loosen the query (more `OR` alternatives, shorter phrases) or raise `max_results_per_source`.
- **Permission denied writing `output/` (Linux):** the container runs as non-root UID 10001. Make the folder writable by it with `sudo chown 10001:10001 output`, or use `chmod 777 output` for a quick local test. On Docker Desktop (Windows/macOS) this is normally handled automatically.
- **Windows drive sharing:** if the project is on a drive other than `C:` (e.g. `D:\Papers\...`) and mounts appear empty, make sure Docker Desktop uses the WSL 2 backend or that the drive is shared under *Settings → Resources → File sharing*.
- **Ranking CSVs not found:** `.dockerignore` excludes `*.csv` from the image on purpose. Ranking files are supplied through the `data/` mount, so they must be in the host `data/` folder. The container never downloads licensed ranking datasets.

### Without Compose (plain Docker)

Linux/macOS:

```bash
docker build -t smart-paper-finder .
docker run --rm \
  -v "$(pwd)/config.json:/app/config.json:ro" \
  -v "$(pwd)/data:/app/data:ro" \
  -v "$(pwd)/output:/app/output" \
  smart-paper-finder
```

Windows (PowerShell):

```powershell
docker build -t smart-paper-finder .
docker run --rm `
  -v "${PWD}/config.json:/app/config.json:ro" `
  -v "${PWD}/data:/app/data:ro" `
  -v "${PWD}/output:/app/output" `
  smart-paper-finder
```
