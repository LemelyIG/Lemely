"""Overview-and-chunks binder read for a script over the token budget at the floor.

Spec 2026-10-19 §2b, behind ``binding.claude_chunked_read`` (off by default). An
overview pass on 768 px thumbnails maps the labels page by page; contiguous chunks
under the budget are then read in parallel at full fitted resolution, each with the
map and the previous chunk's last page as overlap; the merge concatenates them in
page order. Every call is priced on its own and stays under the price tier.
"""

from __future__ import annotations

import contextvars
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel, ConfigDict, Field

from lemely.io.binding.label_binder import StreamRead, _StreamOutput, parse_stream_items
from lemely.io.llm.image_fit import FittedImages, estimate_floor_tokens, fit, thumbnails
from lemely.io.prompts.label_binding import (
    CHUNK_VERSION,
    LABEL_BINDING_SYSTEM_PROMPT,
    OVERVIEW_SYSTEM_PROMPT,
    OVERVIEW_VERSION,
    build_chunk_user_prompt,
    build_overview_user_prompt,
)
from lemely.io.providers import ProviderError, is_anthropic_model

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from lemely.core.loose_schemas import MarkScheme
    from lemely.io.gemini import GeminiClient
    from lemely.io.rasterise import RasterisedPage

OVERVIEW_TASK_TAG = "binding_overview"
#: Chunk calls in flight at once. A script has ~3-4 chunks, and the two binder reads
#: run together under batch concurrency, so an uncapped fan-out meets the rate limit.
_MAX_CHUNK_WORKERS = 4


class PageEntry(BaseModel):
    """One page of the overview: its labels and whether its writing carries on."""

    model_config = ConfigDict(extra="ignore")
    page: int
    labels: list[str] = Field(default_factory=list)
    continues_to_next: bool = False


class PageMap(BaseModel):
    """The overview's map of the whole script, 0-based page indices."""

    model_config = ConfigDict(extra="ignore")
    pages: list[PageEntry]

    def labels_on(self, pages: Iterable[int]) -> list[str]:
        """The labels the map puts on ``pages``, in page order."""
        wanted = set(pages)
        return [label for entry in self.pages if entry.page in wanted for label in entry.labels]

    def covers(self, page_count: int) -> bool:
        """Whether the map has each of pages 0..page_count-1 exactly once (so not 1-based)."""
        return sorted(entry.page for entry in self.pages) == list(range(page_count))

    def text(self) -> str:
        """The map as lines of 0-based pages, as the image labels number them (chunk prompt)."""
        lines = []
        for entry in sorted(self.pages, key=lambda e: e.page):
            line = f"page {entry.page}: {', '.join(entry.labels) or 'no label'}"
            if entry.continues_to_next:
                line += "; writing continues onto the next page"
            lines.append(line)
        return "\n".join(lines)


def plan_chunks(page_tokens: Sequence[int], budget: int) -> list[range]:
    """Contiguous page ranges each under ``budget`` with the overlap page counted.

    A page over the budget on its own is a chunk of its own.
    """
    chunks: list[range] = []
    start = 0
    while start < len(page_tokens):
        used = page_tokens[start - 1] if start > 0 else 0
        end = start
        while end < len(page_tokens) and (end == start or used + page_tokens[end] <= budget):
            used += page_tokens[end]
            end += 1
        chunks.append(range(start, end))
        start = end
    return chunks


def merge_chunk_reads(reads: Sequence[StreamRead]) -> StreamRead:
    """The chunks' items in chunk order (already on whole-script pages); drops summed."""
    drops: dict[str, int] = {}
    for read in reads:
        for reason, count in read.drops.items():
            drops[reason] = drops.get(reason, 0) + count
    return StreamRead(items=[item for read in reads for item in read.items], drops=drops)


