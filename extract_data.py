import re
import unicodedata
import datetime
from difflib import get_close_matches
from typing import Optional, Dict, Any, List, Tuple
from parser import pdf_parser

# -----------------------
# Utilitários
# -----------------------
def normalize_text(s: Optional[str]) -> Optional[str]:
    """Remove acentos e normaliza espaços; útil para limpar nomes."""
    if not s:
        return s
    s = unicodedata.normalize('NFD', s)
    s = ''.join(ch for ch in s if unicodedata.category(ch) != 'Mn')
    s = re.sub(r'\s+', ' ', s)
    return s.strip()

def normalize_upper(s: Optional[str]) -> Optional[str]:
    return normalize_text(s).upper() if s else s

# -----------------------
# Configurações / listas
# -----------------------
COMMON_BANKS = [
    'ITAÚ UNIBANCO', 'ITAU UNIBANCO', 'ITAU', 'BANCO DO BRASIL', 'BRADESCO',
    'SANTANDER', 'CAIXA ECONOMICA FEDERAL', 'CAIXA ECONOMICA', 'CAIXA',
    'BANCO SAFRA', 'BANCO MERCANTIL', 'BANCO RURAL', 'BANCO PAN', 'BANCO INTER'
]

ROLE_LABELS = [
    'AGRAVANTE','AGRAVADO','RECORRENTE','RECORRIDO',
    'EMBARGANTE','EMBARGADO','AUTOR','REU','RÉU','INTERESSADO'
]

OUTCOME_PATTERNS = {
    'negar_provimento': [r'NEGA[MR]? PROVIMENTO', r'NEGAR PROVIMENTO', r'NEGA-SE PROVIMENTO'],
    'dar_provimento': [r'DAR PROVIMENTO', r'DE[AU] PROVIMENTO', r'PROVIDO', r'ACOLHE( O| O?A)? RECURSO'],
    'julgar_improcedente': [r'JULGAR(IM)?PROCEDENTE', r'IMPROCEDENTE'],
    'julgar_procedente': [r'JULGAR PROCEDENTE', r'PROCEDENTE'],
    'prejudicado': [r'PREJUDICAD'],
    'extinto': [r'EXTINTO', r'EXTINGUIR']
}

# -----------------------
# Extração de blocos e partes
# -----------------------
def extract_partes_block(txt: str) -> str:
    """Retorna um bloco plausível contendo as partes (entre RELATÓRIO e VOTO ou início e VOTO)."""
    m_rel = re.search(r'(RELAT[ÓO]RIO|RELATORIO)', txt, flags=re.IGNORECASE)
    m_voto = re.search(r'\bVOTO\b|\bVOTO DO RELATOR\b|\bVOTOS\b', txt, flags=re.IGNORECASE)
    if m_rel and m_voto and m_rel.start() < m_voto.start():
        return txt[m_rel.end():m_voto.start()]
    if m_voto:
        return txt[:m_voto.start()]
    return txt[:1500]

def extract_partes_from_block(block: str) -> Dict[str, str]:
    """
    Retorna dicionário plano: {ROLE: "Nome A; Nome B", ...}
    Captura rótulos do tipo 'AGRAVANTE: Nome', aceitando continuação em linhas seguintes.
    """
    partes: Dict[str, List[str]] = {}
    lines = block.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # padrão 'LABEL : NAMES' (LABEL tipicamente em maiúsculas)
        m = re.match(r'^([A-ZÀ-Ý0-9\s]{3,50})\s*[:\-–]\s*(.+)$', line)
        if m:
            label_raw = m.group(1).strip()
            name = m.group(2).strip()
            # determinar se label corresponde a um role conhecido
            matched_role = None
            label_upper = normalize_upper(label_raw)
            for r in ROLE_LABELS:
                if r in label_upper:
                    matched_role = r
                    break
            if matched_role:
                # anexar linhas seguintes que parecem continuação (não um novo rótulo)
                j = i + 1
                while j < len(lines) and lines[j].strip() and not re.match(r'^[A-ZÀ-Ý0-9\s]{3,50}\s*[:\-–]', lines[j].strip()):
                    name += ' ' + lines[j].strip()
                    j += 1
                clean_name = normalize_text(name)
                if clean_name:
                    partes.setdefault(matched_role, []).append(clean_name)
                i = j
                continue
        i += 1
    # converter listas para string única sem repetições
    partes_flat: Dict[str, str] = {}
    for role, names in partes.items():
        # normalizar nomes e remover duplicatas mantendo ordem
        seen = set()
        unique = []
        for n in names:
            n_norm = ' '.join(n.split())  # remove espaços extras
            if n_norm not in seen:
                seen.add(n_norm)
                unique.append(n_norm)
        partes_flat[role] = '; '.join(unique) if unique else None
    return partes_flat

