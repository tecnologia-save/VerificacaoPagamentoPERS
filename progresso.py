"""Janela de progresso da automacao (Tkinter).

Copiada da Protocolacao PERDCOMP Ressarcimento (que a portou da
ExecucaoPrevidenciario): mesmos widgets em Canvas, mesma paleta, mesmo mecanismo
de pausa/parada. Mudam o titulo e as regras de traducao do log, adaptadas para a
Verificacao de Pagamento (varios certificados e empresas por execucao).

A automacao roda numa thread separada e se comunica com esta janela por uma fila
thread-safe (a GUI so e tocada na thread principal, via polling com `after`).

Uso (na thread principal):
    jan = JanelaProgresso()
    run._registrar_log_sink(jan.log)                 # espelha os print() no log
    run._registrar_pausa_gate(jan.aguardar_se_pausado)
    threading.Thread(target=_rodar, daemon=True).start()
    jan.mainloop()

Na thread da automacao:
    progresso.fase("Login eCAC", 0, 10)     # etapa e faixa de % [ini, fim]
    progresso.finalizar()                   # ao terminar (a janela fecha sozinha)

A janela NAO mostra resumo nem espera o usuario fechar: ao receber `finalizar()`
ela exibe 100%/"Concluido" por um instante e encerra o mainloop, devolvendo o
controle a thread principal, que abre a janela de resumo (`ui_resumo_final`).

Todos os elementos visuais (botoes, barra, painel de log) sao desenhados em
Canvas para terem cantos arredondados — o Tkinter nao suporta isso nativamente.
"""

import queue
import re
import threading
import tkinter as tk
import tkinter.font as tkfont

# Paleta (mesma do formulario/resumo)
FF     = "Segoe UI"
BG     = "#FFFFFF"
DARK   = "#111111"
YEL    = "#F5C518"
YELH   = "#FFD835"
BORD   = "#DDDDDD"
OK     = "#22c55e"
ERR    = "#EF4444"
MUT    = "#777777"
TRACK  = "#ECECEC"   # trilho da barra de progresso
LOG_BG = "#FAFAFA"
LOG_FG = "#333333"

# Marcador de subprogresso emitido pelo loop de linhas ("LINHA 3/10").
_MARCADORES = re.compile(r"LINHA\D*?(\d+)\s*/\s*(\d+)")


class AutomacaoInterrompida(BaseException):
    """Sinaliza parada solicitada pelo usuario.

    Herda de BaseException (e nao de Exception) de proposito: os fluxos da
    automacao usam `except Exception` em varios pontos (inclusive por linha da
    planilha), e a parada precisa atravessar esses blocos ate o topo de
    `iniciar_automacao`, sem ser confundida com uma falha de preenchimento.
    """


# ── Traducao do log tecnico para mensagens amigaveis ─────────────────────────
# O log tecnico completo continua indo para o console e para o arquivo de log;
# a janela mostra apenas o que e util para o usuario acompanhar.
def _r(p):
    return re.compile(p, re.IGNORECASE)


