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
        "grupos": _por_grupo(habs, acessiveis, base, linhas),
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


def _por_grupo(habs: dict, acessiveis: list[dict], base: dict, linhas: list[dict]) -> list[dict]:
    """Agrega por família de tecnologia.

    Linha a linha, AWS, Azure e Google Cloud disputam entre si e cada uma parece
    modesta. São a mesma lacuna: quem não sabe nuvem não sabe nenhuma das três, e
    quem aprende uma transfere a maior parte para as outras. Sem esta agregação a
    prioridade de estudo aponta para o lugar errado.

    A família é o contexto; o que se estuda é a tecnologia. Por isso cada família
    devolve também `faltam_detalhe` e `tem_detalhe`, com o nome e a fatia de vagas
    de cada item, ordenados do mais cobrado para o menos. É isso que o relatório
    mostra como título, e não o nome abstrato da família.

    Só entram itens que de fato apareceram nas vagas (os de `linhas`, que já
    passaram por `min_ocorrencias`). Antes, a lista de lacunas vinha da taxonomia
    inteira e mostrava "falta: R, PHP" para tecnologias que nenhuma vaga pediu.
    """
    por_nome = {r["chave"]: r for r in linhas}
    grupos: dict[str, dict] = {}
    for chave, meta in habs.items():
        g = grupos.setdefault(meta.get("grupo", "Outros"), {"grupo": meta.get("grupo", "Outros"), "chaves": []})
        g["chaves"].append(chave)

    out = []
    n_ace = len(acessiveis)
    n_reg, n_rem = len(base["regional"]), len(base["remoto"])
    for g in grupos.values():
        chaves = set(g["chaves"])
        # uma vaga conta uma vez pelo grupo, mesmo citando três tecnologias dele
        c_ace = sum(1 for j in acessiveis if chaves & set(j.get("skills") or []))
        if not c_ace:
            continue
        c_reg = sum(1 for j in base["regional"] if chaves & set(j.get("skills") or []))
        c_rem = sum(1 for j in base["remoto"] if chaves & set(j.get("skills") or []))

        itens = sorted((por_nome[k] for k in g["chaves"] if k in por_nome),
                       key=lambda r: -r["pct_acessivel"])
        detalhe = lambda r: {"nome": r["nome"], "pct": r["pct_acessivel"], "onde": r["onde"]}
        faltam = [detalhe(r) for r in itens if PESO_LACUNA.get(r["tenho"], 1.0) > 0]
        tem = [detalhe(r) for r in itens if PESO_LACUNA.get(r["tenho"], 1.0) == 0]

        # Fatia das vagas acessíveis que pedem ALGO desta família que ele não tem.
        # É a ordem certa para estudar: a presença total da família engana, porque
        # "Linguagem" aparece em 59% das vagas quase só por causa do Python, que
        # ele já domina. O que interessa é quanto destrava fechar a lacuna.
        faltando = {k for k in g["chaves"]
                    if PESO_LACUNA.get((habs[k].get("tenho") or "nao").lower(), 1.0) > 0}
        pede_lacuna = lambda j: bool(faltando & set(j.get("skills") or []))
        c_lac = sum(1 for j in acessiveis if pede_lacuna(j))
        # A mesma lacuna, separada por mercado. Comparar remoto x região sobre a
        # presença total da família seria enganoso pelo mesmo motivo: "Linguagem"
        # cresce muito no remoto, mas quem cresce é o Python, que ele já tem.
        c_lac_reg = sum(1 for j in base["regional"] if pede_lacuna(j))
        c_lac_rem = sum(1 for j in base["remoto"] if pede_lacuna(j))

        out.append({
            "grupo": g["grupo"],
            "pct_lacuna": round(100 * c_lac / n_ace, 1) if n_ace else 0.0,
            "lacuna_regional": round(100 * c_lac_reg / n_reg, 1) if n_reg else 0.0,
            "lacuna_remoto": round(100 * c_lac_rem / n_rem, 1) if n_rem else 0.0,
            # contagens absolutas: 29% de 24 vagas não pesa o mesmo que 29% de 166
            "n_lacuna_regional": c_lac_reg, "n_lacuna_remoto": c_lac_rem,
            "pct_acessivel": round(100 * c_ace / n_ace, 1) if n_ace else 0.0,
            "pct_regional": round(100 * c_reg / n_reg, 1) if n_reg else 0.0,
            "pct_remoto": round(100 * c_rem / n_rem, 1) if n_rem else 0.0,
            "n_regional": c_reg, "n_remoto": c_rem,
            "faltam_detalhe": faltam,
            "tem_detalhe": tem,
            "faltam": [f["nome"] for f in faltam],  # mantido para quem só quer os nomes
            "dominado": not faltam,
        })
    out.sort(key=lambda r: (-r["pct_lacuna"], -r["pct_acessivel"]))
    return out


def veredito(mercado: dict, n_itens: int = 3) -> dict:
    """As duas conclusões que respondem "o que estudar", como dado e não como texto.

    Painel, Markdown e Telegram renderizam a partir daqui, então dizem a mesma
    coisa. E cada conclusão nomeia as TECNOLOGIAS, não a família: "CI/CD, Azure,
    AWS" é acionável; "Nuvem" não é.

    - `forte`: o que ele já domina e o mercado pede, mais cobrado primeiro.
    - `pedagio`: a família com a maior distância entre remoto e região onde ainda
      há lacuna, com as tecnologias que faltam. Só existe se a amostra permitir
      comparar os dois mercados.
    """
    linhas, grupos = mercado.get("linhas") or [], mercado.get("grupos") or []
    am = mercado.get("amostra") or {}
    comparavel = am.get("comparavel", False)
    item = lambda r: {"nome": r["nome"], "pct": r["pct_acessivel"]}

    forte = [item(r) for r in sorted((r for r in linhas if r["tenho"] == "sim"),
                                    key=lambda r: -r["pct_acessivel"])][:n_itens + 1]
    casa = None
    if comparavel:
        candidatas = [g for g in grupos if g["tem_detalhe"] and g["pct_regional"] > g["pct_remoto"]]
        casa = max(candidatas, key=lambda g: g["pct_regional"] - g["pct_remoto"], default=None)

    pedagio = None
    if comparavel:
        # compara a LACUNA entre os mercados, não a presença da família inteira
        com_lacuna = [g for g in grupos if g["faltam_detalhe"]
                      and g["lacuna_remoto"] > 1.5 * max(g["lacuna_regional"], 1)]
        alvo = max(com_lacuna, key=lambda g: g["lacuna_remoto"] - g["lacuna_regional"], default=None)
        if alvo:
            pedagio = {"grupo": alvo["grupo"], "itens": alvo["faltam_detalhe"][:n_itens],
                       "pct_regional": alvo["lacuna_regional"], "pct_remoto": alvo["lacuna_remoto"],
                       "pct_lacuna": alvo["pct_lacuna"]}

    return {
        "forte": {"itens": forte,
                  "casa": ({"grupo": casa["grupo"], "pct_regional": casa["pct_regional"],
                            "pct_remoto": casa["pct_remoto"],
                            "itens": casa["tem_detalhe"][:n_itens]} if casa else None)},
        "pedagio": pedagio,
        "comparavel": comparavel,
    }


def prioridades(mercado: dict, limite: int = 8) -> list[dict]:
    """As habilidades que faltam, em ordem de quanto destravam candidaturas."""
    return [r for r in (mercado.get("linhas") or []) if r["prioridade"] > 0][:limite]