# -----------------------
# Processo, tipo, data, estado
# -----------------------
def extract_processo_and_estado(txt: str) -> Tuple[Optional[str], Optional[str]]:
    patterns = [
        r'\bN(?:º|°|o)\s*[:.]?\s*([0-9]{4,}[0-9\.\-/]*)\s*(?:-\s*([A-Z]{2}))',
        r'\bPROCESSO\s*(?:N(?:º|o)\.?)\s*([0-9./-]+)\s*(?:-\s*([A-Z]{2}))?',
        r'\bRECURSO ESPECIAL\s*(?:N(?:º|o)\.?)\s*([0-9]+)\s*(?:-\s*([A-Z]{2}))',
        r'\bREsp\.?\s*([0-9./-]+)\b',
        r'\bProcesso:\s*([0-9./-]+)\s*(?:-\s*([A-Z]{2}))?'
    ]
    for pat in patterns:
        m = re.search(pat, txt, flags=re.IGNORECASE)
        if m:
            groups = [g for g in m.groups() if g]
            if groups:
                proc = groups[0].strip()
                estado = None
                # se houver grupo com sigla
                if len(groups) > 1 and re.fullmatch(r'[A-Z]{2}', groups[-1].strip()):
                    estado = groups[-1].strip().upper()
                else:
                    tail = txt[m.end(): m.end()+40]
                    m2 = re.search(r'-\s*([A-Z]{2})', tail)
                    if m2:
                        estado = m2.group(1)
                return proc, estado
    return None, None

