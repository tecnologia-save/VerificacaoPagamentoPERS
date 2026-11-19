"""O que uma linha produz, e o que vai para a coluna AA."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

# Número da Declaração no popup "Declaração foi enviada com sucesso"
# (ex.: 34450.37448.181126.1.3.19-4627). Vai para a coluna AB.
RX_NUMERO_DOCUMENTO = re.compile(r"\d{5}\.\d{5}\.\d{6}\.\d\.\d\.\d{2}-\d{4}")


def numero_documento(texto: str) -> str:
    """O número da Declaração contido em `texto` ("" se não há)."""
    achado = RX_NUMERO_DOCUMENTO.search(texto or "")
    return achado.group(0) if achado else ""


@dataclass
class Desfecho:
    ok: bool
    detalhe: str
    # Texto para a coluna AA. "" = não grava (a linha continua pendente).
    situacao: str = ""
    # A tela ficou num estado conhecido: a próxima linha começa direto pelo
    # "Novo Documento". False = recarrega o módulo antes.
    tela_conhecida: bool = True
    # Tributo usado quando o da coluna K estava trocado (a Receita recusou o
    # outro e este passou): a coluna K é corrigida para ele.
    tributo_corrigido: str = ""
    # Ação na tela para DEPOIS que o resultado estiver gravado (ex.: fechar no
    # "X" o aviso "A TRANSMISSÃO NÃO FOI CONCLUÍDA" — pedido do usuário,
    # 18/11/2026). Quem grava (execucao) chama.
    depois_de_gravar: Callable[[], None] | None = field(default=None, repr=False, compare=False)


class EnvioSemConfirmacao(Exception):
    """O "Enviar" foi clicado (ou pode ter sido) e o desfecho não foi confirmado.

    NÃO se sabe se a Declaração foi transmitida: a linha vai para a quarentena
    (SITUACAO_VERIFICAR) e nunca é reenviada automaticamente."""

    def __init__(self, mensagem: str, *, navegador_morto: bool = False) -> None:
        super().__init__(mensagem)
        self.navegador_morto = navegador_morto


class EnvioRecusadoPeloServidor(Exception):
    """O "Enviar" foi clicado e o PERDCOMP-WEB RECUSOU, com o documento ainda
    na tela de envio: o aviso "Não é possível prosseguir neste momento" e o
    botão "Enviar" de novo disponível, sem nenhum desfecho (linha 73,
    18/11/2026 — instabilidade do e-CAC). Não transmitiu: a linha é refeita."""


class TipoCreditoDivergente(Exception):
    """No "Prosseguir" da identificação a Receita disse que o tipo de crédito
    (PIS/COFINS) não é o do PER/DCOMP que detalha o crédito: o tributo da
    coluna K está trocado. Quem chama inverte e refaz (regra do usuário)."""


class PerdcompCancelado(Exception):
    """No "Prosseguir" da identificação a Receita disse que o documento que
    contém o detalhamento do crédito (o PER/DCOMP da coluna M) está cancelado.
    É o resultado da linha (AA "Perdcomp cancelado"), não um erro: não se
    refaz nem com o outro tributo."""


class EmpresaBloqueadaNaCaixaPostal(Exception):
    """O e-CAC manda para a Caixa Postal em vez de abrir o PER/DCOMP: a empresa
    tem mensagem IMPORTANTE não lida (AGROFEG, 18/11/2026, "Parcelamento em
    atraso"). Ler a mensagem dá ciência ao contribuinte — a automação NUNCA
    abre: a empresa é deixada para depois, sem gastar tentativas."""


class ExecucaoInterrompida(Exception):
    """A execução precisa parar (ex.: envios sem confirmação demais)."""