_REGRAS = [
    (_r(r"=+\s*ETAPA\s+(\d+)/(\d+):\s*(.+?)\s*=+"),
     lambda m: f"▶  Etapa {m.group(1)} de {m.group(2)}: {m.group(3)}"),

    # Planilha e lote
    (_r(r"Linhas pendentes na planilha\s*:\s*(\d+)"),
     lambda m: f"{m.group(1)} linha(s) pendente(s) na planilha."),
    (_r(r"Linhas no lote\s*:\s*(\d+)"),
     lambda m: f"{m.group(1)} linha(s) serão processadas nesta execução."),
    (_r(r"^CERTIFICADO:\s*(.+?)\s+—"),
     lambda m: f"Certificado: {m.group(1)}"),
    (_r(r"^--- Empresa\s+(.+?)\s+—\s+CNPJ\s+(\d+)"),
     lambda m: f"Empresa: {m.group(1)} ({m.group(2)})"),

    # Certificado / login
    (_r(r"Lancando Chrome"),             lambda m: "Abrindo o navegador..."),
    (_r(r"LOGIN CONCLUIDO"),             lambda m: "✓ Login realizado com sucesso."),
    (_r(r"Acesso bloqueado"),
     lambda m: "Acesso temporariamente bloqueado pelo eCAC — aguardando..."),
    (_r(r"Numero maximo de dispositivos|Limite de dispositivos"),
     lambda m: "⚠ Limite de dispositivos atingido no eCAC."),
    (_r(r"\[perfil\] Alterando perfil"),  lambda m: "Trocando para o perfil da próxima empresa..."),
    (_r(r"Perfil alterado"),              lambda m: "✓ Perfil da empresa ativo."),

    # Captcha
    (_r(r"Captcha resolvido"),           lambda m: "✓ Captcha resolvido."),
    (_r(r"\[captcha"),                   lambda m: "Resolvendo captcha de segurança..."),

    # Navegacao
    (_r(r"FASE: Navegacao para o modulo PERDCOMP"), lambda m: "Abrindo o módulo PERDCOMP..."),
    (_r(r"PERDCOMP-WEB nao carregou na tentativa (\d+)/(\d+)"),
     lambda m: f"PERDCOMP-WEB lento — recarregando (tentativa {m.group(1)} de {m.group(2)})..."),

    # Loop de linhas
    (_r(r"^\s*LINHA (\d+)/(\d+)"),
     lambda m: f"Processando linha {m.group(1)} de {m.group(2)}..."),
    (_r(r"aguardando liberar a tela"),   lambda m: "Aguardando a tela do PERDCOMP liberar..."),
    (_r(r"'Declaração de Compensação' selecionada|'Declaracao de Compensacao' selecionada"),
     lambda m: "✓ Declaração de Compensação selecionada."),
    (_r(r"'Novo Documento' clicado"),    lambda m: "Abrindo um novo documento..."),
    (_r(r"FASE: Documento Retificador"), lambda m: "Documento Retificador: Não..."),
    (_r(r"FASE: Tipo de Credito -> (\w+)"), lambda m: f"Tipo de crédito: {m.group(1)}..."),
    (_r(r"FASE: Detalhamento do Credito"),
     lambda m: "Informando o PER/DCOMP anterior que detalha o crédito..."),
    (_r(r"PER/DCOMP anterior preenchido"), lambda m: "✓ Número do PER/DCOMP anterior preenchido."),
    (_r(r"'Prosseguir' clicado"),          lambda m: "Prosseguindo..."),
    (_r(r"FASE: Termo de inconstitucionalidade"), lambda m: "Termo de inconstitucionalidade: Não..."),
    (_r(r"FASE: Declaracao de nao litigio"), lambda m: "Declarando que não há litígio..."),
    (_r(r"FASE: Credito Original"),        lambda m: "Informando o crédito original..."),
    (_r(r"FASE: Informar Debito"),         lambda m: "Informando o débito..."),
    (_r(r"Debito informado"),              lambda m: "✓ Débito informado."),
    (_r(r"FASE: CPF do responsavel"),      lambda m: "Informando o responsável..."),
    (_r(r"Documento apto para envio:\s*True"), lambda m: "✓ Documento apto para envio."),
    (_r(r"Documento apto para envio:\s*False"), lambda m: "⚠ Documento NÃO está apto para envio."),
    (_r(r"FASE: Enviar"),                  lambda m: "Enviando a Declaração de Compensação..."),
    (_r(r"Declaracao enviada\. Numero do documento:\s*(\S+)"),
     lambda m: f"✓ Declaração enviada: {m.group(1)} (pagamento NÃO realizado)."),
    (_r(r"Desfecho do envio: Pagamento realizado"),
     lambda m: "✓ A Receita informou: pagamento JÁ REALIZADO."),
    (_r(r"ENVIO SEM CONFIRMACAO"),         lambda m: "⚠ Envio sem confirmação — linha em quarentena."),
    (_r(r"Planilha gravada"),              lambda m: "✓ Resultados gravados na planilha."),
    (_r(r"MENSAGENS IMPORTANTES"),
     lambda m: "⚠ Empresa com mensagens importantes — ao final, novo login."),
    (_r(r"Caixa Postal aberta"),           lambda m: "Caixa Postal aberta para sair com segurança."),
    (_r(r"Perfil ativo no e-CAC e"),       lambda m: "⚠ Perfil ativo diferente do esperado — refazendo o login."),

    # Encerramento
    (_r(r"'Sair com Seguranca' clicado"), lambda m: "✓ Sessão do eCAC encerrada."),
    (_r(r"Navegador fechado"),            lambda m: "✓ Navegador fechado."),
]

