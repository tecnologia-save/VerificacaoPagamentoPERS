"""Gravação dos resultados: diário CSV imediato + coluna AA da planilha em lote.

POR QUE DOIS LUGARES. A planilha real tem 4 abas e uma delas ("inss") com
~1 milhão de linhas: abrir + salvar em modo de escrita custa ~24 s (medido em
18/11/2026). Salvar a cada linha dobraria o tempo da execução. Então:

  - DIÁRIO (`resultados/<planilha>_verificacao.csv`): cada resultado é
    acrescentado e forçado para o disco NA HORA. É a fonte da verdade;
  - PLANILHA: a coluna AA é gravada A CADA RESULTADO (`salvar_a_cada=1`,
    pedido do usuário em 18/11/2026: a planilha sempre em dia, mesmo que a
    execução seja parada no meio). Custa ~24 s por linha nesta planilha.

Na execução seguinte, o diário é RECONCILIADO com a planilha: linha que tem
resultado no diário e AA vazia (a gravação não chegou a acontecer — Excel
aberto, robô caído) recebe o resultado e não volta ao lote.

TRAVA CONTRA DECLARAÇÃO DUPLICADA. Antes de clicar "Enviar", `marcar_envio`
registra a tentativa no diário. Se o robô morrer entre o clique e o desfecho,
a reconciliação transforma essa tentativa em "Verificar no e-CAC" — a linha
NUNCA é reenviada sem alguém conferir.

A gravação da planilha é atômica (arquivo temporário + troca), com uma cópia
de segurança do original antes da primeira gravação da execução.
"""
from __future__ import annotations

import csv
import os
import re
import shutil
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from .config import (
    ABA_MENSAGENS_ABERTAS,
    SITUACAO_MENSAGENS_IMPORTANTES,
    SITUACAO_PROTOCOLADA,
    SITUACAO_VERIFICAR,
)
from .desfechos import numero_documento
from .planilha import (
    COLUNA_NUMERO_DOCUMENTO,
    COLUNA_PERDCOMP,
    COLUNA_SITUACAO_VERIFICACAO,
    COLUNA_TRIBUTO,
    DadosPlanilha,
    LinhaPerdcomp,
)

MARCA_ENVIANDO = "__ENVIANDO__"
# O servidor recusou o envio (não transmitiu): anula o "enviando" anterior.
MARCA_NAO_TRANSMITIDO = "__NAO_TRANSMITIDO__"
# Coluna K corrigida (o tributo da planilha estava trocado): não é desfecho.
MARCA_TRIBUTO = "__TRIBUTO_CORRIGIDO__"
CABECALHO_SITUACAO = "Situação da Verificação"
CABECALHO_NUMERO = "DCOMP protocolada"
CAMPOS = ("data_hora", "linha", "perdcomp", "cnpj", "situacao", "detalhe")
FORMATO_DATA_HORA = "%d/%m/%Y %H:%M:%S"
# Duas sessões ao mesmo tempo (pedido do usuário, 18/11/2026): no diário da
# OUTRA sessão, um "enviando" mais novo que isto é um envio EM ANDAMENTO (o
# desfecho chega em até 3 min), e não uma quarentena.
ENVIO_EM_ANDAMENTO = timedelta(minutes=15)
# Gravação da planilha: uma sessão de cada vez (trava entre processos).
ESPERA_TRAVA_S = 300
# Mensagens importantes abertas (regra do usuário, 19/11/2026): uma linha por
# mensagem na aba ABA_MENSAGENS_ABERTAS; diário próprio, como o da AA.
CABECALHO_MENSAGENS = ("CNPJ", "Empresa", "Certificado", "Assunto da mensagem", "Aberta em",
                       "ID da mensagem")
CAMPOS_MENSAGENS = ("cnpj", "empresa", "certificado", "assunto", "data_hora", "isn")


