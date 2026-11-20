"""Leitura da planilha de entrada: a lista de PER/DCOMPs já protocolados.

Layout = PRIMEIRA aba da planilha de exemplo ("pers com saldo", depois
renomeada "pis cofins"), cabeçalho na linha 1 e dados a partir da linha 2:

    A Parceiro            J Ano                       S Compensação de Ofício
    B Procurador (=cert.) K Tributo                   T Selic Comp. Ofício
    C Responsável Técnico L Data do Protocolo         U Aviso
    D CNPJ                M PERDCOMP                  V Valor Restituído/Ressarcido
    E Empresa             N Retificadora              W Selic
    F CNAE Principal      O Valor Requerido           X Indeferimento
    G Tese                P Valor da Tese             Y Saldo Perdcomp
    H Tipo                Q Valor Compensado          Z Status
    I Mês-Tri             R Selic Compensada          AA Situação da Verificação (saída)

A planilha MISTURA empresas (coluna D) e procuradores (coluna B): cada
procurador é um certificado diferente. Por isso o lote é organizado em grupos
— certificado > empresa > linhas — para fazer UM login por certificado e só
trocar o perfil entre as empresas dele (ver `planejar_lote`).

As letras das colunas são as do exemplo, mas o cabeçalho é CONFERIDO antes de
qualquer login: uma planilha com as colunas deslocadas faria a automação logar
como a empresa errada.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from .config import PAGAMENTO_INDEVIDO_ATIVO, SITUACAO_MENSAGENS_IMPORTANTES

# Colunas lidas (letra -> campo). A coluna AA é a SAÍDA da automação.
COLUNA_PARCEIRO = "A"
COLUNA_PROCURADOR = "B"
COLUNA_CNPJ = "D"
COLUNA_EMPRESA = "E"
COLUNA_TIPO = "H"
COLUNA_MES_TRI = "I"
COLUNA_ANO = "J"
COLUNA_TRIBUTO = "K"
COLUNA_DATA_PROTOCOLO = "L"
COLUNA_PERDCOMP = "M"
COLUNA_SALDO = "Y"
COLUNA_STATUS = "Z"
COLUNA_SITUACAO_VERIFICACAO = "AA"
# Número da Declaração protocolada (popup do envio). Pedido do usuário, 18/11/2026.
COLUNA_NUMERO_DOCUMENTO = "AB"

# Cabeçalho esperado (normalizado) nas colunas de que a automação depende. Se
# não bater, a execução para ANTES do login, dizendo a célula.
CABECALHO_OBRIGATORIO = {
    COLUNA_PROCURADOR: "procurador",
    COLUNA_CNPJ: "cnpj",
    COLUNA_PERDCOMP: "perdcomp",
}
# Conferido só se existir (a coluna de saída pode ainda não ter sido criada).
CABECALHO_SITUACAO = "situacao da verificacao"

# Linhas vazias seguidas que encerram a leitura. Não para na PRIMEIRA vazia:
# uma linha em branco perdida no meio não pode esconder o resto da planilha;
# mas também não varre um milhão de linhas formatadas (a aba "inss" do exemplo
# tem max_row = 1.029.157).
LINHAS_VAZIAS_PARA_PARAR = 20


class PlanilhaInvalida(ValueError):
    """A planilha não tem o layout esperado. A mensagem diz a célula."""


def normalizar_texto(valor) -> str:
    """Minúsculas, sem acento, pontuação virando espaço, espaços colapsados.

    'Situação da Verificação' -> 'situacao da verificacao'; 'YURI ' -> 'yuri'.
    """
    texto = unicodedata.normalize("NFD", str(valor or "").casefold())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = "".join(c if c.isalnum() or c == "&" else " " for c in texto)
    return " ".join(texto.split())


def normalizar_cnpj(valor) -> str:
    """CNPJ com exatamente 14 dígitos, ou "" se a célula não tem um CNPJ.

    Aceita '10.740.842/0001-33', '10740842000133' e a célula numérica que o
    Excel deixa sem os zeros à esquerda (623904000173 -> '00623904000173').
    Mesma regra das Protocolações (`excel_prep._normalizar_cnpj`)."""
    if valor is None or isinstance(valor, bool):
        return ""
    if isinstance(valor, int):
        texto = str(valor)
    elif isinstance(valor, float):
        texto = format(Decimal(str(valor)), "f").split(".")[0]
    else:
        texto = str(valor)
    digitos = re.sub(r"\D", "", texto)
    if not digitos or len(digitos) > 14:
        return ""
    return digitos.zfill(14)


TRIBUTO_PIS = "PIS"
TRIBUTO_COFINS = "COFINS"


def tipo_tributo(valor) -> str:
    """Coluna K -> "PIS", "COFINS" ou "" (fora do escopo por enquanto).

    As variantes da planilha seguem o tributo que aparece no nome: 'PIS ',
    'PIS/PASEP', 'PIS / PASEP' -> PIS; 'Cofins', 'COFINS/FASE' -> COFINS. O que
    cita os dois ('PIS/COFINS') ou nenhum ('2024', 'IRPJ') fica de fora — o
    usuário ainda vai definir (18/11/2026)."""
    palavras = set(normalizar_texto(valor).split())
    tem_pis, tem_cofins = "pis" in palavras, "cofins" in palavras
    if tem_pis and not tem_cofins:
        return TRIBUTO_PIS
    if tem_cofins and not tem_pis:
        return TRIBUTO_COFINS
    return ""


# Tipo de crédito "Pagamento Indevido ou a Maior" (regra do usuário, 20/11/2026):
# PER/DCOMP de código 04 (restituição de pagamento indevido) e toda linha cuja
# coluna K não cita PIS nem COFINS (INSS, IRPJ, CSLL, IPI...).
TRIBUTO_PAGAMENTO_INDEVIDO = "PAGAMENTO INDEVIDO"
CODIGO_PAGAMENTO_INDEVIDO = "04"


def tipo_credito(tributo, perdcomp: str, *, pagamento_indevido: bool | None = None) -> str:
    """Opção do 1º dropdown (Tipo de Crédito): "PIS", "COFINS",
    "PAGAMENTO INDEVIDO" ou "" (fora do escopo).

    - código 04 no nº do PER/DCOMP -> PAGAMENTO INDEVIDO, seja qual for a coluna K;
    - coluna K só com PIS ou só com COFINS -> esse tributo;
    - coluna K com PIS e COFINS juntos ('PIS/COFINS') ou vazia -> "" (indefinido);
    - qualquer outro texto (INSS, IRPJ, CSLL, IPI...) -> PAGAMENTO INDEVIDO.
    Com `pagamento_indevido` falso (padrão: config.PAGAMENTO_INDEVIDO_ATIVO),
    só a coluna K: "PIS", "COFINS" ou ""."""
    if pagamento_indevido is None:
        pagamento_indevido = PAGAMENTO_INDEVIDO_ATIVO
    if not pagamento_indevido:
        return tipo_tributo(tributo)
    if codigo_credito(perdcomp) == CODIGO_PAGAMENTO_INDEVIDO:
        return TRIBUTO_PAGAMENTO_INDEVIDO
    tributo_k = tipo_tributo(tributo)
    if tributo_k:
        return tributo_k
    palavras = set(normalizar_texto(tributo).split())
    if not palavras or "pis" in palavras or "cofins" in palavras:
        return ""
    return TRIBUTO_PAGAMENTO_INDEVIDO


def status_z_permitido(status, permitidos) -> bool:
    """O status da Receita (coluna Z) está entre os que entram no lote?
    `permitidos` vazio = todos."""
    if not permitidos:
        return True
    return normalizar_texto(status) in {normalizar_texto(s) for s in permitidos}


def _texto(valor) -> str:
    """Valor da célula como texto, sem o '.0' que o Excel gera em número."""
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor).strip()


def codigo_credito(perdcomp: str) -> str:
    """Código do tipo de crédito no número do PER/DCOMP (24 dígitos)."""
    return perdcomp[18:20] if len(perdcomp) == 24 else ""


@dataclass
class LinhaPerdcomp:
    """Uma linha da planilha = um PER/DCOMP protocolado a verificar."""

    numero_linha: int
    procurador: str = ""
    cnpj: str = ""           # 14 dígitos; "" se a célula D não tem CNPJ válido
    cnpj_bruto: str = ""     # como veio na planilha (para a mensagem de erro)
    empresa: str = ""
    parceiro: str = ""
    tipo: str = ""
    mes_tri: str = ""
    ano: str = ""
    tributo: str = ""
    data_protocolo: Any = None
    perdcomp: str = ""
    saldo: Any = None
    status: str = ""
    situacao_verificacao: str = ""
    numero_documento: str = ""  # coluna AB
    # Todas as células da linha por letra de coluna, para as próximas etapas
    # do fluxo (ainda a detalhar) não precisarem mexer na leitura.
    valores: dict[str, Any] = field(default_factory=dict)

    @property
    def rotulo(self) -> str:
        empresa = self.empresa.strip() or self.cnpj or self.cnpj_bruto
        return f"Linha {self.numero_linha} — {empresa} — PER/DCOMP {self.perdcomp or '?'}"

    @property
    def tipo_tributo(self) -> str:
        return tipo_tributo(self.tributo)

    @property
    def tipo_credito(self) -> str:
        return tipo_credito(self.tributo, self.perdcomp)

    @property
    def pendente(self) -> bool:
        """Pendente = coluna AA vazia. Qualquer resultado gravado ali (inclusive
        "Verificar no e-CAC") tira a linha das próximas execuções — menos a
        marca de mensagens importantes não lidas, que não é resultado: com a
        regra de 19/11/2026 a automação abre as mensagens e refaz a linha."""
        situacao = self.situacao_verificacao.strip()
        return not situacao or situacao == SITUACAO_MENSAGENS_IMPORTANTES


@dataclass
class DadosPlanilha:
    caminho: str
    nome_aba: str
    linhas: list[LinhaPerdcomp]
    tem_coluna_situacao: bool

    @property
    def pendentes(self) -> list[LinhaPerdcomp]:
        return [linha for linha in self.linhas if linha.pendente]


def _letra_para_indice(letra: str) -> int:
    """'A' -> 0, 'Z' -> 25, 'AA' -> 26."""
    indice = 0
    for c in letra:
        indice = indice * 26 + (ord(c.upper()) - ord("A") + 1)
    return indice - 1


def _letra(indice: int) -> str:
    """0 -> 'A', 26 -> 'AA'."""
    letras = ""
    indice += 1
    while indice:
        indice, resto = divmod(indice - 1, 26)
        letras = chr(ord("A") + resto) + letras
    return letras


def _celula(linha: tuple, letra: str):
    i = _letra_para_indice(letra)
    return linha[i] if i < len(linha) else None


def conferir_cabecalho(cabecalho: tuple) -> bool:
    """Levanta PlanilhaInvalida se as colunas obrigatórias não estão onde se
    espera. Devolve True se a coluna de saída (AA) já existe."""
    problemas = []
    for letra, esperado in CABECALHO_OBRIGATORIO.items():
        lido = normalizar_texto(_celula(cabecalho, letra))
        if esperado not in lido:
            problemas.append(f"{letra}1 deveria ser '{esperado.upper()}' (está '{lido or 'vazia'}')")
    if problemas:
        raise PlanilhaInvalida(
            "A primeira aba não tem o layout esperado: " + "; ".join(problemas) + "."
        )
    situacao = normalizar_texto(_celula(cabecalho, COLUNA_SITUACAO_VERIFICACAO))
    if situacao and situacao != CABECALHO_SITUACAO:
        raise PlanilhaInvalida(
            f"{COLUNA_SITUACAO_VERIFICACAO}1 deveria ser 'Situação da Verificação' "
            f"(está '{situacao}') — a automação grava o resultado nessa coluna."
        )
    return bool(situacao)


def montar_linha(numero_linha: int, valores: tuple) -> LinhaPerdcomp:
    cnpj_bruto = _texto(_celula(valores, COLUNA_CNPJ))
    return LinhaPerdcomp(
        numero_linha=numero_linha,
        procurador=_texto(_celula(valores, COLUNA_PROCURADOR)),
        cnpj=normalizar_cnpj(_celula(valores, COLUNA_CNPJ)),
        cnpj_bruto=cnpj_bruto,
        empresa=_texto(_celula(valores, COLUNA_EMPRESA)),
        parceiro=_texto(_celula(valores, COLUNA_PARCEIRO)),
        tipo=_texto(_celula(valores, COLUNA_TIPO)),
        mes_tri=_texto(_celula(valores, COLUNA_MES_TRI)),
        ano=_texto(_celula(valores, COLUNA_ANO)),
        tributo=_texto(_celula(valores, COLUNA_TRIBUTO)),
        data_protocolo=_celula(valores, COLUNA_DATA_PROTOCOLO),
        perdcomp=re.sub(r"\D", "", _texto(_celula(valores, COLUNA_PERDCOMP)))
        or _texto(_celula(valores, COLUNA_PERDCOMP)),
        saldo=_celula(valores, COLUNA_SALDO),
        status=_texto(_celula(valores, COLUNA_STATUS)),
        situacao_verificacao=_texto(_celula(valores, COLUNA_SITUACAO_VERIFICACAO)),
        numero_documento=_texto(_celula(valores, COLUNA_NUMERO_DOCUMENTO)),
        valores={_letra(i): v for i, v in enumerate(valores)},
    )


def ler_planilha(caminho: str | Path) -> DadosPlanilha:
    """Lê a PRIMEIRA aba. Não altera o arquivo."""
    caminho = Path(caminho)
    if not caminho.is_file():
        raise FileNotFoundError(f"Planilha não encontrada: {caminho}")

    # read_only: ~19 mil linhas x 27 colunas em poucos segundos, sem carregar
    # estilos. A gravação (quando existir) reabre o arquivo para escrita.
    workbook = load_workbook(filename=str(caminho), data_only=True, read_only=True)
    try:
        aba = workbook.worksheets[0]
        iterador = aba.iter_rows(values_only=True)
        cabecalho = next(iterador, None)
        if cabecalho is None:
            raise PlanilhaInvalida("A primeira aba está vazia.")
        tem_situacao = conferir_cabecalho(cabecalho)

        linhas: list[LinhaPerdcomp] = []
        vazias = 0
        for numero_linha, valores in enumerate(iterador, start=2):
            if not any(v not in (None, "") for v in valores):
                vazias += 1
                if vazias >= LINHAS_VAZIAS_PARA_PARAR:
                    break
                continue
            vazias = 0
            linhas.append(montar_linha(numero_linha, valores))
        return DadosPlanilha(
            caminho=str(caminho), nome_aba=aba.title, linhas=linhas,
            tem_coluna_situacao=tem_situacao,
        )
    finally:
        workbook.close()


# ── Organização do lote ──────────────────────────────────────────────────────

@dataclass
class GrupoEmpresa:
    cnpj: str
    empresa: str
    linhas: list[LinhaPerdcomp] = field(default_factory=list)


@dataclass
class GrupoCertificado:
    """Todas as linhas que entram no e-CAC com o mesmo certificado."""

    certificado: str            # nome do .pfx (sem extensão)
    empresas: list[GrupoEmpresa] = field(default_factory=list)

    @property
    def total_linhas(self) -> int:
        return sum(len(e.linhas) for e in self.empresas)


def planejar_lote(linhas_com_certificado: list[tuple[LinhaPerdcomp, str]]) -> list[GrupoCertificado]:
    """Agrupa (linha, certificado) em certificado > empresa > linhas.

    A ordem de primeira aparição na planilha é mantida nos três níveis. Assim um
    certificado faz UM login, e entre as empresas dele só troca o perfil — que
    é bem mais barato e não gasta vaga de dispositivo da conta gov.br.
    """
    grupos: dict[str, GrupoCertificado] = {}
    empresas: dict[tuple[str, str], GrupoEmpresa] = {}
    for linha, certificado in linhas_com_certificado:
        grupo = grupos.get(certificado)
        if grupo is None:
            grupo = grupos[certificado] = GrupoCertificado(certificado=certificado)
        chave = (certificado, linha.cnpj)
        empresa = empresas.get(chave)
        if empresa is None:
            empresa = empresas[chave] = GrupoEmpresa(cnpj=linha.cnpj, empresa=linha.empresa)
            grupo.empresas.append(empresa)
        empresa.linhas.append(linha)
    return list(grupos.values())
