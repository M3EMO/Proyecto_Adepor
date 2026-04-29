"""
[adepor research workflow] Helper para buscar papers academicos.

Soporta tres backends FREE sin auth:
- openalex (DEFAULT, recomendado): https://api.openalex.org. Corpus 240M+ works.
  No rate limit estricto (10 req/s con email en User-Agent o 100k/day anonymous).
  Devuelve citation counts, venue, year, DOI, abstract reconstruido desde inverted index.
- semanticscholar: free, sin login. Rate limit AGRESIVO (HTTP 429 frecuente).
  Util como fallback alternativo si OpenAlex tampoco da resultados relevantes.
- arxiv: arxiv.org API. Sin auth, sin rate limit fuerte. Sin citation counts (limita
  filtrado por relevancia). Util como ultimo fallback.

Decision usuario 2026-04-28 + 2026-04-29: cada decision tecnica nueva (planes,
schemas, modelos, parametros) debe estar fundamentada en investigacion academica.
Asta MCP API requiere form humano + espera 1-3 dias; usuario opto por OpenAlex
(equivalente funcional, sin auth).

Workflow:
1. py scripts/research/buscar_papers.py "<query>" --topic copa_modelado --limit 10
2. Output: docs/papers/<topic>.md con tabla titulo/year/citations/url/abstract
3. Decision tecnica fundamentada con [REF: docs/papers/<topic>.md] en codigo.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DOCS_PAPERS = ROOT / "docs" / "papers"

# Backends
OPENALEX_API = "https://api.openalex.org/works"
OPENALEX_FIELDS = ("id,title,publication_year,cited_by_count,authorships,"
                   "abstract_inverted_index,doi,primary_location,open_access,"
                   "type,referenced_works_count")

SS_API = "https://api.semanticscholar.org/graph/v1/paper/search"
SS_FIELDS = "title,abstract,year,authors,citationCount,url,venue,externalIds"

ARXIV_API = "http://export.arxiv.org/api/query"

# Email opcional en User-Agent activa "polite pool" en OpenAlex con higher rate limits
OPENALEX_EMAIL = os.environ.get("OPENALEX_EMAIL", "adepor-research@local")


def _reconstruct_abstract(inverted_index):
    """OpenAlex devuelve abstract como inverted index: {word: [positions]}.
    Reconstruye texto en orden lineal."""
    if not inverted_index or not isinstance(inverted_index, dict):
        return ""
    pos_to_word = {}
    for word, positions in inverted_index.items():
        for p in positions:
            pos_to_word[p] = word
    if not pos_to_word:
        return ""
    max_pos = max(pos_to_word.keys())
    return " ".join(pos_to_word.get(i, "") for i in range(max_pos + 1)).strip()


def _search_openalex(query: str, limit: int):
    """OpenAlex search via /works endpoint. Free, sin auth, robusto.

    Doc: https://docs.openalex.org/api-entities/works/search-works
    """
    params = {
        "search": query,
        "per-page": min(limit, 100),
        "select": OPENALEX_FIELDS,
    }
    url = OPENALEX_API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"Adepor-Research/1.0 (mailto:{OPENALEX_EMAIL})"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    out = []
    for w in data.get("results", []):
        title = w.get("title") or ""
        year = w.get("publication_year")
        cits = w.get("cited_by_count", 0)
        authors = [
            {"name": (a.get("author") or {}).get("display_name", "")}
            for a in (w.get("authorships") or [])
        ]
        primary = w.get("primary_location") or {}
        source = primary.get("source") or {}
        venue = source.get("display_name") or "(sin venue)"
        url_paper = primary.get("landing_page_url") or w.get("id") or ""
        doi = (w.get("doi") or "").replace("https://doi.org/", "")
        abstract = _reconstruct_abstract(w.get("abstract_inverted_index"))
        out.append({
            "title": title,
            "abstract": abstract,
            "year": year,
            "authors": authors,
            "citationCount": cits,
            "url": url_paper,
            "venue": venue,
            "externalIds": {"DOI": doi} if doi else {},
        })
    return out


def _search_semantic_scholar(query: str, limit: int):
    params = {"query": query, "limit": min(limit, 100), "fields": SS_FIELDS}
    url = SS_API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Adepor-Research/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("data", [])


def _search_arxiv(query: str, limit: int):
    """arXiv API devuelve Atom XML. Parse mínimo para extraer campos clave."""
    import xml.etree.ElementTree as ET
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": min(limit, 100),
        "sortBy": "relevance",
    }
    url = ARXIV_API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Adepor-Research/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
    NS = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(body)
    out = []
    for entry in root.findall("atom:entry", NS):
        title = (entry.findtext("atom:title", default="", namespaces=NS) or "").strip()
        summary = (entry.findtext("atom:summary", default="", namespaces=NS) or "").strip()
        published = entry.findtext("atom:published", default="", namespaces=NS) or ""
        year = published[:4] if published else None
        link_el = entry.find("atom:id", NS)
        link = (link_el.text if link_el is not None else "") or ""
        arxiv_id = link.rsplit("/", 1)[-1] if link else ""
        authors = [
            a.findtext("atom:name", default="", namespaces=NS)
            for a in entry.findall("atom:author", NS)
        ]
        out.append({
            "title": title,
            "abstract": summary,
            "year": year,
            "authors": [{"name": n} for n in authors],
            "citationCount": None,  # arXiv no provee
            "url": link,
            "venue": "arXiv",
            "externalIds": {"ArXiv": arxiv_id},
        })
    return out


def search(query: str, limit: int = 10, backend: str = "openalex"):
    if backend == "openalex":
        return _search_openalex(query, limit)
    if backend == "arxiv":
        return _search_arxiv(query, limit)
    if backend == "semanticscholar":
        return _search_semantic_scholar(query, limit)
    raise ValueError(f"Backend no soportado: {backend}")


_BACKEND_LABEL = {
    "openalex": "OpenAlex API (free, sin auth, 240M+ works)",
    "semanticscholar": "Semantic Scholar API (free, sin login)",
    "arxiv": "arXiv API (free, sin auth)",
}


def render_md(query, topic, papers, backend="openalex"):
    lines = []
    lines.append(f"# Papers: {topic}")
    lines.append("")
    lines.append(f"> **Query:** `{query}`")
    lines.append(f"> **Fecha:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"> **Source:** {_BACKEND_LABEL.get(backend, backend)}")
    lines.append(f"> **N resultados:** {len(papers)}")
    lines.append("")
    lines.append("## Resultados")
    lines.append("")
    for i, p in enumerate(papers, 1):
        title = p.get("title", "(sin titulo)")
        year = p.get("year", "?")
        cits = p.get("citationCount")
        cits_str = str(cits) if cits is not None else "n/a"
        venue = p.get("venue") or "(sin venue)"
        authors = ", ".join(a.get("name", "") for a in (p.get("authors") or [])[:3])
        if not authors: authors = "(sin autores)"
        url = p.get("url") or ""
        ext = p.get("externalIds") or {}
        doi = ext.get("DOI", "")
        arxiv = ext.get("ArXiv", "")
        abstract = (p.get("abstract") or "(sin abstract)").strip()
        if len(abstract) > 600: abstract = abstract[:600] + "..."

        lines.append(f"### {i}. {title}")
        lines.append("")
        lines.append(f"- **Year:** {year}")
        lines.append(f"- **Citations:** {cits_str}")
        lines.append(f"- **Venue:** {venue}")
        lines.append(f"- **Authors:** {authors}")
        if url: lines.append(f"- **URL:** {url}")
        if doi: lines.append(f"- **DOI:** [{doi}](https://doi.org/{doi})")
        if arxiv: lines.append(f"- **arXiv:** [{arxiv}](https://arxiv.org/abs/{arxiv})")
        lines.append("")
        lines.append(f"**Abstract:** {abstract}")
        lines.append("")
        lines.append("**Relevancia:** _(pendiente analisis)_")
        lines.append("")
        lines.append("---")
        lines.append("")
    lines.append("## Conclusion")
    lines.append("")
    lines.append("_(Pendiente: sintetizar hallazgos relevantes para la decision tecnica.)_")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", help="Query string")
    ap.add_argument("--topic", required=True, help="Slug del topic (ej. copa_modelado)")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--backend",
                    default=os.environ.get("ADEPOR_RESEARCH_BACKEND", "openalex"),
                    choices=["openalex", "semanticscholar", "arxiv"],
                    help="Default openalex (free, robusto). Override via env "
                         "ADEPOR_RESEARCH_BACKEND.")
    args = ap.parse_args()

    print(f"Query: {args.query}")
    print(f"Topic: {args.topic}")
    print(f"Backend: {args.backend}")
    print(f"Limit: {args.limit}")
    print()

    backend_used = args.backend
    try:
        papers = search(args.query, args.limit, backend=args.backend)
    except urllib.error.HTTPError as e:
        if args.backend == "openalex":
            print(f"OpenAlex error (HTTP {e.code}). Fallback a semanticscholar...")
            backend_used = "semanticscholar"
            try:
                papers = search(args.query, args.limit, backend="semanticscholar")
            except urllib.error.HTTPError as e2:
                if e2.code == 429:
                    print("S2 rate limit. Fallback a arxiv...")
                    backend_used = "arxiv"
                    papers = search(args.query, args.limit, backend="arxiv")
                else:
                    raise
        elif e.code == 429 and args.backend == "semanticscholar":
            print("Rate limit (429). Fallback a arxiv...")
            backend_used = "arxiv"
            papers = search(args.query, args.limit, backend="arxiv")
        else:
            raise

    DOCS_PAPERS.mkdir(parents=True, exist_ok=True)
    out_path = DOCS_PAPERS / f"{args.topic}.md"
    md = render_md(args.query, args.topic, papers, backend=backend_used)
    # Append-mode si ya existe (acumular queries por topic)
    if out_path.exists():
        existing = out_path.read_text(encoding="utf-8")
        md = existing.rstrip() + "\n\n---\n\n" + md
    out_path.write_text(md, encoding="utf-8")
    print(f"  -> {out_path} ({len(papers)} papers, backend={backend_used})")
    return papers


if __name__ == "__main__":
    main()