def _ler_diario(arquivo: Path, *, envios_em_andamento_desde: datetime | None = None
                ) -> dict[tuple[int, str], str]:
    """(numero_linha, perdcomp) -> situação final de UM diário. Tentativa de
    envio sem desfecho registrado vira SITUACAO_VERIFICAR — exceto, com
    `envios_em_andamento_desde`, as feitas desde então (outra sessão ainda
    esperando o desfecho)."""
    if not arquivo.exists():
        return {}
    finais: dict[tuple[int, str], str] = {}
    with open(arquivo, encoding="utf-8-sig", newline="") as f:
        for registro in csv.DictReader(f, delimiter=";"):
            try:
                chave = (int(registro["linha"]), registro["perdcomp"])
            except (KeyError, TypeError, ValueError):
                continue
            situacao = registro.get("situacao") or ""
            # Ordem cronológica: a última anotação vale. Um "enviando" sem
            # desfecho depois dele fica como quarentena.
            if situacao == MARCA_ENVIANDO:
                if envios_em_andamento_desde is not None:
                    try:
                        quando = datetime.strptime(registro.get("data_hora") or "",
                                                   FORMATO_DATA_HORA)
                    except ValueError:
                        quando = None
                    if quando is not None and quando >= envios_em_andamento_desde:
                        continue
                finais[chave] = SITUACAO_VERIFICAR
            elif situacao == MARCA_TRIBUTO:
                continue
            elif situacao == MARCA_NAO_TRANSMITIDO:
                if finais.get(chave) == SITUACAO_VERIFICAR:
                    finais.pop(chave)
            elif situacao:
                finais[chave] = situacao
    return finais


def _numeros_do_diario(arquivo: Path) -> dict[str, str]:
    """PER/DCOMP -> número da Declaração protocolada, de UM diário (lido do
    detalhe "Declaração enviada — nº ...")."""
    if not arquivo.exists():
        return {}
    numeros: dict[str, str] = {}
    with open(arquivo, encoding="utf-8-sig", newline="") as f:
        for registro in csv.DictReader(f, delimiter=";"):
            if (registro.get("situacao") or "") != SITUACAO_PROTOCOLADA:
                continue
            numero = numero_documento(registro.get("detalhe") or "")
            if numero and registro.get("perdcomp"):
                numeros[registro["perdcomp"]] = numero
    return numeros


def nome_diario(planilha: Path, sessao: int = 1) -> str:
    """Sessão 1 mantém o nome de sempre; as outras ganham o próprio diário
    (dois processos não escrevem no mesmo arquivo)."""
    sufixo = "" if sessao == 1 else f"_sessao{sessao}"
    return f"{planilha.stem}{sufixo}_verificacao.csv"


def nome_diario_mensagens(planilha: Path, sessao: int = 1) -> str:
    sufixo = "" if sessao == 1 else f"_sessao{sessao}"
    return f"{planilha.stem}{sufixo}_mensagens.csv"


def _ler_mensagens(arquivo: Path) -> list[tuple]:
    """As linhas (na ordem de CABECALHO_MENSAGENS) de um diário de mensagens."""
    if not arquivo.exists():
        return []
    with open(arquivo, encoding="utf-8-sig", newline="") as f:
        return [tuple(registro.get(c) or "" for c in CAMPOS_MENSAGENS)
                for registro in csv.DictReader(f, delimiter=";")]


