#!/usr/bin/env python3
"""Fetch the latest cardiovascular research papers from multiple APIs."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import logging
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

import requests
from xml.etree import ElementTree as ET


USER_AGENT = "CardioLiteratureCollector/1.0 (mailto:research@example.com)"
DEFAULT_KEYWORDS = "aortic stenosis, mitral regurgitation, valvular heart disease, deep learning"
DEFAULT_SOURCES = "pubmed,crossref,openalex"
MAX_RESULTS_PER_KEYWORD = 20
DATA_DIR = Path("data")


@dataclass
class PaperRecord:
    source: str
    keyword: str
    title: str
    authors: str
    doi: str
    publication_date: str
    journal: str
    abstract: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch cardiovascular literature from multiple sources.")
    parser.add_argument("--keywords", default=DEFAULT_KEYWORDS, help="Comma-separated list of keywords to search for.")
    parser.add_argument("--sources", default=DEFAULT_SOURCES, help="Comma-separated list of sources to query.")
    return parser.parse_args()


def normalize_list_argument(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def fetch_pubmed(keyword: str) -> List[PaperRecord]:
    logging.info("Querying PubMed for '%s'", keyword)
    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    search_params = {
        "db": "pubmed",
        "term": keyword,
        "retmode": "json",
        "sort": "pub+date",
        "retmax": str(MAX_RESULTS_PER_KEYWORD),
    }

    try:
        response = requests.get(search_url, params=search_params, headers={"User-Agent": USER_AGENT}, timeout=30)
        response.raise_for_status()
        id_list = response.json().get("esearchresult", {}).get("idlist", [])
    except requests.RequestException as exc:
        logging.error("PubMed search failed: %s", exc)
        return []

    if not id_list:
        logging.info("No PubMed results for '%s'", keyword)
        return []

    fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    fetch_params = {
        "db": "pubmed",
        "id": ",".join(id_list),
        "retmode": "xml",
    }

    try:
        response = requests.get(fetch_url, params=fetch_params, headers={"User-Agent": USER_AGENT}, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        logging.error("PubMed fetch failed: %s", exc)
        return []

    try:
        root = ET.fromstring(response.text)
    except ET.ParseError as exc:
        logging.error("PubMed XML parse error: %s", exc)
        return []

    records: List[PaperRecord] = []
    for article in root.findall("PubmedArticle"):
        title_element = article.find(".//ArticleTitle")
        if title_element is not None:
            title = "".join(title_element.itertext()).strip()
        else:
            title = ""

        abstract_texts = [
            "".join(node.itertext()).strip()
            for node in article.findall(".//Abstract/AbstractText")
            if node is not None
        ]
        abstract = "\n".join(filter(None, abstract_texts))

        authors = []
        for author in article.findall(".//Author"):
            collective_name = author.findtext("CollectiveName")
            if collective_name:
                authors.append(collective_name.strip())
                continue
            last_name = author.findtext("LastName")
            fore_name = author.findtext("ForeName")
            initials = author.findtext("Initials")
            if fore_name or last_name:
                name_parts = [part for part in (fore_name, last_name) if part]
                authors.append(" ".join(name_parts))
            elif initials and last_name:
                authors.append(f"{initials} {last_name}")
        authors_str = "; ".join(authors)

        doi_element = article.find(".//ArticleIdList/ArticleId[@IdType='doi']")
        doi = doi_element.text.strip() if doi_element is not None and doi_element.text else ""

        journal = article.findtext(".//Journal/Title", default="").strip()
        publication_date = extract_pubmed_date(article)

        records.append(
            PaperRecord(
                source="PubMed",
                keyword=keyword,
                title=title,
                authors=authors_str,
                doi=doi,
                publication_date=publication_date,
                journal=journal,
                abstract=abstract,
            )
        )

    return records


def extract_pubmed_date(article: ET.Element) -> str:
    pub_date = article.find(".//JournalIssue/PubDate")
    if pub_date is None:
        pub_date = article.find(".//ArticleDate")
    if pub_date is None:
        return ""

    year = pub_date.findtext("Year")
    month = pub_date.findtext("Month")
    day = pub_date.findtext("Day")

    if month and not month.isdigit():
        try:
            month_datetime = dt.datetime.strptime(month[:3], "%b")
            month = f"{month_datetime.month:02d}"
        except ValueError:
            month = None
    if year and month and day:
        return f"{year}-{int(month):02d}-{int(day):02d}"
    if year and month:
        return f"{year}-{int(month):02d}"
    if year:
        return year
    return ""


def fetch_crossref(keyword: str) -> List[PaperRecord]:
    logging.info("Querying Crossref for '%s'", keyword)
    url = "https://api.crossref.org/works"
    params = {
        "query": keyword,
        "filter": "type:journal-article",
        "sort": "published",
        "order": "desc",
        "rows": str(MAX_RESULTS_PER_KEYWORD),
    }
    try:
        response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=30)
        response.raise_for_status()
        items = response.json().get("message", {}).get("items", [])
    except requests.RequestException as exc:
        logging.error("Crossref request failed: %s", exc)
        return []

    records: List[PaperRecord] = []
    for item in items:
        title = " ".join(item.get("title", [])).strip()
        authors = []
        for author in item.get("author", []) or []:
            given = author.get("given") or ""
            family = author.get("family") or ""
            name = " ".join(part for part in (given, family) if part).strip()
            if not name:
                name = author.get("name", "")
            if name:
                authors.append(name)
        authors_str = "; ".join(authors)

        doi = (item.get("DOI") or "").lower().strip()
        publication_date = extract_crossref_date(item)
        journal = " ".join(item.get("container-title", [])).strip()
        abstract_raw = item.get("abstract", "")
        abstract = clean_html(abstract_raw)

        records.append(
            PaperRecord(
                source="Crossref",
                keyword=keyword,
                title=title,
                authors=authors_str,
                doi=doi,
                publication_date=publication_date,
                journal=journal,
                abstract=abstract,
            )
        )
    return records


def extract_crossref_date(item: Dict) -> str:
    for key in ("published-print", "published-online", "issued", "created"):
        date_info = item.get(key)
        if not date_info:
            continue
        date_parts = date_info.get("date-parts")
        if not date_parts:
            continue
        parts = date_parts[0]
        if not parts:
            continue
        year = parts[0]
        month = parts[1] if len(parts) > 1 else None
        day = parts[2] if len(parts) > 2 else None
        if year and month and day:
            return f"{year:04d}-{month:02d}-{day:02d}"
        if year and month:
            return f"{year:04d}-{month:02d}"
        if year:
            return f"{year:04d}"
    return ""


def fetch_openalex(keyword: str) -> List[PaperRecord]:
    logging.info("Querying OpenAlex for '%s'", keyword)
    url = "https://api.openalex.org/works"
    params = {
        "search": keyword,
        "per-page": str(MAX_RESULTS_PER_KEYWORD),
        "sort": "publication_date:desc",
    }
    try:
        response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=30)
        response.raise_for_status()
        results = response.json().get("results", [])
    except requests.RequestException as exc:
        logging.error("OpenAlex request failed: %s", exc)
        return []

    records: List[PaperRecord] = []
    for item in results:
        title = (item.get("title") or "").strip()
        authors = []
        for authorship in item.get("authorships", []) or []:
            author_obj = authorship.get("author") or {}
            name = author_obj.get("display_name")
            if name:
                authors.append(name)
        authors_str = "; ".join(authors)

        doi = (item.get("ids", {}).get("doi") or "").replace("https://doi.org/", "").strip()
        publication_date = item.get("publication_date") or ""
        journal = (
            item.get("primary_location", {})
            .get("source", {})
            .get("display_name", "")
            .strip()
        )
        abstract = decode_openalex_abstract(item.get("abstract_inverted_index"))

        records.append(
            PaperRecord(
                source="OpenAlex",
                keyword=keyword,
                title=title,
                authors=authors_str,
                doi=doi,
                publication_date=publication_date,
                journal=journal,
                abstract=abstract,
            )
        )
    return records


def decode_openalex_abstract(index: Optional[Dict[str, List[int]]]) -> str:
    if not index:
        return ""
    positions: Dict[int, str] = {}
    for word, idxs in index.items():
        for idx in idxs:
            positions[idx] = word
    abstract_words = [positions[i] for i in sorted(positions)]
    return " ".join(abstract_words)


def clean_html(value: str) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", "", value)
    text = text.replace("\n", " ").strip()
    return text


def deduplicate_records(records: Iterable[PaperRecord]) -> List[PaperRecord]:
    seen: Dict[str, PaperRecord] = {}
    for record in records:
        key = record.doi.lower() if record.doi else ""
        if not key:
            normalized_title = record.title.lower().strip()
            key = f"title:{normalized_title}|date:{record.publication_date}"
        if key not in seen:
            seen[key] = record
    return list(seen.values())


def write_csv(records: List[PaperRecord], timestamp: str) -> Path:
    DATA_DIR.mkdir(exist_ok=True)
    dated_path = DATA_DIR / f"literature_results_{timestamp}.csv"
    latest_path = DATA_DIR / "literature_results.csv"

    fieldnames = ["source", "keyword", "title", "authors", "doi", "publication_date", "journal", "abstract"]
    with dated_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_dict())

    # Write/overwrite the latest file as a convenience pointer.
    with latest_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_dict())

    logging.info("Saved %d records to %s", len(records), dated_path)
    return dated_path


def write_markdown_summary(records: List[PaperRecord], timestamp: str) -> Path:
    DATA_DIR.mkdir(exist_ok=True)
    md_path = DATA_DIR / f"literature_summary_{timestamp}.md"
    header = (
        "| Source | Keyword | Title | Authors | Journal | Publication Date | DOI |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
    )
    with md_path.open("w", encoding="utf-8") as md_file:
        md_file.write(f"# Cardiovascular Literature Summary ({timestamp})\n\n")
        md_file.write(header)
        for record in records:
            title = record.title.replace("|", "\|")
            authors = record.authors.replace("|", "\|")
            journal = record.journal.replace("|", "\|")
            doi_display = record.doi or ""
            if doi_display and not doi_display.startswith("http"):
                doi_display = f"https://doi.org/{doi_display}"
            md_file.write(
                f"| {record.source} | {record.keyword} | {title} | {authors} | {journal} | {record.publication_date} | {doi_display} |\n"
            )
    logging.info("Saved Markdown summary to %s", md_path)
    return md_path


def main() -> None:
    configure_logging()
    args = parse_args()
    keywords = normalize_list_argument(args.keywords)
    sources = normalize_list_argument(args.sources)

    if not keywords:
        logging.warning("No keywords provided. Exiting without fetching data.")
        return
    if not sources:
        logging.warning("No sources provided. Exiting without fetching data.")
        return

    fetchers: Dict[str, Callable[[str], List[PaperRecord]]] = {
        "pubmed": fetch_pubmed,
        "crossref": fetch_crossref,
        "openalex": fetch_openalex,
    }

    all_records: List[PaperRecord] = []
    for source in sources:
        fetcher = fetchers.get(source.lower())
        if not fetcher:
            logging.warning("Source '%s' is not supported and will be skipped.", source)
            continue
        for keyword in keywords:
            try:
                source_records = fetcher(keyword)
                all_records.extend(source_records)
            except Exception as exc:  # Catch-all to ensure workflow continues
                logging.error("Failed to fetch from %s for '%s': %s", source, keyword, exc)

    if not all_records:
        logging.warning("No records retrieved from any source.")

    unique_records = deduplicate_records(all_records)
    timestamp = dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    write_csv(unique_records, timestamp)
    write_markdown_summary(unique_records, timestamp)


if __name__ == "__main__":
    main()
