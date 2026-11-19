"""Faz o login no e-CAC UMA vez e mantém o Chrome aberto e logado.

As execuções com `--navegador-aberto` se conectam a ESTE Chrome (porta de
depuração 9222, aberta pelo ecac_login), trocam o perfil da empresa e, no fim,
só se desconectam: não saem do e-CAC nem fecham o navegador. Assim o login não
é refeito a cada execução (captcha, vaga de dispositivo do certificado).

Uso (deixe esta janela de terminal aberta):
    python manter_navegador.py --certificado SAVE --cnpj 07581518000105

Ctrl+C: sai com segurança do e-CAC e fecha o navegador.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from VerificacaoPagamento.certificados import (  # noqa: E402
    carregar_certificado,
    ler_senhas,
    listar_pfx,
    resolver_nome,
)
from VerificacaoPagamento.sessao import abrir_sessao, cnpj_do_perfil_ativo  # noqa: E402

ARQUIVO_ESTADO = ROOT / "navegador_aberto.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--certificado", required=True, help="procurador (coluna B), ex.: SAVE")
    parser.add_argument("--cnpj", required=True, help="CNPJ do primeiro perfil (14 dígitos)")
    argumentos = parser.parse_args()

    caminho = resolver_nome(argumentos.certificado, listar_pfx())
    if caminho is None:
        sys.exit(f"Nenhum .pfx corresponde a '{argumentos.certificado}'.")
    certificado = carregar_certificado(caminho, ler_senhas())
    cnpj = "".join(c for c in argumentos.cnpj if c.isdigit()).zfill(14)

    try:
        from ecac_login import dir_perfil_chrome
        perfil = dir_perfil_chrome(ROOT)
    except ImportError:
        perfil = None
    sessao = abrir_sessao(certificado, cnpj, project_dir=ROOT, perfil_dir=perfil)
    # As execuções com --navegador-aberto leem daqui com que certificado ele
    # está logado, e só processam as empresas desse certificado.
    ARQUIVO_ESTADO.write_text(json.dumps({"certificado": certificado.nome}, ensure_ascii=False),
                              encoding="utf-8")
    print("=" * 60)
    print(f"NAVEGADOR ABERTO E LOGADO — certificado '{certificado.nome}', perfil "
          f"{cnpj_do_perfil_ativo(sessao.page) or cnpj}")
    print("Rode as execucoes com --navegador-aberto. Ctrl+C aqui encerra o navegador.")
    print("=" * 60)
    try:
        while True:
            time.sleep(30)
    except KeyboardInterrupt:
        print("\nEncerrando: Sair com Seguranca e fechando o navegador...")
    finally:
        ARQUIVO_ESTADO.unlink(missing_ok=True)
        sessao.encerrar()


if __name__ == "__main__":
    main()
