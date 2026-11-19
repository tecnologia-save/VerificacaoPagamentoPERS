"""Formulário inicial: planilha de entrada + limite de linhas.

Mesmo visual das Protocolações (cabeçalho preto com logo e faixa amarela,
seções com régua amarela, campos arredondados) — os widgets foram copiados de
`ui_formulario_inicial.py` da Protocolação Ressarcimento.

NÃO há escolha de certificado: a planilha mistura procuradores, e o
certificado de cada linha vem da coluna B (ver `VerificacaoPagamento/certificados.py`).
"""
from __future__ import annotations

import sys
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox

from VerificacaoPagamento.config import LIMITE_LINHAS_PADRAO, PASTA_CERTIFICADOS

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    PROJECT_DIR = Path(sys._MEIPASS)
else:
    PROJECT_DIR = Path(__file__).parent
LOGO_PATH = str(PROJECT_DIR / "logo_save.png")

BG       = "#FFFFFF"
DARK     = "#111111"
YELLOW   = "#F5C518"
YELLOW_H = "#FFD835"
BORDER   = "#DDDDDD"
MUTED    = "#777777"
FF       = "Segoe UI"
ENTRY_H  = 38
RADIUS   = 10

INNER_W  = 576
PAD      = 28
GAP      = 14
W_BROWSE = 100
W_FILE   = INNER_W - W_BROWSE - GAP
W_LIMITE = 140


@dataclass
class DadosIniciais:
    caminho_planilha: str
    limite_linhas: int | None   # None = todas as linhas pendentes
    limite_empresas: int | None = None  # None = todas as empresas


def rrect(c, x1, y1, x2, y2, r=RADIUS, **kw):
    pts = [
        x1+r, y1,    x2-r, y1,
        x2,   y1,    x2,   y1+r,
        x2,   y2-r,  x2,   y2,
        x2-r, y2,    x1+r, y2,
        x1,   y2,    x1,   y2-r,
        x1,   y1+r,  x1,   y1,
    ]
    return c.create_polygon(pts, smooth=True, **kw)


class RoundedEntry(tk.Canvas):
    def __init__(self, parent, sv, px_w, readonly=False):
        super().__init__(parent, width=px_w, height=ENTRY_H,
                         bg=BG, highlightthickness=0, bd=0)
        self._s = rrect(self, 1, 1, px_w - 2, ENTRY_H - 2,
                        fill=BG, outline=BORDER, width=2)
        self.entry = tk.Entry(
            self, textvariable=sv, relief="flat",
            bg=BG, fg=DARK, font=(FF, 10),
            insertbackground=DARK, bd=0, highlightthickness=0,
            state="readonly" if readonly else "normal", readonlybackground=BG,
        )
        self.create_window(px_w // 2, ENTRY_H // 2, window=self.entry,
                           anchor="center", width=px_w - 22)
        if not readonly:
            self.entry.bind("<FocusIn>",  lambda _: self.itemconfig(self._s, outline=YELLOW, width=2))
            self.entry.bind("<FocusOut>", lambda _: self.itemconfig(self._s, outline=BORDER, width=2))


class RoundedButton(tk.Canvas):
    def __init__(self, parent, text, command, px_w, height=44):
        super().__init__(parent, width=px_w, height=height,
                         bg=BG, highlightthickness=0, bd=0, cursor="hand2")
        self._s = rrect(self, 1, 1, px_w - 2, height - 2, r=12, fill=YELLOW, outline="")
        self.create_text(px_w // 2, height // 2, text=text,
                         fill=DARK, font=(FF, 11, "bold"))
        self.bind("<Button-1>", lambda _: command())
        self.bind("<Enter>", lambda _: self.itemconfig(self._s, fill=YELLOW_H))
        self.bind("<Leave>", lambda _: self.itemconfig(self._s, fill=YELLOW))


def secao(parent, texto):
    f = tk.Frame(parent, bg=BG)
    tk.Label(f, text=texto, bg=BG, fg=DARK,
             font=(FF, 9, "bold")).grid(row=0, column=0, padx=(0, 12))
    line = tk.Canvas(f, bg=BG, height=2, highlightthickness=0)
    line.grid(row=0, column=1, sticky="ew")
    f.columnconfigure(1, weight=1)
    f.bind("<Configure>", lambda e: (line.delete("all"),
           line.create_rectangle(0, 0, e.width, 2, fill=YELLOW, outline="")))
    return f


def campo_label(parent, text):
    return tk.Label(parent, text=text, bg=BG, fg=DARK, font=(FF, 8, "bold"), anchor="w")


def interpretar_limite(texto: str) -> int | None:
    """'' -> None (todas); '5' -> 5. Levanta ValueError se não for inteiro > 0."""
    texto = (texto or "").strip()
    if not texto:
        return None
    valor = int(texto)
    if valor <= 0:
        raise ValueError("limite deve ser maior que zero")
    return valor


def _validar(sv_planilha, sv_limite, sv_empresas, root) -> DadosIniciais | None:
    erros = []
    planilha = sv_planilha.get().strip()
    if not planilha:
        erros.append("Selecione a planilha de entrada (.xlsx).")
    limite = None
    try:
        limite = interpretar_limite(sv_limite.get())
    except ValueError:
        erros.append("Limite de linhas: informe um número inteiro maior que zero, "
                     "ou deixe em branco para processar todas.")
    limite_empresas = None
    try:
        limite_empresas = interpretar_limite(sv_empresas.get())
    except ValueError:
        erros.append("Limite de empresas: informe um número inteiro maior que zero, "
                     "ou deixe em branco para processar todas.")
    if erros:
        messagebox.showerror("Validação", "\n".join(f"• {e}" for e in erros), parent=root)
        return None
    return DadosIniciais(caminho_planilha=planilha, limite_linhas=limite,
                         limite_empresas=limite_empresas)


