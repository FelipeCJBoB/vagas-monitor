"""Mapa do que o mercado cobra: presencial na região x remoto nacional.

A pergunta que este módulo responde não é "quais tecnologias aparecem nas vagas",
que qualquer contagem responde, e sim **o que estudar primeiro**. Para isso são
precisos três recortes que uma contagem simples não dá:

1. **Separar os dois mercados.** As vagas presenciais da região e as remotas
   nacionais não são o mesmo mercado com endereços diferentes: são indústria
   catarinense e empresa de tecnologia, que cobram coisas distintas. Misturar as
   duas produz uma lista média que não descreve nenhuma das duas.

2. **Descontar o que já se sabe.** Uma habilidade muito pedida que o candidato já
   domina não é prioridade de estudo. O campo `tenho` do `skills.yaml` é o que
   transforma "o mercado pede SQL" em "não perca tempo, você já tem".

3. **Restringir ao que é alcançável.** Kubernetes aparecer em vaga sênior não
   informa nada sobre a próxima candidatura de um júnior. O recorte de
   senioridade separa demanda real de demanda aspiracional.

Ressalva honesta sobre o método: a comparação entre os dois segmentos mistura
duas causas. As vagas remotas vêm de empresas de tecnologia e tendem a ser mais
sêniores; parte da diferença observada é o tipo de empresa, não o regime de
trabalho. Por isso o relatório informa o tamanho da amostra e a cobertura de
descrições ao lado de cada percentual, e o corte por senioridade é aplicado
sempre que sobra amostra.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

import yaml

from .models import Job
from .text import any_term, normalize

log = logging.getLogger("vagas.skills")

PESO_LACUNA = {"nao": 1.0, "parcial": 0.5, "sim": 0.0}
SENIORIDADE_ALCANCAVEL = {"junior", "pleno", "unknown"}

# Abaixo disto o percentual do segmento não é informação: com 4 vagas, uma única
# menção vira "25% do mercado". O segmento continua sendo contado e exibido em
# número absoluto, mas não pode sustentar a afirmação de que algo "pesa mais aqui".
MIN_SEGMENTO = 10


def load_taxonomy(root: Path, nome: str = "skills.yaml") -> dict:
    p = Path(root) / nome
    if not p.exists():
        log.warning("%s não encontrado; o mapa de mercado será omitido", nome)
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def extract(text: str, taxonomia: dict) -> list[str]:
    """Chaves das habilidades citadas no texto, na ordem da taxonomia."""
    hay = normalize(text)
    if not hay:
        return []
    return [k for k, v in (taxonomia.get("habilidades") or {}).items()
            if any_term(hay, v.get("termos", []))]


def annotate_jobs(jobs: Iterable[Job], taxonomia: dict) -> int:
    """Grava `job.skills` a partir da descrição COMPLETA.

    Roda no pipeline, e não no relatório, porque o JSON guarda a descrição
    truncada: extrair depois perderia tudo que aparece a partir do 1200º caractere,
    justamente onde costuma ficar a lista de requisitos.
    """
    com_descricao = 0
    for j in jobs:
        if not j.description:
            j.skills = []
            continue
        com_descricao += 1
        j.skills = extract(f"{j.title}\n{j.description}", taxonomia)
    return com_descricao


def _segmento(j: dict) -> str | None:
    if j.get("matched_city"):
        return "regional"
    if j.get("workplace") == "remote":
        return "remoto"
    return None


def analyze(jobs: list[dict], taxonomia: dict) -> dict:
    """Compara a frequência de cada habilidade nos dois mercados.

    Recebe dicionários (o contexto do relatório), não objetos Job, para que o
    comando `render` consiga refazer a análise a partir de um JSON gravado.
    """
    habs = (taxonomia or {}).get("habilidades") or {}
    if not habs:
        return {}
    min_ocorr = int((taxonomia or {}).get("min_ocorrencias", 4))

    # só vagas com descrição entram na base: as demais não têm o que medir, e
    # incluí-las no denominador faria toda habilidade parecer mais rara
    base = {"regional": [], "remoto": []}
    total_por_segmento = {"regional": 0, "remoto": 0}
    for j in jobs:
        seg = _segmento(j)
        if not seg:
            continue
        total_por_segmento[seg] += 1
        if j.get("skills") is not None and j.get("description"):
            base[seg].append(j)

    n_reg, n_rem = len(base["regional"]), len(base["remoto"])
    acessiveis = [j for seg in base.values() for j in seg
                  if j.get("seniority") in SENIORIDADE_ALCANCAVEL]

    linhas = []
    for chave, meta in habs.items():
        c_reg = sum(1 for j in base["regional"] if chave in (j.get("skills") or []))
        c_rem = sum(1 for j in base["remoto"] if chave in (j.get("skills") or []))
        if c_reg + c_rem < min_ocorr:
            continue
        p_reg = 100 * c_reg / n_reg if n_reg else 0.0
        p_rem = 100 * c_rem / n_rem if n_rem else 0.0
        c_ace = sum(1 for j in acessiveis if chave in (j.get("skills") or []))
        p_ace = 100 * c_ace / len(acessiveis) if acessiveis else 0.0
        tenho = (meta.get("tenho") or "nao").lower()

        # a prioridade responde "estudar isto muda quantas candidaturas?":
        # frequência entre as vagas que ele pode pegar, descontado o que já sabe
        prioridade = round(p_ace * PESO_LACUNA.get(tenho, 1.0), 1)

        comparavel = n_reg >= MIN_SEGMENTO and n_rem >= MIN_SEGMENTO
        if not comparavel:
            onde = "indeterminado"
        elif p_reg >= 2 * p_rem and c_reg >= 3:
            onde = "presencial"
        elif p_rem >= 2 * p_reg and c_rem >= 3:
            onde = "remoto"
        else:
            onde = "ambos"

        linhas.append({
            "chave": chave, "nome": meta.get("nome", chave), "grupo": meta.get("grupo", "Outros"),
            "tenho": tenho, "n_regional": c_reg, "n_remoto": c_rem,
            "pct_regional": round(p_reg, 1), "pct_remoto": round(p_rem, 1),
            "pct_acessivel": round(p_ace, 1), "onde": onde, "prioridade": prioridade,
        })

    linhas.sort(key=lambda r: (-r["prioridade"], -r["pct_acessivel"]))
    return {
        "linhas": linhas,
        "grupos": _por_grupo(habs, acessiveis, base),
        "amostra": {
            "regional": n_reg, "remoto": n_rem,
            "regional_total": total_por_segmento["regional"],
            "remoto_total": total_por_segmento["remoto"],
            "acessiveis": len(acessiveis),
            "cobertura_pct": round(
                100 * (n_reg + n_rem) / max(1, sum(total_por_segmento.values())), 1),
            # só com os dois lados povoados a coluna "onde pesa" significa algo
            "comparavel": n_reg >= MIN_SEGMENTO and n_rem >= MIN_SEGMENTO,
            "min_segmento": MIN_SEGMENTO,
        },
        "min_ocorrencias": min_ocorr,
    }


def _por_grupo(habs: dict, acessiveis: list[dict], base: dict) -> list[dict]:
    """Agrega por família de tecnologia.

    Linha a linha, AWS, Azure e Google Cloud disputam entre si e cada uma parece
    modesta. São a mesma lacuna: quem não sabe nuvem não sabe nenhuma das três, e
    quem aprende uma transfere a maior parte para as outras. Sem esta agregação a
    prioridade de estudo aponta para o lugar errado.
    """
    grupos: dict[str, dict] = {}
    for chave, meta in habs.items():
        g = grupos.setdefault(meta.get("grupo", "Outros"),
                              {"grupo": meta.get("grupo", "Outros"), "chaves": [], "faltam": []})
        g["chaves"].append(chave)
        if PESO_LACUNA.get((meta.get("tenho") or "nao").lower(), 1.0) > 0:
            g["faltam"].append(meta.get("nome", chave))

    out = []
    n_ace = len(acessiveis)
    for g in grupos.values():
        chaves = set(g["chaves"])
        # uma vaga conta uma vez pelo grupo, mesmo citando três tecnologias dele
        c_ace = sum(1 for j in acessiveis if chaves & set(j.get("skills") or []))
        if not c_ace:
            continue
        c_reg = sum(1 for j in base["regional"] if chaves & set(j.get("skills") or []))
        c_rem = sum(1 for j in base["remoto"] if chaves & set(j.get("skills") or []))
        n_reg, n_rem = len(base["regional"]), len(base["remoto"])
        out.append({
            "grupo": g["grupo"],
            "pct_acessivel": round(100 * c_ace / n_ace, 1) if n_ace else 0.0,
            "pct_regional": round(100 * c_reg / n_reg, 1) if n_reg else 0.0,
            "pct_remoto": round(100 * c_rem / n_rem, 1) if n_rem else 0.0,
            "faltam": g["faltam"],
            "dominado": not g["faltam"],
        })
    out.sort(key=lambda r: -r["pct_acessivel"])
    return out


def prioridades(mercado: dict, limite: int = 8) -> list[dict]:
    """As habilidades que faltam, em ordem de quanto destravam candidaturas."""
    return [r for r in (mercado.get("linhas") or []) if r["prioridade"] > 0][:limite]
