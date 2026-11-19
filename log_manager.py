"""Gerenciador de log. Salva erros em logs/DD-MM-YYYY_verificacao_pagamento.txt.

Copiado das Protocolações (mesmo comportamento).

No .exe (frozen) os logs vao para a pasta DO EXECUTAVEL (persistente e gravavel),
nunca para dentro de _internal — que em onedir e apagado a cada atualizacao e pode
ser somente-leitura. E toda a escrita e best-effort: `registrar_erro` roda de
dentro de blocos `except` no run.py, entao uma falha de log JAMAIS pode propagar
e derrubar/mascarar o erro original.
"""
import sys
from datetime import datetime
from pathlib import Path


def _base_dir() -> Path:
    """Pasta-base dos logs: ao lado do .exe quando congelado; senao, ao lado do
    fonte. Em onedir, __file__ fica dentro de _internal (efemero) — por isso o
    caso frozen usa sys.executable."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def registrar_erro(mensagem: str, log_dir: Path = None) -> None:
    agora = datetime.now()
    entrada = f"[{agora.strftime('%d/%m/%Y %H:%M:%S')}] ERRO: {mensagem}\n"
    print(f"[LOG] {entrada.strip()}")
    try:
        if log_dir is None:
            log_dir = _base_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        nome_arquivo = agora.strftime("%d-%m-%Y") + "_verificacao_pagamento.txt"
        with open(log_dir / nome_arquivo, "a", encoding="utf-8") as f:
            f.write(entrada)
    except Exception:
        # Nunca deixar uma falha de log (pasta read-only, disco cheio, etc.)
        # derrubar o fluxo — o erro real ja foi impresso acima.
        pass
