"""Janela de finalizacao — resumo da execucao.

Copiada da Protocolacao PERDCOMP Ressarcimento sem mudancas de comportamento.

Exibida depois do logout no e-CAC e do fechamento do navegador. Segue o mesmo
padrao de design do formulario inicial (header preto com faixa amarela, cartoes
brancos, botoes arredondados) — equivalente ao `_mostrar_resumo_final` da
automacao ExecucaoPrevidenciario.

Cada linha processada vira um item da lista, com o simbolo de sucesso/falha e o
detalhe correspondente (numero do protocolo, "rascunho" ou a mensagem de erro).
"""
import os
import tkinter as tk
from pathlib import Path

BG     = "#FFFFFF"
DARK   = "#111111"
YELLOW = "#F5C518"
YELL_H = "#FFD835"
BORDER = "#DDDDDD"
MUTED  = "#777777"
OK     = "#22C55E"
ERR    = "#EF4444"
FF     = "Segoe UI"

PAD    = 24
WIN_W  = 560
BTN_H  = 40


def _rrect(c, x1, y1, x2, y2, r=10, **kw):
    pts = [
        x1+r, y1,    x2-r, y1,
        x2,   y1,    x2,   y1+r,
        x2,   y2-r,  x2,   y2,
        x2-r, y2,    x1+r, y2,
        x1,   y2,    x1,   y2-r,
        x1,   y1+r,  x1,   y1,
    ]
    return c.create_polygon(pts, smooth=True, **kw)


def _botao(parent, texto, comando, largura, primario=True):
    c = tk.Canvas(parent, width=largura, height=BTN_H,
                  bg=BG, highlightthickness=0, bd=0, cursor="hand2")
    if primario:
        forma = _rrect(c, 1, 1, largura - 1, BTN_H - 1, fill=YELLOW, outline="")
        c.bind("<Enter>", lambda _: c.itemconfig(forma, fill=YELL_H))
        c.bind("<Leave>", lambda _: c.itemconfig(forma, fill=YELLOW))
    else:
        forma = _rrect(c, 1, 1, largura - 1, BTN_H - 1, fill=BG, outline=BORDER, width=2)
        c.bind("<Enter>", lambda _: c.itemconfig(forma, outline=DARK))
        c.bind("<Leave>", lambda _: c.itemconfig(forma, outline=BORDER))
    c.create_text(largura // 2, BTN_H // 2, text=texto, fill=DARK,
                  font=(FF, 10, "bold" if primario else "normal"))
    c.bind("<Button-1>", lambda _: comando())
    return c