class ChunkedLabelReader:
    """Reads a long script as an overview plus chunks; shared by both binder reads."""

    def __init__(self, client: GeminiClient, *, tier_guard: bool = False) -> None:
        self._client = client
        #: True when the reader exists only as the tier guard, with
        #: ``binding.claude_chunked_read`` off.
        self.tier_guard = tier_guard
        self._lock = threading.Lock()
        self._maps: dict[str, PageMap] = {}
        self._fit_locks: dict[str, threading.Lock] = {}
        self._fits: dict[str, FittedImages] = {}
        self._log = structlog.get_logger().bind(component="label_binder", chunked_read=True)

    @staticmethod
    def _digest(pages: list[RasterisedPage]) -> str:
        h = hashlib.sha256()
        for page in pages:
            h.update(len(page.png_bytes).to_bytes(8, "big"))
            h.update(page.png_bytes)
        return h.hexdigest()

    def _fit(self, pages: list[RasterisedPage]) -> FittedImages:
        key = self._digest(pages)
        with self._lock:
            key_lock = self._fit_locks.setdefault(key, threading.Lock())
        # Single-flight per script: the two reads start together and encode the pages once.
        with key_lock:
            with self._lock:
                fitted = self._fits.get(key)
            if fitted is None:
                g = self._client._settings.gemini
                fitted = fit(
                    [p.png_bytes for p in pages],
                    byte_limit=None,
                    token_budget=g.claude_image_token_budget,
                    floor_px=g.claude_image_floor_px,
                    enhance=g.claude_image_enhance is True,
                )
                with self._lock:
                    self._fits[key] = fitted
        return fitted

    def applies(self, pages: list[RasterisedPage], model: str | None) -> bool:
        """A claude- read whose pages are still over the token budget at the floor.

        Decided from the page headers alone; the full fit runs only on the chunked path.
        """
        if model is None or not is_anthropic_model(model):
            return False
        g = self._client._settings.gemini
        try:
            floor_tokens = estimate_floor_tokens(
                [p.png_bytes for p in pages], floor_px=g.claude_image_floor_px
            )
        except ProviderError:
            if not self.tier_guard:
                raise
            # The guard adds no failure of its own: the single call's own fit reports it.
            return False
        return floor_tokens > g.claude_image_token_budget

    def _page_map(
        self, pages: list[RasterisedPage], mark_scheme: MarkScheme, *, model: str
    ) -> PageMap:
        key = self._digest(pages)
        # Held across the call on purpose: the two reads start together and must share one overview.
        with self._lock:
            page_map = self._maps.get(key)
            if page_map is None:
                page_map = self._client.generate_structured(
                    system_prompt=OVERVIEW_SYSTEM_PROMPT,
                    user_prompt=build_overview_user_prompt(mark_scheme, page_count=len(pages)),
                    image_parts=list(
                        # Plain: the provider's own fit enhances the thumbnails once.
                        thumbnails([p.png_bytes for p in pages], enhance=False)
                    ),
                    response_schema=PageMap,
                    prompt_version=OVERVIEW_VERSION,
                    model=model,
                    task_tag=OVERVIEW_TASK_TAG,
                    cache_mode="bypass",
                )
                self._maps[key] = page_map
                self._log.info("binding_chunked_read", role="overview", pages=len(pages))
        return page_map

    def _read_chunk(
        self,
        pages: list[RasterisedPage],
        mark_scheme: MarkScheme,
        page_map: PageMap | None,
        chunk: range,
        number: int,
        *,
        model: str,
        media_resolution: str,
        extra_cache_key: str,
        task_tag: str,
    ) -> StreamRead:
        overlap = chunk.start > 0
        first = chunk.start - 1 if overlap else chunk.start
        sent = pages[first : chunk.stop]
        raw = self._client.generate_structured(
            system_prompt=LABEL_BINDING_SYSTEM_PROMPT,
            user_prompt=build_chunk_user_prompt(
                mark_scheme,
                page_count=len(sent),
                first_page=first,
                total_pages=len(pages),
                overlap=overlap,
                page_map=page_map.text() if page_map is not None else None,
                labels=page_map.labels_on(chunk) if page_map is not None else None,
            ),
            image_parts=[p.png_bytes for p in sent],
            media_resolution=media_resolution,
            response_schema=_StreamOutput,
            prompt_version=CHUNK_VERSION,
            model=model,
            extra_cache_key=f"{extra_cache_key}|chunk{number}",
            task_tag=task_tag,
            cache_mode="bypass",
        )
        local = parse_stream_items(raw.model_dump()["items"], page_count=len(sent))
        skip = 1 if overlap else 0
        items = [
            item.model_copy(update={"page": first + item.page})
            for item in local.items
            if item.page >= skip
        ]
        drops = dict(local.drops)
        overlap_dropped = len(local.items) - len(items)
        if overlap_dropped:
            drops["overlap_page"] = drops.get("overlap_page", 0) + overlap_dropped
        self._log.info(
            "binding_chunked_read",
            role="chunk",
            chunk=number,
            first_page=chunk.start + 1,
            last_page=chunk.stop,
            items=len(items),
            task=task_tag,
        )
        return StreamRead(items=items, drops=drops)

    def read(
        self,
        pages: list[RasterisedPage],
        mark_scheme: MarkScheme,
        *,
        model: str,
        media_resolution: str = "high",
        extra_cache_key: str,
        task_tag: str,
    ) -> StreamRead:
        """The overview (once per script), the chunks in parallel, then the merge."""
        fitted = self._fit(pages)
        page_map = self._page_map(pages, mark_scheme, model=model)
        mapped: PageMap | None = page_map
        if not page_map.covers(len(pages)):
            # A map that skips, repeats or is out of range (or 1-based) cannot narrow
            # anything safely: every chunk gets the full label list and no map.
            self._log.warning(
                "binding_chunked_read", role="overview_invalid", pages=len(pages), task=task_tag
            )
            mapped = None
        chunks = plan_chunks(
            fitted.page_tokens, self._client._settings.gemini.claude_image_token_budget
        )
        self._log.info(
            "binding_chunked_read", role="plan", pages=len(pages), chunks=len(chunks), task=task_tag
        )
        with ThreadPoolExecutor(max_workers=min(len(chunks), _MAX_CHUNK_WORKERS)) as pool:
            futures = [
                pool.submit(
                    contextvars.copy_context().run,
                    self._read_chunk,
                    pages,
                    mark_scheme,
                    mapped,
                    chunk,
                    number,
                    model=model,
                    media_resolution=media_resolution,
                    extra_cache_key=extra_cache_key,
                    task_tag=task_tag,
                )
                for number, chunk in enumerate(chunks, start=1)
            ]
            reads = [future.result() for future in futures]
        merged = merge_chunk_reads(reads)
        self._log.info("binding_chunked_read", role="merge", items=len(merged.items), task=task_tag)
        return merged
