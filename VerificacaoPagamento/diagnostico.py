"""Retrato da tela (HTML de cada frame + screenshot) quando algo sai do esperado.

As telas da Declaração de Compensação ainda não têm HTML capturado. Em vez de
depender de alguém rodar `debug_capturar_tela.py` no momento certo, a própria
automação salva o retrato da tela nos pontos de dúvida/falha — é com esses
arquivos que os seletores das próximas etapas são confirmados.

Best-effort: nunca levanta (roda dentro de tratamento de erro).
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


def capturar_tela(page, rotulo: str, pasta: Path) -> Path | None:
    """Salva <pasta>/<rotulo>_<timestamp>_{principal,frameN}.html e .png.

    Devolve o caminho-base (sem extensão), ou None se nada pôde ser salvo."""
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        rotulo = re.sub(r"[^\w.-]+", "_", rotulo).strip("_") or "tela"
        base = pasta / f"{rotulo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    except Exception:  # noqa: BLE001
        return None

    salvou = False
    try:
        frames = list(page.frames)
    except Exception:  # noqa: BLE001
        frames = []
    for i, frame in enumerate(frames):
        nome = "principal" if frame == page.main_frame else f"frame{i}"
        try:
            Path(f"{base}_{nome}.html").write_text(frame.content(), encoding="utf-8")
            salvou = True
        except Exception:  # noqa: BLE001, S112 — frame que sumiu no meio: segue com os outros
            continue
    try:
        page.screenshot(path=f"{base}.png", full_page=True, timeout=15_000)
        salvou = True
    except Exception:  # noqa: BLE001, S110
        pass
    if salvou:
        print(f"  -> Tela salva para conferencia: {base}.*")
        return base
    return None