def mostrar_resumo(
    empresa: str,
    cnpj: str,
    linhas: list,
    pasta_destino=None,
    motivo_parada: str = "",
    modo_teste: bool = False,
    avisos: list = None,
) -> None:
    """Abre a janela de resumo e bloqueia ate ser fechada.

    `linhas` e uma lista de dicts com as chaves:
        rotulo  -> texto curto da linha (ex.: "Linha 5 — PIS 3/2023")
        ok      -> bool (define o simbolo e a cor)
        detalhe -> texto secundario (protocolo, "rascunho", erro...)

    `motivo_parada`, quando preenchido, indica que o loop foi interrompido
    antes de processar todas as linhas pendentes.

    `avisos` sao mensagens de problemas que NAO interromperam a execucao (ex.:
    a planilha nao pode ser movida para o Drive no fim).
    """
    root = tk.Tk()
    root.title("Execução Finalizada")
    root.configure(bg=BG)
    root.resizable(False, False)
    root.attributes("-topmost", True)

    total = len(linhas)
    concluidas = sum(1 for item in linhas if item.get("ok"))
    falhas = total - concluidas

    # ── Header ────────────────────────────────────────────────────────────────
    hdr = tk.Frame(root, bg=DARK, padx=PAD, pady=16)
    hdr.pack(fill="x")
    tk.Label(hdr, text="EXECUÇÃO FINALIZADA", bg=DARK, fg=YELLOW,
             font=(FF, 14, "bold"), anchor="w").pack(anchor="w")
    tk.Label(hdr, text=f"{empresa} — {cnpj}" if empresa else cnpj,
             bg=DARK, fg=MUTED, font=(FF, 9), anchor="w").pack(anchor="w")
    tk.Frame(root, bg=YELLOW, height=4).pack(fill="x")

    corpo = tk.Frame(root, bg=BG, padx=PAD, pady=16)
    corpo.pack(fill="both", expand=True)

    if modo_teste:
        aviso = tk.Frame(corpo, bg="#FFF8E1", highlightthickness=1,
                         highlightbackground=YELLOW)
        aviso.pack(fill="x", pady=(0, 14))
        tk.Label(aviso, text="MODO TESTE — nada foi salvo ou enviado ao e-CAC.",
                 bg="#FFF8E1", fg="#8A6D00", font=(FF, 9, "bold"),
                 wraplength=WIN_W - PAD * 2 - 20, justify="left").pack(
                     anchor="w", padx=10, pady=8)

    # ── Contadores ────────────────────────────────────────────────────────────
    contadores = tk.Frame(corpo, bg=BG)
    contadores.pack(fill="x", pady=(0, 14))
    for valor, rotulo, cor in (
        (total, "processadas", DARK),
        (concluidas, "concluídas", OK),
        (falhas, "com falha", ERR if falhas else MUTED),
    ):
        celula = tk.Frame(contadores, bg=BG)
        celula.pack(side="left", expand=True, fill="x")
        tk.Label(celula, text=str(valor), bg=BG, fg=cor,
                 font=(FF, 20, "bold")).pack(anchor="w")
        tk.Label(celula, text=rotulo, bg=BG, fg=MUTED, font=(FF, 8)).pack(anchor="w")

    # ── Lista de linhas ───────────────────────────────────────────────────────
    if linhas:
        # A altura da lista e medida DEPOIS de montar os itens, nunca estimada:
        # cada item tem altura variavel (o detalhe pode quebrar em varias linhas
        # por causa do wraplength), entao um "altura fixa x quantidade" corta os
        # ultimos itens silenciosamente. Acima de ALTURA_MAXIMA a lista rola.
        ALTURA_MAXIMA = 380

        wrapper = tk.Frame(corpo, bg=BG)
        wrapper.pack(fill="x")
        canvas = tk.Canvas(wrapper, bg=BG, highlightthickness=0)
        barra = tk.Scrollbar(wrapper, orient="vertical", command=canvas.yview, width=8)
        canvas.pack(side="left", fill="both", expand=True)
        lista = tk.Frame(canvas, bg=BG)
        janela_lista = canvas.create_window((0, 0), window=lista, anchor="nw")

        lista.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(janela_lista, width=e.width))

        for item in linhas:
            tk.Frame(lista, bg=BORDER, height=1).pack(fill="x")
            linha_frame = tk.Frame(lista, bg=BG, pady=7)
            linha_frame.pack(fill="x")
            sucesso = bool(item.get("ok"))
            tk.Label(linha_frame, text="✓" if sucesso else "✗", bg=BG,
                     fg=OK if sucesso else ERR, font=(FF, 11, "bold"),
                     width=2, anchor="w").pack(side="left")
            textos = tk.Frame(linha_frame, bg=BG)
            textos.pack(side="left", fill="x", expand=True, padx=(6, 0))
            tk.Label(textos, text=item.get("rotulo", ""), bg=BG, fg=DARK,
                     font=(FF, 10), anchor="w").pack(anchor="w", fill="x")
            detalhe = item.get("detalhe", "")
            if detalhe:
                tk.Label(textos, text=detalhe, bg=BG, fg=MUTED, font=(FF, 8),
                         anchor="w", wraplength=WIN_W - PAD * 2 - 40,
                         justify="left").pack(anchor="w", fill="x")
        tk.Frame(lista, bg=BORDER, height=1).pack(fill="x")

        # Mede a altura real da lista montada e decide altura do canvas/rolagem.
        lista.update_idletasks()
        altura_real = lista.winfo_reqheight()
        canvas.configure(height=min(altura_real, ALTURA_MAXIMA))
        if altura_real > ALTURA_MAXIMA:
            barra.pack(side="right", fill="y")
            canvas.configure(yscrollcommand=barra.set)

            def _rolar(e):
                canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

            canvas.bind("<Enter>", lambda _: root.bind_all("<MouseWheel>", _rolar))
            canvas.bind("<Leave>", lambda _: root.unbind_all("<MouseWheel>"))
    else:
        tk.Label(corpo, text="Nenhuma linha pendente foi processada.",
                 bg=BG, fg=MUTED, font=(FF, 10)).pack(anchor="w")

    if motivo_parada:
        tk.Label(corpo, text=f"Execução interrompida: {motivo_parada}",
                 bg=BG, fg=ERR, font=(FF, 9), anchor="w",
                 wraplength=WIN_W - PAD * 2, justify="left").pack(anchor="w", pady=(14, 0))

    for aviso in (avisos or []):
        tk.Label(corpo, text=f"⚠ {aviso}", bg=BG, fg="#8A6D00", font=(FF, 9),
                 anchor="w", wraplength=WIN_W - PAD * 2,
                 justify="left").pack(anchor="w", pady=(14, 0))

    # ── Botões ────────────────────────────────────────────────────────────────
    rodape = tk.Frame(root, bg=BG, padx=PAD, pady=16)
    rodape.pack(fill="x")

    if pasta_destino and Path(pasta_destino).exists():
        caminho = str(pasta_destino)
        _botao(rodape, "Abrir Pasta da Empresa",
               lambda: os.startfile(caminho), 210).pack(side="left", padx=(0, 10))

    _botao(rodape, "Fechar", root.destroy, 100, primario=False).pack(side="left")

    root.update_idletasks()
    altura_final = root.winfo_reqheight()
    x = (root.winfo_screenwidth() - WIN_W) // 2
    y = max(0, (root.winfo_screenheight() - altura_final) // 2)
    root.geometry(f"{WIN_W}x{altura_final}+{x}+{y}")
    root.after(150, lambda: (root.lift(), root.focus_force()))
    root.mainloop()