def coletar_dados_iniciais() -> DadosIniciais | None:
    """Abre o formulário. None se a janela for fechada sem confirmar."""
    root = tk.Tk()
    root.title("Verificação de Pagamento PER/DCOMP")
    root.configure(bg=DARK)
    root.resizable(False, False)

    header = tk.Frame(root, bg=DARK, padx=PAD, pady=18)
    header.pack(fill="x")
    try:
        from PIL import Image, ImageTk
        _img = Image.open(LOGO_PATH).resize((42, 42), Image.LANCZOS)
        _logo = ImageTk.PhotoImage(_img)
        ic = tk.Label(header, image=_logo, bg=DARK)
        ic._logo = _logo
        ic.pack(side="left", padx=(0, 14))
    except Exception:  # noqa: BLE001, S110 — sem logo o header continua válido
        pass
    tf = tk.Frame(header, bg=DARK)
    tf.pack(side="left")
    tk.Label(tf, text="VERIFICAÇÃO DE PAGAMENTO", bg=DARK, fg=YELLOW,
             font=(FF, 16, "bold")).pack(anchor="w")
    tk.Label(tf, text="PER/DCOMP — Declaração de Compensação no e-CAC",
             bg=DARK, fg=MUTED, font=(FF, 9)).pack(anchor="w")

    tk.Frame(root, bg=YELLOW, height=4).pack(fill="x")
    body = tk.Frame(root, bg=BG, padx=PAD, pady=22)
    body.pack(fill="both", expand=True)
    tk.Frame(root, bg=DARK, height=6).pack(fill="x")

    sv_planilha = tk.StringVar()
    sv_limite = tk.StringVar(value=LIMITE_LINHAS_PADRAO)
    sv_empresas = tk.StringVar(value="")

    secao(body, "DADOS DE ENTRADA").pack(fill="x", pady=(0, 12))
    linha_planilha = tk.Frame(body, bg=BG)
    linha_planilha.pack(fill="x", pady=(0, 6))
    campo_label(linha_planilha, "PLANILHA DE PER/DCOMPS (PRIMEIRA ABA)").pack(anchor="w")
    fp = tk.Frame(linha_planilha, bg=BG)
    fp.pack(fill="x", pady=(3, 0))
    RoundedEntry(fp, sv_planilha, W_FILE, readonly=True).pack(side="left", padx=(0, GAP))

    def _procurar():
        try:
            inicial = str(Path.home() / "Downloads")
        except Exception:  # noqa: BLE001
            inicial = None
        caminho = filedialog.askopenfilename(
            title="Selecione a planilha de PER/DCOMPs",
            filetypes=[("Planilha Excel", "*.xlsx *.xlsm"), ("Todos os arquivos", "*.*")],
            initialdir=inicial, parent=root,
        )
        if caminho:
            sv_planilha.set(caminho)

    RoundedButton(fp, "Procurar", _procurar, W_BROWSE, height=ENTRY_H).pack(side="left")

    qtd_pfx = len(list(PASTA_CERTIFICADOS.glob("*.pfx"))) if PASTA_CERTIFICADOS.is_dir() else 0
    tk.Label(body, text=(f"Certificados: {qtd_pfx} .pfx em {PASTA_CERTIFICADOS} — escolhidos "
                         "pela coluna B (Procurador) de cada linha."),
             bg=BG, fg=MUTED if qtd_pfx else "#EF4444", font=(FF, 8), anchor="w",
             wraplength=INNER_W, justify="left").pack(anchor="w", pady=(0, 18))

    secao(body, "OPÇÕES DE PROCESSAMENTO").pack(fill="x", pady=(0, 12))
    linha_limite = tk.Frame(body, bg=BG)
    linha_limite.pack(fill="x", pady=(0, 6))
    for coluna, (rotulo, variavel) in enumerate((("LIMITE DE EMPRESAS", sv_empresas),
                                                ("LIMITE DE LINHAS", sv_limite))):
        celula = tk.Frame(linha_limite, bg=BG)
        celula.grid(row=0, column=coluna, sticky="w", padx=(0, 24))
        campo_label(celula, rotulo).pack(anchor="w")
        RoundedEntry(celula, variavel, W_LIMITE).pack(anchor="w", pady=(3, 0))
    tk.Label(body, text=("Processa só as primeiras N empresas / linhas, na ordem do robô "
                         "(certificado > empresa). Em branco = todas."),
             bg=BG, fg=MUTED, font=(FF, 8), anchor="w").pack(anchor="w", pady=(0, 20))

    tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=(0, 20))

    resultado: list = [None]

    def _iniciar():
        dados = _validar(sv_planilha, sv_limite, sv_empresas, root)
        if dados:
            resultado[0] = dados
            root.destroy()

    RoundedButton(body, "INICIAR", _iniciar, INNER_W, height=44).pack()
    tk.Frame(body, bg=BG, height=10).pack()

    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
    root.after(150, lambda: (root.lift(), root.focus_force()))
    root.mainloop()
    return resultado[0]