_RX_PROBLEMA = re.compile(r"\bERRO\b|\bErro\b|\[AVISO\]|Aviso:|Falha|PARADA", re.IGNORECASE)
_RX_PREFIXO  = re.compile(r"^\s*\[[^\]]+\]\s*")


def _amigavel(linha: str):
    """Converte uma linha do log tecnico em mensagem amigavel (ou None p/ ocultar)."""
    s = linha.strip()
    if not s:
        return None
    for rx, fn in _REGRAS:
        m = rx.search(s)
        if m:
            return fn(m)
    # Erros e avisos sempre aparecem, sem o prefixo tecnico.
    if _RX_PROBLEMA.search(s):
        return "⚠  " + _RX_PREFIXO.sub("", s)[:160]
    return None


def _rrect(c, x1, y1, x2, y2, r=10, **kw):
    """Retangulo com os 4 cantos arredondados (poligono suavizado)."""
    pts = [
        x1 + r, y1,    x2 - r, y1,
        x2,     y1,    x2,     y1 + r,
        x2,     y2 - r, x2,    y2,
        x2 - r, y2,    x1 + r, y2,
        x1,     y2,    x1,     y2 - r,
        x1,     y1 + r, x1,    y1,
    ]
    return c.create_polygon(pts, smooth=True, **kw)