class RegistroResultados:
    def __init__(self, caminho_planilha: str | Path, pasta_diario: Path, pasta_backup: Path, *,
                 salvar_a_cada: int = 1, intervalo_s: float = 600,
                 em_segundo_plano: bool = False, sessao: int = 1) -> None:
        self.planilha = Path(caminho_planilha)
        self.diario = Path(pasta_diario) / nome_diario(self.planilha, sessao)
        self.diario_mensagens = Path(pasta_diario) / nome_diario_mensagens(self.planilha, sessao)
        self._arquivo_trava = Path(pasta_diario) / f"{self.planilha.stem}.trava"
        self._pasta_backup = Path(pasta_backup)
        self._salvar_a_cada = salvar_a_cada
        self._intervalo_s = intervalo_s
        self._ultimo_save = time.monotonic()
        self._backup_feito = False
        # numero_linha -> (perdcomp, situacao) ainda não gravados na planilha
        self._a_gravar: dict[int, tuple[str, str]] = {}
        # numero_linha -> (perdcomp, tributo certo) para a coluna K
        self._tributos: dict[int, tuple[str, str]] = {}
        # numero_linha -> (perdcomp, número da Declaração) para a coluna AB
        self._numeros: dict[int, tuple[str, str]] = {}
        # (cnpj, id da mensagem) -> linha da aba das mensagens importantes abertas
        self._mensagens: dict[tuple[str, str], tuple] = {}
        self.ultima_falha = ""  # motivo da última gravação da planilha que falhou
        # Em segundo plano (pedido do usuário, 18/11/2026): gravar a planilha leva
        # ~24 s e segurava o "Novo Documento" da linha seguinte. O diário continua
        # síncrono (a garantia); a coluna AA é gravada por uma thread, em ordem.
        self._trava = threading.Lock()
        self._acordar = threading.Event()
        self._parar = False
        self._thread: threading.Thread | None = None
        if em_segundo_plano:
            self._thread = threading.Thread(target=self._gravador, name="gravador-planilha",
                                            daemon=True)
            self._thread.start()

    def _gravador(self) -> None:
        while True:
            self._acordar.wait(timeout=5)
            self._acordar.clear()
            with self._trava:
                ha_fila = bool(self._a_gravar or self._numeros or self._tributos
                               or self._mensagens)
            if ha_fila:
                self.salvar()
            if self._parar:
                return

    def fechar(self) -> bool:
        """Termina a gravação em segundo plano e grava o que sobrou. True se a
        planilha ficou em dia."""
        if self._thread is not None:
            self._parar = True
            self._acordar.set()
            self._thread.join(timeout=300)
            self._thread = None
        return self.salvar()

    # ── diário ───────────────────────────────────────────────────────────────
    def _anotar(self, linha: LinhaPerdcomp, situacao: str, detalhe: str = "") -> None:
        self.diario.parent.mkdir(parents=True, exist_ok=True)
        novo = not self.diario.exists()
        with open(self.diario, "a", encoding="utf-8-sig", newline="") as f:
            escritor = csv.writer(f, delimiter=";")
            if novo:
                escritor.writerow(CAMPOS)
            escritor.writerow((datetime.now().strftime(FORMATO_DATA_HORA), linha.numero_linha,
                               linha.perdcomp, linha.cnpj, situacao, detalhe[:300]))
            f.flush()
            os.fsync(f.fileno())

    def ler_diario(self) -> dict[tuple[int, str], str]:
        """(numero_linha, perdcomp) -> situação final. Tentativa de envio sem
        desfecho registrado vira SITUACAO_VERIFICAR."""
        return _ler_diario(self.diario)

    def _desfechos_por_perdcomp(self, dados: DadosPlanilha) -> dict[str, str]:
        """PER/DCOMP -> resultado já conhecido, de QUALQUER planilha desta máquina
        (todos os diários da pasta) e da coluna AA desta planilha.

        A planilha foi dividida em partes (18/11/2026): as linhas mudaram de
        número, e a mesma planilha repete PER/DCOMPs (ex.: linhas 499 e 513).
        Casar só pelo número da linha deixaria o mesmo PER/DCOMP ser transmitido
        de novo. Um resultado final vale mais que "Verificar no e-CAC"."""
        conhecidos: dict[str, str] = {}

        def _guardar(perdcomp: str, situacao: str) -> None:
            if not perdcomp or not situacao or situacao == SITUACAO_MENSAGENS_IMPORTANTES:
                return
            atual = conhecidos.get(perdcomp)
            if atual is None or (atual == SITUACAO_VERIFICAR and situacao != SITUACAO_VERIFICAR):
                conhecidos[perdcomp] = situacao

        em_andamento = datetime.now() - ENVIO_EM_ANDAMENTO
        for arquivo in sorted(self.diario.parent.glob("*_verificacao.csv")):
            outro = arquivo.resolve() != self.diario.resolve()
            for (_, perdcomp), situacao in _ler_diario(
                    arquivo, envios_em_andamento_desde=em_andamento if outro else None).items():
                _guardar(perdcomp, situacao)
        for linha in dados.linhas:
            _guardar(linha.perdcomp, linha.situacao_verificacao.strip())
        return conhecidos

    def reconciliar(self, dados: DadosPlanilha) -> int:
        """Aplica à planilha (em memória e na fila de gravação) o que já se sabe
        e a AA não tem: o diário desta planilha (por linha) e, pelo NÚMERO DO
        PER/DCOMP, os diários das outras planilhas e as outras linhas desta.
        Devolve quantas linhas foram preenchidas assim."""
        finais = self.ler_diario()
        por_perdcomp = self._desfechos_por_perdcomp(dados)
        aplicadas = 0
        for linha in dados.linhas:
            if not linha.pendente:
                continue
            situacao = (finais.get((linha.numero_linha, linha.perdcomp))
                        or por_perdcomp.get(linha.perdcomp))
            # A marca de mensagens importantes não é resultado (a linha é refeita).
            if situacao and situacao != SITUACAO_MENSAGENS_IMPORTANTES:
                linha.situacao_verificacao = situacao
                with self._trava:
                    self._a_gravar[linha.numero_linha] = (linha.perdcomp, situacao)
                aplicadas += 1
        self._reconciliar_numeros(dados)
        try:
            self.reconciliar_mensagens()
        except Exception as e:  # noqa: BLE001 — a aba das mensagens nunca impede a execução
            print(f"  -> [AVISO] Diario das mensagens nao conferido ({type(e).__name__}).")
        return aplicadas

    def reconciliar_mensagens(self) -> int:
        """Mensagens dos diários desta planilha (todas as sessões) que ainda não
        estão na aba das abertas entram na fila. Devolve quantas."""
        from openpyxl import load_workbook

        pasta = self.diario_mensagens.parent
        arquivos = [pasta / f"{self.planilha.stem}_mensagens.csv",
                    *sorted(pasta.glob(f"{self.planilha.stem}_sessao*_mensagens.csv"))]
        anotadas = [linha for arquivo in arquivos for linha in _ler_mensagens(arquivo)]
        if not anotadas:
            return 0
        workbook = load_workbook(self.planilha, read_only=True)
        try:
            existentes = set()
            if ABA_MENSAGENS_ABERTAS in workbook.sheetnames:
                for valores in workbook[ABA_MENSAGENS_ABERTAS].iter_rows(min_row=2, values_only=True):
                    if valores and len(valores) >= 6:
                        existentes.add((str(valores[0] or "").strip(), str(valores[5] or "").strip()))
        finally:
            workbook.close()
        novas = 0
        with self._trava:
            for linha in anotadas:
                chave = (linha[0], linha[5])
                if chave not in existentes and chave not in self._mensagens:
                    self._mensagens[chave] = linha
                    novas += 1
        if novas:
            self._acordar.set()
        return novas

    def _reconciliar_numeros(self, dados: DadosPlanilha) -> int:
        """Coluna AB das linhas protocoladas que ainda não a têm, pelo número
        do PER/DCOMP: dos diários (todas as planilhas desta máquina) e das
        outras linhas desta planilha (PER/DCOMP repetido)."""
        numeros: dict[str, str] = {}
        for arquivo in sorted(self.diario.parent.glob("*_verificacao.csv")):
            numeros.update(_numeros_do_diario(arquivo))
        for linha in dados.linhas:
            if linha.numero_documento.strip() and linha.perdcomp:
                numeros.setdefault(linha.perdcomp, linha.numero_documento.strip())
        aplicadas = 0
        for linha in dados.linhas:
            if (linha.numero_documento.strip()
                    or linha.situacao_verificacao.strip() != SITUACAO_PROTOCOLADA):
                continue
            numero = numeros.get(linha.perdcomp)
            if numero:
                linha.numero_documento = numero
                with self._trava:
                    self._numeros[linha.numero_linha] = (linha.perdcomp, numero)
                aplicadas += 1
        if aplicadas:
            self._acordar.set()
        return aplicadas

    # ── API usada pela execução ──────────────────────────────────────────────
    def marcar_envio(self, linha: LinhaPerdcomp) -> None:
        """ANTES de clicar "Enviar": a tentativa fica no diário."""
        self._anotar(linha, MARCA_ENVIANDO)

    def corrigir_tributo(self, linha: LinhaPerdcomp, tributo: str) -> None:
        """A Receita confirmou que o tributo certo é `tributo` (coluna K trocada).
        Vai para a planilha junto com a próxima gravação da AA."""
        self._anotar(linha, MARCA_TRIBUTO, f"{linha.tributo} -> {tributo}")
        with self._trava:
            self._tributos[linha.numero_linha] = (linha.perdcomp, tributo)
        linha.tributo = tributo

    def marcar_nao_transmitido(self, linha: LinhaPerdcomp, detalhe: str = "") -> None:
        """O servidor recusou o envio: a tentativa não conta (a linha é refeita)."""
        self._anotar(linha, MARCA_NAO_TRANSMITIDO, detalhe)

    def registrar(self, linha: LinhaPerdcomp, situacao: str, detalhe: str = "") -> None:
        self._anotar(linha, situacao, detalhe)
        linha.situacao_verificacao = situacao
        numero = numero_documento(detalhe) if situacao == SITUACAO_PROTOCOLADA else ""
        with self._trava:
            self._a_gravar[linha.numero_linha] = (linha.perdcomp, situacao)
            if numero:
                linha.numero_documento = numero
                self._numeros[linha.numero_linha] = (linha.perdcomp, numero)
            vencido = (len(self._a_gravar) >= self._salvar_a_cada
                       or time.monotonic() - self._ultimo_save >= self._intervalo_s)
        if not vencido:
            return
        if self._thread is not None:
            self._acordar.set()  # a thread grava; a automação segue para o "Novo Documento"
        else:
            self.salvar()

    def registrar_mensagem(self, *, cnpj: str, empresa: str, certificado: str, assunto: str,
                           isn: str) -> None:
        """Uma mensagem importante aberta: diário na hora (fsync) e a aba das
        abertas na próxima gravação da planilha."""
        linha = (cnpj, empresa, certificado, " ".join(str(assunto or "").split()),
                 datetime.now().strftime(FORMATO_DATA_HORA), str(isn))
        self.diario_mensagens.parent.mkdir(parents=True, exist_ok=True)
        novo = not self.diario_mensagens.exists()
        with open(self.diario_mensagens, "a", encoding="utf-8-sig", newline="") as f:
            escritor = csv.writer(f, delimiter=";")
            if novo:
                escritor.writerow(CAMPOS_MENSAGENS)
            escritor.writerow(linha)
            f.flush()
            os.fsync(f.fileno())
        with self._trava:
            self._mensagens[(linha[0], linha[5])] = linha
        if self._thread is not None:
            self._acordar.set()
        else:
            self.salvar()

    @property
    def pendentes_de_gravacao(self) -> int:
        return len(self._a_gravar) + len(self._numeros) + len(self._mensagens)

    # ── planilha ─────────────────────────────────────────────────────────────
    def _backup(self) -> None:
        if self._backup_feito:
            return
        self._pasta_backup.mkdir(parents=True, exist_ok=True)
        destino = self._pasta_backup / (f"{self.planilha.stem}_antes_{datetime.now():%Y%m%d_%H%M%S}"
                                        f"{self.planilha.suffix}")
        shutil.copy2(self.planilha, destino)
        self._backup_feito = True
        print(f"  -> Copia de seguranca da planilha: {destino}")

    @contextmanager
    def _trava_entre_sessoes(self):
        """Só uma sessão grava a planilha por vez: cada gravação relê o arquivo,
        escreve as SUAS células e o substitui — duas ao mesmo tempo perderiam
        o que a outra gravou. Levanta TimeoutError se não conseguir a vez."""
        import msvcrt

        self._arquivo_trava.parent.mkdir(parents=True, exist_ok=True)
        with open(self._arquivo_trava, "a+b") as f:
            limite = time.monotonic() + ESPERA_TRAVA_S
            while True:
                try:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= limite:
                        raise TimeoutError("outra sessao esta gravando a planilha ha muito tempo")
                    time.sleep(0.5)
            try:
                yield
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)

    def salvar(self) -> bool:
        """Grava a fila na coluna AA. False (e a fila continua) se não deu —
        tipicamente a planilha aberta no Excel. Nunca levanta."""
        with self._trava:
            fila = dict(self._a_gravar)
            tributos = dict(self._tributos)
            numeros = dict(self._numeros)
            mensagens = dict(self._mensagens)
        if not fila and not tributos and not numeros and not mensagens:
            return True
        temporario = self.planilha.with_name(f"~gravando_{self.planilha.name}")
        try:
            with self._trava_entre_sessoes():
                gravadas = self._gravar_na_planilha(fila, tributos, numeros, temporario,
                                                    mensagens)
        except Exception as e:  # noqa: BLE001 — o diário já tem tudo; tenta de novo depois
            self.ultima_falha = f"{type(e).__name__}: {e}"
            print(f"  -> [AVISO] A planilha nao pode ser gravada agora ({type(e).__name__}) — "
                  "esta aberta no Excel? Os resultados estao no diario e serao gravados depois.")
            try:
                temporario.unlink(missing_ok=True)
            except OSError:
                pass
            self._ultimo_save = time.monotonic()
            return False
        with self._trava:
            for numero in gravadas:
                # Só sai da fila se não chegou um resultado NOVO para a linha
                # enquanto a planilha era gravada.
                if self._a_gravar.get(numero) == fila[numero]:
                    self._a_gravar.pop(numero, None)
            for numero in tributos:
                if self._tributos.get(numero) == tributos[numero]:
                    self._tributos.pop(numero, None)
            for numero in numeros:
                if self._numeros.get(numero) == numeros[numero]:
                    self._numeros.pop(numero, None)
            for chave in mensagens:
                self._mensagens.pop(chave, None)
        self._ultimo_save = time.monotonic()
        self.ultima_falha = ""
        print("  -> Planilha gravada.")
        return True

    def _gravar_na_planilha(self, fila, tributos, numeros, temporario: Path,
                            mensagens=None) -> list[int]:
        from openpyxl import load_workbook

        self._backup()
        print(f"  -> Gravando {len(fila)} resultado(s) na coluna "
              f"{COLUNA_SITUACAO_VERIFICACAO} da planilha...")
        workbook = load_workbook(self.planilha)
        try:
            aba = workbook.worksheets[0]
            celula_cabecalho = aba[f"{COLUNA_SITUACAO_VERIFICACAO}1"]
            if not str(celula_cabecalho.value or "").strip():
                celula_cabecalho.value = CABECALHO_SITUACAO
            gravadas = []
            for numero, (perdcomp, situacao) in sorted(fila.items()):
                # Confere que a linha ainda é a do mesmo PER/DCOMP: se alguém
                # inseriu/apagou linhas na planilha, NÃO grava no lugar errado.
                lido = re.sub(r"\D", "", str(aba[f"{COLUNA_PERDCOMP}{numero}"].value or ""))
                if lido != perdcomp:
                    print(f"  -> [AVISO] Linha {numero}: o PER/DCOMP da planilha mudou; resultado "
                          "NAO gravado na AA (continua no diario).")
                    gravadas.append(numero)
                    continue
                aba[f"{COLUNA_SITUACAO_VERIFICACAO}{numero}"] = situacao
                gravadas.append(numero)
            for numero, (perdcomp, tributo) in tributos.items():
                lido = re.sub(r"\D", "", str(aba[f"{COLUNA_PERDCOMP}{numero}"].value or ""))
                if lido == perdcomp:
                    aba[f"{COLUNA_TRIBUTO}{numero}"] = tributo
            if numeros:
                cabecalho_ab = aba[f"{COLUNA_NUMERO_DOCUMENTO}1"]
                if not str(cabecalho_ab.value or "").strip():
                    cabecalho_ab.value = CABECALHO_NUMERO
            for numero, (perdcomp, documento) in numeros.items():
                lido = re.sub(r"\D", "", str(aba[f"{COLUNA_PERDCOMP}{numero}"].value or ""))
                if lido == perdcomp:
                    aba[f"{COLUNA_NUMERO_DOCUMENTO}{numero}"] = documento
            if mensagens:
                self._gravar_mensagens(workbook, mensagens)
            workbook.save(temporario)
        finally:
            workbook.close()
        os.replace(temporario, self.planilha)
        return gravadas

    @staticmethod
    def _gravar_mensagens(workbook, mensagens) -> None:
        """Acrescenta as mensagens à aba das abertas (criada no fim, com o
        cabeçalho, se não existir). A mesma mensagem (CNPJ + ID) não repete."""
        from openpyxl.styles import Font

        if ABA_MENSAGENS_ABERTAS in workbook.sheetnames:
            aba = workbook[ABA_MENSAGENS_ABERTAS]
        else:
            aba = workbook.create_sheet(ABA_MENSAGENS_ABERTAS)
            aba.append(CABECALHO_MENSAGENS)
            for celula in aba[1]:
                celula.font = Font(bold=True)
            for letra, largura in zip("ABCDEF", (18, 45, 22, 90, 20, 16)):
                aba.column_dimensions[letra].width = largura
        existentes = {(str(v[0] or "").strip(), str(v[5] or "").strip())
                      for v in aba.iter_rows(min_row=2, values_only=True) if v and len(v) >= 6}
        novas = [linha for chave, linha in mensagens.items() if chave not in existentes]
        for linha in novas:
            aba.append(list(linha))
        if novas:
            print(f"  -> {len(novas)} mensagem(ns) importante(s) aberta(s) na aba "
                  f"'{ABA_MENSAGENS_ABERTAS}'.")
