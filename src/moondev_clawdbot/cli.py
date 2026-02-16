from __future__ import annotations

import time
from typing import Optional
import typer
from rich.console import Console

from .config import load_settings
from .sources.base import source_names
from .pipeline import ingest as ingest_run, score as score_run
from .storage import Store
from .models import Item
from .alerts import alert as send_alert
from .export import export_reports


app = typer.Typer(add_completion=False, help="MoonDev Clawdbot - ingest/score/alert social arbitrage items")
console = Console()

sources_app = typer.Typer(help="Manage sources")
run_app = typer.Typer(help="Run pipeline")
app.add_typer(sources_app, name="sources")
app.add_typer(run_app, name="run")


def _parse_sources(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


@sources_app.command("list")
def sources_list():
    for n in source_names():
        typer.echo(n)


@app.command()
def ingest(
    sources: str = typer.Option("tiktok,x_mock", help="Comma-separated sources"),
    env_file: Optional[str] = typer.Option(None, help="Path to .env"),
):
    settings = load_settings(env_file)
    ingest_run(settings.db_path, _parse_sources(sources))


@app.command()
def score(
    limit: int = typer.Option(200, help="How many unscored items to score"),
    env_file: Optional[str] = typer.Option(None, help="Path to .env"),
):
    settings = load_settings(env_file)
    score_run(settings.db_path, limit=limit)


@app.command("enrich-vision")
def enrich_vision(
    limit: int = typer.Option(50, help="How many items to enrich (max)."),
    provider: str = typer.Option(
        "stub",
        help="stub (default, no credentials) | openai (requires OPENAI_API_KEY + openai pkg)",
    ),
    overwrite: bool = typer.Option(False, help="Overwrite existing metrics.llm_enrich if present."),
    max_images: int = typer.Option(5, help="How many screenshots to send/use per item."),
    env_file: Optional[str] = typer.Option(None, help="Path to .env"),
):
    """Batch vision enrichment.

    Writes output into metrics_json['llm_enrich'].
    """

    from .vision_enrich import enrich_db_vision

    settings = load_settings(env_file)
    n = enrich_db_vision(
        settings.db_path,
        limit=limit,
        provider=(provider or "stub").strip().lower(),
        overwrite=overwrite,
        max_images=max_images,
        source="tiktok",
    )
    console.print(f"[green]Vision-enriched[/green] {n} items (provider={provider})")


@app.command("enrich-llm")
def enrich_llm_compat(
    limit: int = typer.Option(50, help="How many items to enrich (max)."),
    provider: str = typer.Option("stub", help="Alias for enrich-vision --provider"),
    overwrite: bool = typer.Option(False, help="Overwrite existing metrics.llm_enrich if present."),
    max_images: int = typer.Option(5, help="How many screenshots to send/use per item."),
    env_file: Optional[str] = typer.Option(None, help="Path to .env"),
):
    """Backward-compatible alias for `enrich-vision`."""

    return enrich_vision(
        limit=limit,
        provider=provider,
        overwrite=overwrite,
        max_images=max_images,
        env_file=env_file,
    )


@app.command()
def alert(
    min_score: float = typer.Option(0.65, help="Minimum score to send"),
    top_k: int = typer.Option(10, help="Max items to send"),
    channel: str = typer.Option("auto", help="stdout|telegram|discord|auto"),
    env_file: Optional[str] = typer.Option(None, help="Path to .env"),
):
    settings = load_settings(env_file)
    store = Store(settings.db_path)
    import json

    rows = store.top_items(limit=top_k, min_score=min_score)
    items: list[Item] = []
    for r in rows:
        metrics = {}
        try:
            metrics = json.loads(r.get("metrics_json") or "{}")
        except Exception:
            metrics = {}
        items.append(
            Item(
                item_id=r["item_id"],
                source=r["source"],
                url=r["url"],
                title=r["title"],
                text=r["text"],
                metrics=metrics,
                score=r["score"],
                created_at=r["created_at"],
                fetched_at=r["fetched_at"],
                raw=None,
            )
        )
    send_alert(settings, items, channel=channel)


@app.command()
def export(
    out_dir: str = typer.Option("./data/reports", help="Output directory"),
    min_score: float = typer.Option(0.0, help="Only export items >= this score"),
    limit: int = typer.Option(100, help="How many items to export"),
    env_file: Optional[str] = typer.Option(None, help="Path to .env"),
):
    settings = load_settings(env_file)
    jpath, cpath = export_reports(settings.db_path, out_dir=out_dir, limit=limit, min_score=min_score)
    console.print(f"Wrote {jpath}")
    console.print(f"Wrote {cpath}")


@run_app.command("once")
def run_once(
    sources: str = typer.Option("tiktok,x_mock", help="Comma-separated sources"),
    min_score: float = typer.Option(0.65, help="Minimum score to send"),
    top_k: int = typer.Option(10, help="Max items to send"),
    channel: str = typer.Option("auto", help="stdout|telegram|discord|auto"),
    env_file: Optional[str] = typer.Option(None, help="Path to .env"),
):
    settings = load_settings(env_file)
    ingest_run(settings.db_path, _parse_sources(sources))
    score_run(settings.db_path)

    store = Store(settings.db_path)
    import json

    rows = store.top_items(limit=top_k, min_score=min_score)
    items = []
    for r in rows:
        metrics = {}
        try:
            metrics = json.loads(r.get("metrics_json") or "{}")
        except Exception:
            metrics = {}
        items.append(
            Item(
                item_id=r["item_id"],
                source=r["source"],
                url=r["url"],
                title=r["title"],
                text=r["text"],
                metrics=metrics,
                score=r["score"],
                created_at=r["created_at"],
                fetched_at=r["fetched_at"],
                raw=None,
            )
        )
    send_alert(settings, items, channel=channel)


@run_app.command("daemon")
def run_daemon(
    sources: str = typer.Option("tiktok,x_mock", help="Comma-separated sources"),
    interval_sec: int = typer.Option(300, help="Loop interval (seconds)"),
    min_score: float = typer.Option(0.65, help="Minimum score to send"),
    top_k: int = typer.Option(10, help="Max items to send"),
    channel: str = typer.Option("auto", help="stdout|telegram|discord|auto"),
    env_file: Optional[str] = typer.Option(None, help="Path to .env"),
):
    settings = load_settings(env_file)
    srcs = _parse_sources(sources)
    console.print(f"Running daemon every {interval_sec}s; sources={srcs}")
    while True:
        try:
            ingest_run(settings.db_path, srcs)
            score_run(settings.db_path)
            import json

            store = Store(settings.db_path)
            rows = store.top_items(limit=top_k, min_score=min_score)
            items = []
            for r in rows:
                metrics = {}
                try:
                    metrics = json.loads(r.get("metrics_json") or "{}")
                except Exception:
                    metrics = {}
                items.append(
                    Item(
                        item_id=r["item_id"],
                        source=r["source"],
                        url=r["url"],
                        title=r["title"],
                        text=r["text"],
                        metrics=metrics,
                        score=r["score"],
                        created_at=r["created_at"],
                        fetched_at=r["fetched_at"],
                        raw=None,
                    )
                )
            send_alert(settings, items, channel=channel)
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
        time.sleep(interval_sec)


@app.command()
def ui(
    env_file: Optional[str] = typer.Option(None, help="Path to .env"),
    port: int = typer.Option(8501, help="Streamlit port"),
):
    """Launch the Streamlit dashboard."""
    from .ui.app import run_streamlit

    settings = load_settings(env_file)
    run_streamlit(settings.db_path, port=port)
