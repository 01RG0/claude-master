/**
 * 60 FPS HTML5 Canvas time scrubber bar.
 */

import type { Scrubber, ScrubberSnapshot } from "./scrubber.js";

export class CanvasScrubber {
  private readonly canvas: HTMLCanvasElement;
  private readonly ctx: CanvasRenderingContext2D;
  private readonly scrubber: Scrubber;
  private unsub: (() => void) | null = null;
  private dragging = false;
  private snap: ScrubberSnapshot;

  constructor(canvas: HTMLCanvasElement, scrubber: Scrubber) {
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("2d context unavailable");
    this.canvas = canvas;
    this.ctx = ctx;
    this.scrubber = scrubber;
    this.snap = scrubber.snapshot();
    this.bind();
    this.draw();
  }

  private bind(): void {
    this.unsub = this.scrubber.subscribe((s) => {
      this.snap = s;
      this.draw();
    });

    this.canvas.addEventListener("pointerdown", this.onDown);
    this.canvas.addEventListener("pointermove", this.onMove);
    this.canvas.addEventListener("pointerup", this.onUp);
    this.canvas.addEventListener("pointerleave", this.onUp);
  }

  private tsFromX(x: number): number {
    const { oldestTs, newestTs } = this.snap;
    if (oldestTs == null || newestTs == null || newestTs <= oldestTs) {
      return oldestTs ?? 0;
    }
    const w = this.canvas.width || 1;
    const t = Math.min(1, Math.max(0, x / w));
    return oldestTs + t * (newestTs - oldestTs);
  }

  private onDown = (e: PointerEvent): void => {
    this.dragging = true;
    this.scrubber.beginScrub();
    this.scrubber.seek(this.tsFromX(e.offsetX));
    this.canvas.setPointerCapture(e.pointerId);
  };

  private onMove = (e: PointerEvent): void => {
    if (!this.dragging) return;
    this.scrubber.seek(this.tsFromX(e.offsetX));
  };

  private onUp = (): void => {
    if (!this.dragging) return;
    this.dragging = false;
    this.scrubber.endScrub(true);
  };

  draw(): void {
    const { canvas, ctx, snap } = this;
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    ctx.fillStyle = "#1a1f2e";
    ctx.fillRect(0, 0, w, h);

    const { oldestTs, newestTs, cursorTs, mode, bufferSize } = snap;
    if (oldestTs != null && newestTs != null && newestTs > oldestTs) {
      const t = (cursorTs - oldestTs) / (newestTs - oldestTs);
      const x = t * w;

      ctx.fillStyle = "#2d4a3e";
      ctx.fillRect(0, 0, x, h);

      ctx.strokeStyle = "#5eead4";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }

    ctx.fillStyle = "#94a3b8";
    ctx.font = "11px ui-monospace, monospace";
    ctx.fillText(`${mode} · ${bufferSize} events`, 8, h - 8);
  }

  dispose(): void {
    this.unsub?.();
    this.canvas.removeEventListener("pointerdown", this.onDown);
    this.canvas.removeEventListener("pointermove", this.onMove);
    this.canvas.removeEventListener("pointerup", this.onUp);
    this.canvas.removeEventListener("pointerleave", this.onUp);
  }
}
