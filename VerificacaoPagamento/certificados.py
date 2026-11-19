"""Procurador (coluna B) -> certificado .pfx em C:\\Certificados.

Mesmo mecanismo do VerificaMensagensPagamento (desktop): o .pfx é entregue ao
Chrome pelo `ecac_login` (`cert_pfx_path` + `cert_pfx_passphrase`, via
`client_certificates`) — sem Windows Certificate Store, sem UAC, sem policy de
registro. É o que permite usar VÁRIOS certificados na mesma execução.

DIFERENÇA DELIBERADA em relação ao VerificaMensagensPagamento: lá o nome da
planilha casa com o .pfx por SEMELHANÇA (score >= 0.40). Aqui o casamento é
EXATO depois de normalizar, mais a tabela de apelidos de `config`. "SAVE" é
parecido com "Save Inteligência" E com "Save Tecnologia"; escolher por
semelhança é entrar no e-CAC como o procurador errado.

A pasta C:\\Certificados é de outras automações também: aqui ela só é LIDA.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import APELIDOS_CERTIFICADO, ARQUIVO_SENHAS, PASTA_CERTIFICADOS
from .planilha import normalizar_texto


class CertificadoIndisponivel(Exception):
    """O certificado não pode ser usado. A mensagem é para o operador."""


@dataclass(frozen=True)
class Certificado:
    nome: str          # nome do .pfx sem extensão (ex.: "Save Inteligência")
    caminho: Path
    senha: str


def listar_pfx(pasta: Path = PASTA_CERTIFICADOS) -> dict[str, Path]:
    """{nome normalizado do .pfx: caminho}."""
    if not pasta.is_dir():
        return {}
    return {normalizar_texto(p.stem): p for p in pasta.glob("*.pfx")}


def resolver_nome(procurador: str, pfx_disponiveis: dict[str, Path],
                  apelidos: dict[str, str] = APELIDOS_CERTIFICADO) -> Path | None:
    """O .pfx do procurador, ou None. Nunca adivinha.

    1. apelido conhecido (config.APELIDOS_CERTIFICADO) -> o .pfx que ele aponta;
    2. senão, o .pfx cujo nome é IGUAL ao procurador (normalizado).
    """
    chave = normalizar_texto(procurador)
    if not chave:
        return None
    apelidos_norm = {normalizar_texto(k): normalizar_texto(v) for k, v in apelidos.items()}
    alvo = apelidos_norm.get(chave, chave)
    return pfx_disponiveis.get(alvo)


def ler_senhas(arquivo: Path = ARQUIVO_SENHAS) -> dict[str, str]:
    """{nome normalizado do arquivo .pfx: senha}. Normalizado porque o
    senhas.json real tem 'Yury.pfx' para o arquivo 'YURY.pfx'."""
    if not arquivo.is_file():
        raise CertificadoIndisponivel(f"{arquivo} não existe — crie com as senhas dos .pfx.")
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 — vira mensagem para o operador
        raise CertificadoIndisponivel(f"{arquivo} não pôde ser lido ({type(e).__name__}).") from None
    if not isinstance(dados, dict):
        raise CertificadoIndisponivel(f"{arquivo} deveria ser um objeto {{arquivo: senha}}.")
    return {normalizar_texto(Path(str(k)).stem): str(v or "") for k, v in dados.items()}


def conferir_senha(caminho: Path, senha: str) -> None:
    """Abre o .pfx com a senha ANTES de abrir o navegador.

    Visto no VerificaMensagensPagamento (14/10/2026): com a senha errada o
    Chrome nem abre, e o Playwright fica preso dentro do `ecac_login`,
    derrubando todos os logins seguintes. Conferir aqui custa milissegundos.
    (O PKCS#12 no formato antigo — RC2/3DES — é reempacotado pelo próprio
    `ecac_login` desde a versão com `_pkcs12_moderno`.)
    """
    from cryptography.hazmat.primitives.serialization import pkcs12

    try:
        pkcs12.load_key_and_certificates(caminho.read_bytes(), senha.encode() if senha else None)
    except Exception:  # noqa: BLE001 — senha errada ou arquivo corrompido: mesma ação
        raise CertificadoIndisponivel(
            f"a senha de {ARQUIVO_SENHAS.name} não abre {caminho.name} "
            "(ou o arquivo está corrompido)"
        ) from None


def carregar_certificado(caminho: Path, senhas: dict[str, str]) -> Certificado:
    senha = senhas.get(normalizar_texto(caminho.stem), "")
    if not senha:
        raise CertificadoIndisponivel(f"sem senha para {caminho.name} em {ARQUIVO_SENHAS}")
    conferir_senha(caminho, senha)
    return Certificado(nome=caminho.stem, caminho=caminho, senha=senha)