class _Botao(tk.Canvas):
    """Botao arredondado desenhado em Canvas, com icone opcional (pause/play/stop)."""

    def __init__(self, master, texto, largura, altura=42, fill=YEL, fg=DARK,
                 hover=YELH, outline="", comando=None, icone=None, bg=BG):
        super().__init__(master, width=largura, height=altura, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._larg, self._alt = largura, altura
        self._fill, self._hover, self._outline, self._fg = fill, hover, outline, fg
        self._comando = comando
        self._habilitado = True
        self._fonte = tkfont.Font(family=FF, size=10, weight="bold")
        self.redesenhar(texto, icone)
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)

    # ── desenho ───────────────────────────────────────────────────────────────
    def redesenhar(self, texto=None, icone=None, fill=None, fg=None, outline=None):
        if texto is not None:
            self._texto = texto
        if icone is not None or not hasattr(self, "_icone"):
            self._icone = icone
        if fill is not None:
            self._fill = fill
        if fg is not None:
            self._fg = fg
        if outline is not None:
            self._outline = outline

        self.delete("all")
        r = min(12, self._alt // 2)
        self._shape = _rrect(self, 2, 2, self._larg - 2, self._alt - 2, r=r,
                             fill=self._fill, outline=self._outline or "",
                             width=1 if self._outline else 0)

        cy = self._alt // 2
        larg_txt = self._fonte.measure(self._texto)
        if self._icone:
            gap, larg_ico = 9, 12
            total = larg_ico + gap + larg_txt
            x_ico = (self._larg - total) // 2 + larg_ico // 2
            self._desenhar_icone(x_ico, cy, self._icone, self._fg)
            self.create_text(x_ico + larg_ico // 2 + gap, cy, text=self._texto,
                             fill=self._fg, font=self._fonte, anchor="w")
        else:
            self.create_text(self._larg // 2, cy, text=self._texto,
                             fill=self._fg, font=self._fonte)

    def _desenhar_icone(self, x, cy, tipo, cor):
        if tipo == "pause":
            # Dois tracinhos verticais arredondados (⏸ desenhado, nao fonte).
            for dx in (-5, 1):
                _rrect(self, x + dx, cy - 7, x + dx + 4, cy + 7, r=2,
                       fill=cor, outline="")
        elif tipo == "play":
            self.create_polygon(x - 4, cy - 7, x - 4, cy + 7, x + 7, cy,
                                fill=cor, outline="", smooth=False)
        elif tipo == "stop":
            _rrect(self, x - 6, cy - 6, x + 6, cy + 6, r=2, fill=cor, outline="")

    # ── estado / eventos ──────────────────────────────────────────────────────
    def habilitar(self, ok: bool):
        self._habilitado = ok
        self.configure(cursor="hand2" if ok else "arrow")
        self.itemconfig(self._shape, fill=self._fill if ok else TRACK)

    def _click(self, _):
        if self._habilitado and self._comando:
            self._comando()

    def _enter(self, _):
        if self._habilitado:
            self.itemconfig(self._shape, fill=self._hover)

    def _leave(self, _):
        if self._habilitado:
            self.itemconfig(self._shape, fill=self._fill)


class _Barra(tk.Canvas):
    """Barra de progresso arredondada (trilho + preenchimento em pill)."""

    def __init__(self, master, altura=20):
        super().__init__(master, height=altura, bg=BG, highlightthickness=0, bd=0)
        self._h = altura
        self._pct = 0.0
        self.bind("<Configure>", lambda _e: self._desenhar())

    def set(self, pct: float):
        self._pct = max(0.0, min(100.0, pct))
        self._desenhar()

    def _desenhar(self):
        self.delete("all")
        w = self.winfo_width()
        if w <= 1:
            return
        h = self._h
        r = h // 2

        # Trilho
        _rrect(self, 1, 1, w - 1, h - 1, r=r, fill=TRACK, outline="")

        # Preenchimento (minimo de 2r para o pill nao deformar)
        if self._pct > 0.4:
            larg = (w - 2) * (self._pct / 100.0)
            fim = min(max(1 + larg, 2 * r + 1), w - 1)
            _rrect(self, 1, 1, fim, h - 1, r=r, fill=YEL, outline="")
            # Brilho sutil na metade de cima, para dar acabamento
            if fim - 1 > 2 * r:
                _rrect(self, 1 + 3, 1 + 3, fim - 3, h / 2, r=max(2, r // 2),
                       fill=YELH, outline="")


class _PainelLog(tk.Canvas):
    """Area de log com borda arredondada (Text embutido via create_window)."""

    def __init__(self, master):
        super().__init__(master, bg=BG, highlightthickness=0, bd=0)
        self.inner = tk.Frame(self, bg=LOG_BG)
        self.txt = tk.Text(self.inner, bg=LOG_BG, fg=LOG_FG, bd=0, relief="flat",
                           font=(FF, 9), wrap="word", state="disabled",
                           highlightthickness=0, height=8, spacing1=2, spacing3=2)
        self.scroll = tk.Scrollbar(self.inner, command=self.txt.yview,
                                   width=10, bd=0, relief="flat",
                                   troughcolor=LOG_BG, highlightthickness=0)
        self.txt.configure(yscrollcommand=self.scroll.set)
        self.scroll.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)
        self._win = self.create_window(0, 0, anchor="nw", window=self.inner)
        self.bind("<Configure>", self._on_conf)

    def _on_conf(self, e):
        self.delete("borda")
        _rrect(self, 1, 1, e.width - 1, e.height - 1, r=12,
               fill=LOG_BG, outline=BORD, width=1, tags="borda")
        self.tag_lower("borda")
        pad = 9
        self.coords(self._win, pad, pad)
        self.itemconfig(self._win, width=max(1, e.width - 2 * pad),
                        height=max(1, e.height - 2 * pad))


class JanelaProgresso:
    def __init__(self, subtitulo: str = "Preparando..."):
        self.fila = queue.Queue()
        self._fase_ini = 0.0
        self._fase_fim = 100.0
        self._pct = 0.0
        self._concluido = False

        # Pausa: o evento fica "setado" enquanto rodando. A thread da automacao
        # chama aguardar_se_pausado() nos checkpoints e bloqueia enquanto pausado.
        self._evento_continuar = threading.Event()
        self._evento_continuar.set()
        self._pausado = False
        self._parar = False          # parada solicitada pelo usuario
        self._ultima_msg = None      # evita repetir a mesma mensagem amigavel
        self._encerrando = False     # trava o polling durante o fechamento
        self._after_poll = None      # id do `after` do polling (para cancelar)

        self.root = tk.Tk()
        self.root.title("Verificação de Pagamento PER/DCOMP — Progresso")
        self.root.configure(bg=BG)
        self.root.minsize(600, 500)
        self.root.protocol("WM_DELETE_WINDOW", self._on_fechar)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(self.root, bg=DARK, padx=22, pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="EXECUÇÃO EM ANDAMENTO", bg=DARK, fg=YEL,
                 font=(FF, 14, "bold"), anchor="w").pack(anchor="w")
        self.lbl_sub = tk.Label(hdr, text=subtitulo, bg=DARK, fg=MUT,
                                font=(FF, 9), anchor="w")
        self.lbl_sub.pack(anchor="w")

        # Faixa amarela arredondada (acento)
        faixa = tk.Canvas(self.root, height=6, bg=BG, highlightthickness=0, bd=0)
        faixa.pack(fill="x", padx=22, pady=(10, 0))
        faixa.bind("<Configure>", lambda e: (
            faixa.delete("all"),
            _rrect(faixa, 0, 0, e.width, 6, r=3, fill=YEL, outline=""),
        ))

        # ── Etapa atual + porcentagem ─────────────────────────────────────────
        top = tk.Frame(self.root, bg=BG, padx=22)
        top.pack(fill="x", pady=(14, 8))
        self.lbl_fase = tk.Label(top, text="Iniciando...", bg=BG, fg=DARK,
                                 font=(FF, 13, "bold"), anchor="w")
        self.lbl_fase.pack(side="left")
        self.lbl_pct = tk.Label(top, text="0%", bg=BG, fg=DARK,
                                font=(FF, 13, "bold"), anchor="e")
        self.lbl_pct.pack(side="right")

        # ── Barra de progresso ────────────────────────────────────────────────
        self.barra = _Barra(self.root, altura=20)
        self.barra.pack(fill="x", padx=22)

        # ── Linha de detalhe (ultima acao) ────────────────────────────────────
        self.lbl_detalhe = tk.Label(self.root, text="", bg=BG, fg=MUT,
                                    font=(FF, 9), anchor="w", padx=22)
        self.lbl_detalhe.pack(fill="x", pady=(8, 8))

        # ── Rodape (botoes) ───────────────────────────────────────────────────
        # Empacotado ANTES do log e fixado em "bottom": o log usa expand=True e,
        # se viesse primeiro, empurraria os botoes para fora da janela.
        self.rodape = tk.Frame(self.root, bg=BG, padx=22)
        self.rodape.pack(side="bottom", fill="x", pady=(0, 16))

        self.btn_pausar = _Botao(self.rodape, "Pausar", largura=132, altura=42,
                                 fill=BG, hover="#F3F3F3", fg=DARK, outline=BORD,
                                 icone="pause", comando=self._toggle_pausa)
        self.btn_pausar.pack(side="left")

        self.btn_parar = _Botao(self.rodape, "Parar", largura=118, altura=42,
                                fill=ERR, hover="#DC2626", fg="#FFFFFF",
                                icone="stop", comando=self._confirmar_parar)
        self.btn_parar.pack(side="right")

        # ── Log detalhado (borda arredondada) ─────────────────────────────────
        self.painel = _PainelLog(self.root)
        self.painel.pack(side="top", fill="both", expand=True, padx=22, pady=(0, 14))
        self.txt = self.painel.txt

        self._centralizar(640, 590)
        self._after_poll = self.root.after(80, self._poll)

    # ── API chamada pela thread da automacao (thread-safe) ────────────────────
    def fase(self, nome: str, ini: float, fim: float):
        self.fila.put(("fase", nome, float(ini), float(fim)))

    def log(self, texto: str):
        self.fila.put(("log", texto))

    def finalizar(self):
        """Sinaliza o fim da automacao — a janela se fecha sozinha em seguida."""
        self.fila.put(("fim",))

    def aguardar_se_pausado(self):
        """Checkpoint chamado pela thread da automacao.

        Bloqueia enquanto pausado e levanta AutomacaoInterrompida quando o
        usuario confirma a parada. Pausa e parada passam a valer no PROXIMO
        checkpoint — nao interrompem uma acao ja em andamento no navegador.
        """
        self._evento_continuar.wait()
        if self._parar:
            raise AutomacaoInterrompida()

    def pausar_por_pendencia(self, mensagem: str):
        """Pausa a automacao POR EXIGENCIA do fluxo (nao por clique do usuario)
        e exibe `mensagem` — ex.: "exclua rascunhos e clique em Retomar".

        Chamada pela thread da automacao. O estado de pausa (`_pausado` +
        `_evento_continuar`) e alterado JA AQUI, de forma sincrona e thread-safe,
        para nao haver corrida: se so enfileirassemos a mudanca para a thread de
        UI, a automacao poderia chamar `aguardar_se_pausado()` antes de o evento
        ser limpo e nao pausaria. A parte visual (botao/rotulos/messagebox) vai
        pela fila, pois so pode ser tocada na thread principal.

        Depois desta chamada, a automacao deve chamar `aguardar_se_pausado()`
        para efetivamente bloquear ate o usuario clicar em Retomar (ou Parar).
        """
        if self._concluido:
            return
        self._pausado = True
        self._evento_continuar.clear()
        self.fila.put(("pausa_aviso", mensagem))

    @property
    def parada_solicitada(self) -> bool:
        return self._parar

    # ── Parar (thread principal) ──────────────────────────────────────────────
    def _confirmar_parar(self):
        if self._concluido or self._parar:
            return
        from tkinter import messagebox
        if not messagebox.askyesno(
            "Parar automação",
            "Deseja realmente PARAR a automação?\n\n"
            "O documento em preenchimento é descartado e as linhas restantes "
            "não serão processadas.\n\n"
            "A automação ainda vai sair do e-CAC com segurança antes de encerrar.",
            icon="warning", default="no", parent=self.root,
        ):
            return

        self._parar = True
        self._evento_continuar.set()   # destrava caso esteja pausado
        self.btn_parar.habilitar(False)
        self.btn_pausar.habilitar(False)
        self.lbl_sub.config(text="PARANDO — aguardando a etapa atual terminar...")
        self.lbl_detalhe.config(text="Parada solicitada. Encerrando com segurança...")
        self._log_linha("\n⛔  Parada solicitada pelo usuário — encerrando...")

    # ── Pausa (thread principal) ──────────────────────────────────────────────
    def _toggle_pausa(self):
        if self._concluido:
            return
        self._pausado = not self._pausado
        if self._pausado:
            self._evento_continuar.clear()          # bloqueia a automacao
            self.btn_pausar.redesenhar("Retomar", icone="play", fill=YEL,
                                       outline="", fg=DARK)
            self.btn_pausar._hover = YELH
            self.lbl_sub.config(text="PAUSADO — clique em Retomar para continuar")
            self.lbl_detalhe.config(
                text="Pausado. A automação para no próximo passo e retoma de onde parou.")
        else:
            self.btn_pausar.redesenhar("Pausar", icone="pause", fill=BG,
                                       outline=BORD, fg=DARK)
            self.btn_pausar._hover = "#F3F3F3"
            self.lbl_sub.config(text=f"Executando: {self.lbl_fase.cget('text')}")
            self._evento_continuar.set()            # libera a automacao

    # ── Interno (thread principal) ────────────────────────────────────────────
    def _poll(self):
        if self._encerrando:
            return          # nao reagenda: a janela esta sendo destruida
        try:
            while True:
                self._processar(self.fila.get_nowait())
        except queue.Empty:
            pass
        self._after_poll = self.root.after(80, self._poll)

    def _processar(self, item):
        tipo = item[0]
        if tipo == "fase":
            _, nome, ini, fim = item
            self._fase_ini, self._fase_fim = ini, fim
            self.lbl_fase.config(text=nome)
            if not self._pausado:
                self.lbl_sub.config(text=f"Executando: {nome}")
            self._set_pct(ini)
        elif tipo == "log":
            self._append_stdout(item[1])
        elif tipo == "pausa_aviso":
            self._mostrar_pausa_aviso(item[1])
        elif tipo == "fim":
            self._on_fim()

    def _mostrar_pausa_aviso(self, mensagem: str):
        """(thread principal) Reflete na UI a pausa exigida pelo fluxo: coloca o
        botao no estado "Retomar", destaca a mensagem e abre um messagebox para
        garantir que o usuario veja. O estado de pausa em si ja foi setado por
        `pausar_por_pendencia` na thread da automacao."""
        if self._concluido:
            return
        self.btn_pausar.redesenhar("Retomar", icone="play", fill=YEL,
                                   outline="", fg=DARK)
        self.btn_pausar._hover = YELH
        self.lbl_sub.config(text="PAUSADO — ação necessária")
        self.lbl_detalhe.config(text=mensagem[:120])
        self._log_linha("\n⏸  " + mensagem)
        # Messagebox modal: bloqueia o event loop ate o OK, mas a automacao ja
        # esta pausada, entao nada se perde. Garante que o aviso nao passe
        # despercebido. Depois do OK, o usuario age e clica em Retomar.
        from tkinter import messagebox
        messagebox.showwarning("Ação necessária", mensagem, parent=self.root)

    def _append_stdout(self, data: str):
        """Recebe o stdout tecnico e mostra apenas mensagens amigaveis na janela.

        O log tecnico completo continua indo para o console e para o arquivo de
        log — aqui so entra o que ajuda o usuario a acompanhar a operacao atual.
        """
        for linha in data.splitlines():
            if not linha.strip():
                continue

            # Subprogresso usa a linha tecnica (ex.: "LINHA 3/10").
            m = _MARCADORES.search(linha)
            if m:
                try:
                    i, total = int(m.group(1)), int(m.group(2))
                    if total > 0:
                        frac = max(0.0, min(1.0, i / total))
                        alvo = self._fase_ini + frac * (self._fase_fim - self._fase_ini)
                        if alvo >= self._pct:
                            self._set_pct(alvo)
                except Exception:
                    pass

            msg = _amigavel(linha)
            if msg and msg != self._ultima_msg:
                self._ultima_msg = msg
                self.lbl_detalhe.config(text=msg[:120])
                self._log_linha(msg)

    def _log_linha(self, texto: str):
        self._inserir(texto + "\n")

    def _inserir(self, texto: str):
        self.txt.configure(state="normal")
        self.txt.insert("end", texto)
        # Limita o buffer para nao crescer indefinidamente.
        if int(self.txt.index("end-1c").split(".")[0]) > 2000:
            self.txt.delete("1.0", "500.0")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _set_pct(self, pct: float):
        self._pct = max(0.0, min(100.0, pct))
        self.barra.set(self._pct)
        self.lbl_pct.config(text=f"{int(round(self._pct))}%")

    def _on_fim(self):
        self._concluido = True

        # Libera qualquer pausa pendente e desabilita os botoes de controle.
        self._pausado = False
        self._evento_continuar.set()
        for b in ("btn_pausar", "btn_parar"):
            try:
                getattr(self, b).habilitar(False)
            except Exception:
                pass

        if self._parar:
            self.lbl_fase.config(text="Interrompida")
            self.lbl_sub.config(text="Automação parada pelo usuário")
        else:
            self._set_pct(100)
            self.lbl_fase.config(text="Concluído")
            self.lbl_sub.config(text="Automação finalizada")
        self.lbl_detalhe.config(text="Abrindo o resumo da execução...")

        # Fecha sozinha: o detalhamento fica por conta da janela de resumo, que a
        # thread principal abre assim que este mainloop termina. A pequena pausa
        # existe so para o 100%/"Concluído" nao piscar — sem ela a janela some no
        # mesmo instante em que a barra chega ao fim.
        self.root.after(900, self._encerrar)

    def _encerrar(self):
        # Cancela o polling ANTES de sair do mainloop: o `after` pendente
        # dispararia depois do destroy() e o Tcl reclamaria no console
        # ("invalid command name ..._poll").
        self._encerrando = True
        if self._after_poll is not None:
            try:
                self.root.after_cancel(self._after_poll)
            except Exception:
                pass
            self._after_poll = None
        try:
            self.root.quit()
        except Exception:
            pass

    def _on_fechar(self):
        # Ignora o X: enquanto roda, para nao fechar sem querer no meio; depois,
        # porque a janela ja esta se fechando sozinha.
        if not self._concluido:
            self.lbl_detalhe.config(text="Automação em andamento — use Parar para interromper.")

    def _centralizar(self, w, h):
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def mainloop(self):
        self.root.mainloop()
        try:
            self.root.destroy()
        except Exception:
            pass