def extract_tipo_processo(txt: str) -> Optional[str]:
    tipos = ['AGRAVO EM RECURSO ESPECIAL','RECURSO ESPECIAL','AGRAVO INTERNO','AGRAVO DE INSTRUMENTO','EMBARGOS DE DECLARAÇÃO']
    for t in tipos:
        if re.search(r'\b' + re.escape(t) + r'\b', txt, flags=re.IGNORECASE):
            return t
    # fallback: tentar primeiro cabeçalho
    first_line = txt.splitlines()[0] if txt.splitlines() else ''
    m = re.match(r'^(.*?)\s+N(?:º|o|°)\b', first_line, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None

def extract_data_julgamento(txt: str) -> Optional[str]:
    """
    Extrai a data de julgamento e retorna no formato DD/MM/YYYY.
    Aceita padrões como:
      - 'Brasília, 28 de agosto de 2023'
      - 'JULGADO: 28/08/2023'
      - '28/08/2023'
    """
    meses = {
        "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
        "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
        "outubro": 10, "novembro": 11, "dezembro": 12
    }

    # padrão textual: 'Brasília, 28 de agosto de 2023'
    m_texto = re.search(
        r'(\d{1,2})\s+de\s+([a-zçãéíóú]+)\s+de\s+(\d{4})', txt, flags=re.IGNORECASE
    )
    if m_texto:
        dia = int(m_texto.group(1))
        mes_nome = m_texto.group(2).lower()
        ano = int(m_texto.group(3))
        mes = meses.get(mes_nome)
        if mes:
            try:
                return datetime.date(ano, mes, dia).strftime("%d/%m/%Y")
            except ValueError:
                pass

    # padrão numérico: JULGADO: 28/08/2023 ou PAUTA: dd/mm/yyyy JULGADO: dd/mm/yyyy
    m_num = re.search(r'(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})', txt)
    if m_num:
        dia, mes, ano = map(int, m_num.groups())
        try:
            return datetime.date(ano, mes, dia).strftime("%d/%m/%Y")
        except ValueError:
            pass

    return None

# -----------------------
# Banco detection
# -----------------------
def detect_bank(txt: str) -> Optional[str]:
    txt_n = normalize_upper(txt)
    for b in COMMON_BANKS:
        if b.upper() in txt_n:
            return b
    m = re.search(r'\bBANCO\s+([A-ZÀ-Ý0-9\.\-\/\s,&]{2,80}?)\b', txt, flags=re.IGNORECASE)
    if m:
        cand = m.group(0).strip()
        cand = re.sub(r'\s{2,}', ' ', cand)
        return normalize_text(cand)
    m2 = re.search(r'([A-Z][A-Z\s\.\-,&]{3,80}S\.A\.?)', txt, flags=re.IGNORECASE)
    if m2:
        cand = normalize_text(m2.group(1))
        matches = get_close_matches(cand.upper(), [b.upper() for b in COMMON_BANKS], n=1, cutoff=0.7)
        if matches:
            # title-case match
            return matches[0].title()
        return cand
    return None

# -----------------------
# Texto do voto & dispositivo
# -----------------------
# def extract_texto_voto(txt: str) -> Optional[str]:
#     patterns = [
#         r'\bVOTO\b\s*(.+?)(?:\n\s*\bACÓRD[AÃ]O\b|\n\s*\bACORD[AÃ]O\b|\n\s*\bACORDAM\b|\n\s*\bDISPOSITIVO\b|\n\s*\bRELAT[ÓO]RIO\b)',
#         r'\bVOTO DO RELATOR\b\s*(.+?)(?:\n\s*\bACORDAM\b|\n\s*\bDISPOSITIVO\b|\n\s*\Z)'
#     ]
#     for p in patterns:
#         m = re.search(p, txt, flags=re.IGNORECASE | re.DOTALL)
#         if m:
#             voto = m.group(1).strip()
#             voto = re.sub(r'\n{2,}', '\n\n', voto)
#             return voto
#     # fallback: trecho anterior ao dispositivo
#     m2 = re.search(r'(.{1200})(ACORDAM|DISPOSITIVO|ACÓRDÃO|ACORDAO)', txt, flags=re.IGNORECASE | re.DOTALL)
#     if m2:
#         voto = m2.group(1).strip()
#         return voto
#     return None

def extract_dispositivo(txt: str) -> Optional[str]:
    m = re.search(r'\bACORDAM\b(.{0,2000})', txt, flags=re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(0).strip()
    m2 = re.search(r'\bDISPOSITIVO\b(.{0,2000})', txt, flags=re.IGNORECASE | re.DOTALL)
    if m2:
        return m2.group(0).strip()
    tail = txt[-1200:].strip()
    return tail if tail else None

# -----------------------
# Inferir decisão p/ banco (heurística)
# -----------------------
def infer_decision_for_bank(dispositivo: Optional[str], partes: Dict[str, str], banco_name: Optional[str]) -> Optional[str]:
    if not dispositivo:
        return None
    dnorm = normalize_upper(dispositivo)
    matched_key = None
    for key, pats in OUTCOME_PATTERNS.items():
        for pat in pats:
            if re.search(pat, dnorm, flags=re.IGNORECASE):
                matched_key = key
                break
        if matched_key:
            break
    # identificar papel do banco nas partes
    bank_roles = []
    if banco_name and partes:
        bn_token = normalize_upper(banco_name.split()[0])
        for role, names_str in partes.items():
            if not names_str:
                continue
            # checar se qualquer nome da string contém token do banco
            for nm in [n.strip() for n in names_str.split(';')]:
                if bn_token in normalize_upper(nm) or normalize_upper(banco_name) in normalize_upper(nm):
                    bank_roles.append(role)
    # heurística simples combinando matched_key e papel
    if matched_key:
        if matched_key in ('negar_provimento','julgar_improcedente','prejudicado','extinto'):
            if any(r in bank_roles for r in ['AGRAVANTE','RECORRENTE','EMBARGANTE']):
                return 'contraria'
            if any(r in bank_roles for r in ['AGRAVADO','RECORRIDO','EMBARGADO']):
                return 'favoravel'
            return 'indeterminado'
        if matched_key in ('dar_provimento','julgar_procedente'):
            if any(r in bank_roles for r in ['AGRAVANTE','RECORRENTE','EMBARGANTE']):
                return 'favoravel'
            if any(r in bank_roles for r in ['AGRAVADO','RECORRIDO','EMBARGADO']):
                return 'contraria'
            return 'indeterminado'
    # fallback: procurar "nega provimento a (recurso de) BANCO" ou similar
    if banco_name:
        bn_simple = normalize_upper(banco_name.split()[0])
        if re.search(r'NEGA.*PROVIMENTO.*' + re.escape(bn_simple), normalize_upper(dispositivo), flags=re.IGNORECASE):
            return 'contraria'
        if re.search(r'DAR PROVIMENTO.*' + re.escape(bn_simple), normalize_upper(dispositivo), flags=re.IGNORECASE):
            return 'favoravel'
    return 'indeterminado'

# -----------------------
# Função principal (simples / sem confidências)
# -----------------------
def extract_acordao_data(text: str) -> Dict[str, Any]:
    """
    Versão simplificada: retorna dicionário plano com chaves:
      processo, tipo_processo, data_julgamento, estado,
      AGRAVANTE, AGRAVADO, RECORRENTE, RECORRIDO, EMBARGANTE, EMBARGADO, AUTOR, REU, INTERESSADO,
      banco, texto_voto, dispositivo, decisao_para_banco
    Valores: strings ou None. Partes armazenadas em strings únicas separadas por '; ' sem repetição.
    """
    # inicializar resultado com chaves previstas (partes como None por padrão)
    result: Dict[str, Any] = {
        "processo": None,
        "tipo_processo": None,
        "data_julgamento": None,
        "estado": None,
        # predefinir rótulos de partes (serão preenchidos se encontradas)
        "AGRAVANTE": None,
        "AGRAVADO": None,
        "RECORRENTE": None,
        "RECORRIDO": None,
        "EMBARGANTE": None,
        "EMBARGADO": None,
        "AUTOR": None,
        "REU": None,
        "INTERESSADO": None,
        "banco": None,
        # "texto_voto": None,
        # "dispositivo": None,
        "decisao_para_banco": None
    }

    if not text or not text.strip():
        return result

    txt = text

    # processo & estado
    proc, est = extract_processo_and_estado(txt)
    if proc:
        result["processo"] = proc
    if est:
        result["estado"] = est

    # tipo processo
    tipo = extract_tipo_processo(txt)
    if tipo:
        result["tipo_processo"] = tipo

    # data julgamento
    data = extract_data_julgamento(txt)
    if data:
        result["data_julgamento"] = data

    # partes
    block = extract_partes_block(txt)
    partes_flat = extract_partes_from_block(block)
    # popular result para cada role previsto
    for role in ["AGRAVANTE","AGRAVADO","RECORRENTE","RECORRIDO","EMBARGANTE","EMBARGADO","AUTOR","REU","INTERESSADO"]:
        if role in partes_flat:
            result[role] = partes_flat[role]

    # banco
    banco = detect_bank(txt)
    if banco:
        result["banco"] = banco

    # texto do voto
    # voto = extract_texto_voto(txt)
    # if voto:
    #     result["texto_voto"] = voto

    # dispositivo
    dispositivo = extract_dispositivo(txt)
    # if dispositivo:
    #     result["dispositivo"] = dispositivo

    # decisao p/ banco (heurística)
    decisao = infer_decision_for_bank(dispositivo, {k:v for k,v in result.items() if k in ROLE_LABELS}, banco)
    result["decisao_para_banco"] = decisao

    return result

# -----------------------
# Exemplo de uso:
# -----------------------
# texto = open('acordao.txt','r',encoding='utf-8').read()
# vals = extract_acordao_fields_simple(texto)
# print(vals)

# text = pdf_parser('./data/itau/AAGARESP-2279744-2023-08-30.pdf')
# data = extract_acordao_data(text)
# print(data)