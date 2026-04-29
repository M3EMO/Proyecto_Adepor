"""
[adepor research workflow] Helper para buscar papers academicos.

Soporta dos backends:
- semanticscholar (default): API que usa Allen ASTA. Rate limit ESTRICTO sin key.
- arxiv: arxiv.org API. Mas permisivo, sin auth, requiere IP control.

Decision del usuario 2026-04-28: cada decision tecnica nueva (planes, schemas,
modelos, parametros) debe estar fundamentada en investigacion academica.
Workflow:
1. py scripts/research/buscar_papers.py "<query>" --topic copa_modelado --limit 10 [--backend arxiv]
2. Output: docs/papers/<topic>.md con tabla titulo/year/citations/url/abstract
3. Decision tecnica fundamentada con [REF: docs/papers/<topic>.md] en codigo.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DOCS_PAPERS = ROOT / "docs" / "papers"

SS_API = "https://api.semanticscholar.org/graph/v1/paper/search"
SS_FIELDS = "title,abstract,year,authors,citationCount,url,venue,externalIds"
ARXIV_API = "http://export.arxiv.org/api/query"


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


def search(query: str, limit: int = 10, backend: str = "semanticscholar"):
    if backend == "arxiv":
        return _search_arxiv(query, limit)
    return _search_semantic_scholar(query, limit)


def render_md(query, topic, papers):
    lines = []
    lines.append(f"# Papers: {topic}")
    lines.append("")
    lines.append(f"> **Query:** `{query}`")
    lines.append(f"> **Fecha:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"> **Source:** Semantic Scholar API (free, sin login)")
    lines.append(f"> **N resultados:** {len(papers)}")
    lines.append("")
    lines.append("## Resultados")
    lines.append("")
    for i, p in enumerate(papers, 1):
        title = p.get("title", "(sin titulo)")
        year = p.get("year", "?")
        cits = p.get("citationCount", 0)
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
        lines.append(f"- **Citations:** {cits}")
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
    ap.add_argument("--backend", default="semanticscholar", choices=["semanticscholar", "arxiv"])
    args = ap.parse_args()

    print(f"Query: {args.query}")
    print(f"Topic: {args.topic}")
    print(f"Backend: {args.backend}")
    print(f"Limit: {args.limit}")
    print()

    try:
        papers = search(args.query, args.limit, backend=args.backend)
    except urllib.error.HTTPError as e:
        if e.code == 429 and args.backend == "semanticscholar":
            print("Rate limit (429). Fallback a arxiv...")
            papers = search(args.query, args.limit, backend="arxiv")
        else:
            raise

    DOCS_PAPERS.mkdir(parents=True, exist_ok=True)
    out_path = DOCS_PAPERS / f"{args.topic}.md"
    md = render_md(args.query, args.topic, papers)
    # Append-mode si ya existe (acumular queries por topic)
    if out_path.exists():
        existing = out_path.read_text(encoding="utf-8")
        md = existing.rstrip() + "\n\n---\n\n" + md
    out_path.write_text(md, encoding="utf-8")
    print(f"  -> {out_path} ({len(papers)} papers)")
    return papers


if __name__ == "__main__":
    main()
