#!/usr/bin/env python3
"""GitHub Actions: audita mudanças do upstream antes de sincronizar um fork.

Não executa scripts recebidos nem trata o conteúdo jurídico como instruções.
A validação é heurística e NÃO certifica integralidade ou vigência normativa.
"""
import base64
import datetime as dt
import hashlib
import html
from html.parser import HTMLParser
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

SOURCE = 'ctresb/leis'
STATE_PATH = 'automation/monitor_state.json'
MAX_FILES = 60
TIMEOUT = 20


def api(path, token, method='GET', payload=None):
    req = urllib.request.Request(
        'https://api.github.com' + path, method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Accept': 'application/vnd.github+json',
                 'X-GitHub-Api-Version': '2022-11-28',
                 'Authorization': 'Bearer ' + token,
                 'User-Agent': 'legislacao-fork-watch/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            raw = response.read(8_000_000)
        return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read(300).decode(errors='replace')
        raise RuntimeError(f'GitHub {method} {path}: HTTP {exc.code} {detail}') from exc


def read_file(repo, path, ref, token, max_bytes=2_000_000):
    encoded = urllib.parse.quote(path, safe='/')
    item = api(f'/repos/{repo}/contents/{encoded}?ref={ref}', token)
    if item.get('type') != 'file' or item.get('encoding') != 'base64':
        raise ValueError('arquivo não textual, não suportado ou muito grande')
    data = base64.b64decode(item.get('content', ''))
    if not data or len(data) > max_bytes:
        raise ValueError('arquivo vazio ou excede o limite da auditoria')
    return data.decode('utf-8'), item['sha']


def inspect_text(path, content, previous=None):
    problems = []
    if previous is not None and len(previous) > 1000 and len(content) < len(previous) * .65:
        problems.append('redução súbita superior a 35%')
    suspicious = [r'ignore (?:all )?(?:previous|prior) instructions',
                  r'(?:system|developer) prompt',
                  r'desconsidere (?:todas )?as instru[çc][õo]es anteriores',
                  r'execute (?:this|the following) command',
                  r'<\|(?:im_start|system|developer)\|>']
    if any(re.search(pattern, content, re.I) for pattern in suspicious):
        problems.append('possível prompt injection; requer revisão humana')
    if path.startswith(('federal/leis-ordinarias/', 'federal/leis-complementares/')):
        m = re.match(r'\A---\s*\n(.*?)\n---\s*\n', content, re.S)
        if not m:
            problems.append('cabeçalho de metadados ausente')
        else:
            header = m.group(1)
            for field in ('titulo', 'tipo', 'numero', 'data', 'versao_texto', 'fonte', 'baixado_em'):
                if not re.search(rf'(?m)^{field}:\s*\S', header):
                    problems.append('metadado faltante: ' + field)
            if not re.search(r'(?m)^fonte:\s*[\x27\"]?https://', header):
                problems.append('fonte não indicada com HTTPS')
            if re.search(r'versao_texto:\s*[\x27\"]?republica[çc][ãa]o/retifica[çc][ãa]o', header, re.I):
                problems.append('apenas republicação/retificação: verificar integralidade')
        if not re.search(r'\bArt\.?\s*1\s*[º°o.]|\bArtigo\s+[úu]nico', content, re.I):
            problems.append('possível lei incompleta: não identificado art. 1º')
        if len(content) < 400:
            problems.append('texto excepcionalmente curto')
    return problems


def inspect_changes(base, target, token):
    data = api(f'/repos/{SOURCE}/compare/{base}...{target}?per_page=100', token)
    if data.get('status') == 'identical':
        return [], 0
    if data.get('status') != 'ahead':
        return ['histórico do projeto de origem divergiu'], 0
    files = data.get('files', [])
    if data.get('ahead_by', 0) > 250 or len(files) > MAX_FILES or len(files) >= 300:
        return [f'lote acima do limite de auditoria: {len(files)} arquivos listados'], len(files)
    problems = []
    for item in files:
        path, status = item.get('filename', ''), item.get('status', '')
        if not path or '..' in path.split('/') or '\\' in path:
            problems.append('caminho suspeito: ' + path)
        elif status not in ('added', 'modified'):
            problems.append('remoção/renomeação pendente de revisão: ' + path)
        elif not path.endswith('.md') or path.startswith(('.github/', 'automation/', 'scripts/', '.githooks/')):
            problems.append('código, executável ou arquivo não Markdown modificado: ' + path)
        else:
            try:
                current, _ = read_file(SOURCE, path, target, token)
                older = read_file(SOURCE, path, base, token)[0] if status == 'modified' else None
                problems.extend(f'{path}: {x}' for x in inspect_text(path, current, older))
            except Exception as exc:
                problems.append(f'{path}: validação falhou: {exc}')
        if len(problems) >= 30:
            problems.append('alertas adicionais omitidos')
            break
    return problems, len(files)


def fork_ancestor(repo, token):
    commit = api(f'/repos/{repo}/commits/main', token)
    for _ in range(30):
        sha = commit.get('sha', '')
        if not re.fullmatch(r'[a-f0-9]{40}', sha):
            raise ValueError('SHA de commit inválido')
        try:
            api(f'/repos/{SOURCE}/commits/{sha}', token)
            return sha
        except RuntimeError as exc:
            if 'HTTP 404' not in str(exc):
                raise
        parent = commit.get('parents') or []
        if not parent:
            break
        commit = api(f"/repos/{repo}/commits/{parent[0]['sha']}", token)
    raise ValueError('ancestral comum não encontrado nos últimos 30 commits')


class VisibleLegalText(HTMLParser):
    """Extrai texto legível; scripts, estilos e metadados não fazem parte da lei."""
    OMIT = frozenset(('head', 'script', 'style', 'noscript', 'svg', 'iframe'))
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skipped = []
        self.parts = []
        self.struck = []

    def handle_starttag(self, tag, attrs):
        if tag in self.OMIT:
            self.skipped.append(tag)
        elif not self.skipped and (tag in ('s', 'strike', 'del') or
                any(name == 'style' and 'line-through' in (value or '').lower()
                    for name, value in attrs)):
            self.struck.append(tag)
            self.parts.append(' [INICIO_TACHADO] ')

    def handle_endtag(self, tag):
        if tag in self.skipped:
            while self.skipped:
                if self.skipped.pop() == tag:
                    break
        elif tag in self.struck:
            while self.struck:
                if self.struck.pop() == tag:
                    break
            self.parts.append(' [FIM_TACHADO] ')

    def handle_data(self, data):
        if not self.skipped:
            self.parts.append(data)


def legal_text_digest(page):
    parser = VisibleLegalText()
    parser.feed(page)
    body = html.unescape(' '.join(parser.parts))
    normalized = re.sub(r'\s+', ' ', body.replace('\xa0', ' ')).strip()
    # Evita armazenar como válido um desafio HTML, erro 200, página vazia ou texto truncado.
    articles = re.findall(r'\bArt\.?\s*(\d{1,4})\s*[º°o.]', normalized, re.I)
    if len(normalized) < 7000 or len(articles) < 10 or '1' not in articles:
        raise ValueError('conteúdo oficial não parece conter a legislação integral')
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def official_hash(url):
    u = urllib.parse.urlsplit(url)
    allowed = ('www.planalto.gov.br', 'planalto.gov.br')
    if u.scheme != 'https' or u.hostname not in allowed:
        raise ValueError('endereço fora dos domínios oficiais permitidos')
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (legal-monitor/1.0)'})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        new = urllib.parse.urlsplit(response.url)
        if new.scheme != 'https' or new.hostname not in allowed:
            raise ValueError('redirecionamento não confiável')
        content = response.read(12_000_001)
        declared = response.headers.get_content_charset()
    if len(content) < 900 or len(content) > 12_000_000:
        raise ValueError('tamanho anormal da página')
    detected = re.search(rb'charset\s*=\s*["\x27]?\s*([-\w]+)', content[:8000], re.I)
    charset = declared or (detected.group(1).decode('ascii') if detected else 'windows-1252')
    try:
        page = content.decode(charset)
    except (LookupError, UnicodeError):
        page = content.decode('windows-1252', errors='replace')
    return legal_text_digest(page)


def classify_official_update(hashes, pending, source_id, checksum):
    """Confirma alteração textual apenas depois de duas leituras consecutivas iguais."""
    if source_id not in hashes:
        hashes[source_id] = checksum
        pending.pop(source_id, None)
        return 'baseline'
    if hashes[source_id] == checksum:
        pending.pop(source_id, None)
        return 'unchanged'
    was_pending = pending.get(source_id) == checksum
    pending[source_id] = checksum
    return 'confirmed' if was_pending else 'possible'


def load_state(repo, token):
    try:
        raw, sha = read_file(repo, STATE_PATH, 'main', token, max_bytes=100_000)
    except RuntimeError as exc:
        if 'HTTP 404' in str(exc):
            return {}, None
        raise
    state = json.loads(raw)
    if not isinstance(state, dict):
        raise ValueError('estado anterior não é um objeto JSON')
    return state, sha


def save_state(repo, token, state, old_sha):
    state['checked_at_utc'] = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    content = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
    data = {'message': 'chore: registrar auditoria automática da legislação',
            'content': base64.b64encode(content.encode()).decode(), 'branch': 'main'}
    if old_sha:
        data['sha'] = old_sha
    api(f'/repos/{repo}/contents/{STATE_PATH}', token, method='PUT', payload=data)


def main():
    token = os.environ.get('GITHUB_TOKEN', '')
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    if not token or not repo or repo == SOURCE:
        raise RuntimeError('requer autenticação e execução no fork, não no projeto original')
    meta = api(f'/repos/{repo}', token)
    if not meta.get('fork') or meta.get('parent', {}).get('full_name') != SOURCE:
        raise RuntimeError('o repositório não é fork direto do projeto autorizado')
    state, sha = load_state(repo, token)
    warnings, blocks, notes = [], [], []
    with open(os.path.join(os.path.dirname(__file__), 'fontes_oficiais.json'), encoding='utf-8') as handle:
        sources = json.load(handle)['fontes']
    # Novo espaço de hashes para não confundir HTML bruto da versão antiga com texto.
    hashes = state.setdefault('hashes_textuais_oficiais', {})
    pending = state.setdefault('mudancas_oficiais_pendentes', {})
    for source in sources:
        sid = source['id']
        try:
            checksum = official_hash(source['url'])
            classification = classify_official_update(hashes, pending, sid, checksum)
            if classification == 'baseline':
                notes.append(f"Referência textual oficial inicial registrada: {sid}")
            elif classification == 'possible':
                notes.append(f"Variação na página de {sid}; aguardando confirmação na próxima verificação.")
            elif classification == 'confirmed':
                warnings.append(f"Alteração textual oficial confirmada em duas verificações: {sid} — {source['url']}. Revisão jurídica necessária.")
        except Exception as exc:
            warnings.append(f"Não foi possível validar a fonte oficial {sid}: {exc}")
    head = api(f'/repos/{SOURCE}/commits/main', token)['sha']
    last = state.get('upstream_confirmado')
    if last:
        try:
            api(f'/repos/{SOURCE}/commits/{last}', token)
        except RuntimeError as exc:
            if 'HTTP 404' not in str(exc):
                raise
            last = None
            notes.append('Referência anterior era um commit exclusivo do fork; recalculando ancestral.')
    if not last:
        last = fork_ancestor(repo, token)
        state['upstream_confirmado'] = last
        notes.append('Linha-base inicial encontrada: ' + last[:12])
    if head == last:
        notes.append('Origem sem commits novos desde a última sincronização.')
    else:
        blocks, count = inspect_changes(last, head, token)
        if blocks:
            notes.append(f'{count} arquivos verificados/listados; integração bloqueada para revisão.')
        elif api(f'/repos/{SOURCE}/commits/main', token)['sha'] != head:
            blocks.append('Novo commit recebido durante verificação; aguardar próxima execução')
        else:
            result = api(f'/repos/{repo}/merge-upstream', token, method='POST', payload={'branch': 'main'})
            state['upstream_confirmado'] = head
            notes.append(f"Sincronização GitHub aplicada: {result.get('merge_type', 'merge')}; {count} arquivos auditados.")
    state['ultimo_resultado'] = {'notas': notes, 'bloqueios': blocks, 'avisos': warnings}
    save_state(repo, token, state, sha)
    result = '\n'.join(notes + ['BLOQUEIO: ' + s for s in blocks] + ['AVISO: ' + s for s in warnings])
    print(result or 'Nenhuma mudança detectada')
    for warning in warnings:
        # Anotação visível no GitHub Actions, sem classificar a rotina inteira como falha.
        safe = warning.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
        print('::warning title=Monitor da legislação::' + safe)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as handle:
            handle.write('## Monitor de legislação\n\n' + '\n\n'.join('- ' + t for t in notes + blocks + warnings) + '\n')
    # Bloqueios impedem sincronização e sinalizam falha; avisos das fontes oficiais
    # são registrados e não invalidam a verificação de atualizações do fork.
    if blocks:
        sys.exit(2)


if __name__ == '__main__':
    main()
