# -*- coding: utf-8 -*-
"""K줄달음(퀴즈 러너) 문항 — `runner_2026.json`.

🔑 출처마다 형식이 다르다 → **여기서 하나로 합친다** (K줄달음 doc/03 10-15). 앱은 결과만 읽는다.

  출처                         카테고리       OX 문장
  knowledge/travel/korean/trend 상식 등       Gemini가 만든 «틀»에 보기를 넣는다 (며칠에 나눠)
  runner/sources/*.kquiz        경제          〃
  general_2026.json             우리말 사전   정해진 문장 (AI 없음 · 뜻풀이는 원문 그대로)
  kdalin/confusables.py         맞춤법        정해진 문장 (AI 없음)

🔴 **기존 파일은 읽기만 한다** — knowledge.json 등은 KDailyUtil, general_2026.json은 K달인이 쓴다.
🔴 문항 하나 = 항목 하나(`id` = 원 문항). 4지선다(`mc`)와 OX 문장들(`ox`)을 같이 담는다 —
   앱은 한 판에 같은 `id`를 한 번만 낸다(같은 문항의 O/X가 이어 나오면 답이 샌다, K줄달음 doc/03 10-15).

사용:
  python runner/build_runner.py             # 변환 대기 문항을 하루치만 Gemini로
  python runner/build_runner.py --no-ai     # Gemini 없이(정해진 문장·캐시만)
  python runner/build_runner.py --selftest  # 가짜 응답으로 한 바퀴 (파일 안 씀 · 키 불필요)
"""
import glob
import hashlib
import io
import json
import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'kdalin'))

import ox_template  # noqa: E402
from josa import normalize  # noqa: E402

OUT = os.path.join(ROOT, 'runner_2026.json')

# 🔑 하루치 — 기존 로봇들과 무료 한도를 나눠 쓴다. 비상시 워크플로 env로 줄이거나 늘린다.
CALLS_PER_RUN = int(os.environ.get('RUNNER_CALLS_PER_RUN') or 2)
BATCH = int(os.environ.get('RUNNER_BATCH') or 30)   # 2회 × 30 = 하루 60문항 → 약 790문항이 2주 남짓

# 🔑 관문(레인)에 들어가는 보기 길이 — 넘으면 4지선다로는 안 쓰고 OX로만 쓴다 (K줄달음 P0: 6자 확인)
MC_MAX_OPTION_CHARS = 10

CREDIT = '뜻풀이 출처: 국립국어원 표준국어대사전 (CC BY-SA 2.0 KR)'
FORBIDDEN = ['우리말 겨루기', '우리말겨루기', 'KBS']

# 기존 파일 → 게임 카테고리. 🔴 순서 = Gemini 변환 순서(상식부터)
LEGACY = [
    ('knowledge.json', '상식'),
    ('travel.json', '세계여행'),
    ('korean.json', '우리말'),
    ('trend.json', '신조어'),
]
SUB = {
    '시사 상식': '시사',
    '맞춤법 및 띄어쓰기': '맞춤법',
    '고난이도 고유어': '고유어', '순우리말': '고유어', '아름다운 순우리말': '고유어',
    '국가 수도': '수도', '국가수도': '수도', '국가명': '수도',
    '세계명소': '명소', '세계 명소': '명소', '해외명소': '명소', '관광명소': '명소', '랜드마크': '명소',
    '최신 유행어/신조어': '신조어', '최신 유행어': '신조어', '유행어/신조어': '신조어', '유행어': '신조어',
    '라이프스타일': '신조어',
}
GENERAL_SUB = {'definition': '뜻풀이', 'idiom': '관용구', 'proverb': '속담'}

# 🔴 사실이 의심스러운 원 문항 — 확인 전까지 내지 않는다 (K's works todo 2026-10-16)
SKIP_IDS = {
    30036: '혼천의는 세종 때 만들었는데 «세종 때 아닌 것»의 정답으로 되어 있다',
    30072: '국정 회의 장소 정답이 근정전 — 사정전이 아닌가',
}

CATEGORY_ORDER = ['상식', '세계여행', '우리말', '신조어', '경제', '우리말 사전', '맞춤법']
LEVEL_OF = {1: 'easy', 2: 'normal', 3: 'hard'}   # 옛 응답(수준 도입 전) 읽기용

# 🔑 수준 = 교과 과정 기준 4단계 + 그 안의 1~3 (K줄달음 doc/03 2026-10-20)
#    🔑 tier는 앱이 «같은 수준 안에서 쉬운 것부터» 내는 순서에만 쓴다 — 화면에 안 보인다.
GRADES = {1: 'elem', 2: 'middle', 3: 'high', 4: 'expert'}
# 옛 앱(level만 읽는다)이 그대로 돌게 level도 채운다
LEVEL_BY_GRADE = {'elem': 'easy', 'middle': 'normal', 'high': 'normal', 'expert': 'hard'}


def load(path, default):
    if not os.path.exists(path):
        return default
    with io.open(path, encoding='utf-8') as f:
        return json.load(f)


def has_forbidden(*texts):
    return any(w in (t or '') for t in texts for w in FORBIDDEN)


def ox_key(question, options, answer):
    """원 문항이 바뀌면 OX를 다시 만든다 — 질문·보기·정답의 지문(指紋)."""
    raw = json.dumps([question, options, answer], ensure_ascii=False)
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:10]


def sane_mc(options, answer):
    return (len(options) == 4 and len(set(options)) == 4 and answer in options
            and all(isinstance(o, str) and o.strip() for o in options))


# ── 출처 읽기 ──────────────────────────────────────────────────────────────

def legacy_sources():
    out = []
    for fn, category in LEGACY:
        for q in load(os.path.join(ROOT, fn), []):
            if q.get('type') != 'MULTIPLE_CHOICE' or q.get('id') in SKIP_IDS:
                continue
            options, answer = q.get('options') or [], q.get('answer')
            if not sane_mc(options, answer):
                continue
            if has_forbidden(q.get('question'), q.get('explanation'), *options):
                continue
            sub = (q.get('subCategory') or '').strip()
            out.append({
                'id': 'q-%s' % q['id'], 'via': 'ai', 'category': category,
                'subCategory': SUB.get(sub, sub),
                'question': q['question'].strip(), 'prompt': '',
                'options': options, 'answer': answer,
                'explanation': (q.get('explanation') or '').strip(), 'credit': '',
            })
    return out


def kquiz_sources():
    """runner/sources/*.kquiz — 🔑 「경제」(주식 용어 사전). 거의 AI 생성, 사용 확정 (K줄달음 doc/03 10-16 Q3)."""
    out = []
    for path in sorted(glob.glob(os.path.join(HERE, 'sources', '*.kquiz'))):
        for q in load(path, {}).get('questions', []):
            options, answer = q.get('options') or [], q.get('answer')
            if q.get('type') != 'MULTIPLE_CHOICE' or not sane_mc(options, answer):
                continue
            if has_forbidden(q.get('question'), q.get('explanation'), *options):
                continue
            # .kquiz에는 id가 없다 → 질문 글로 만든다(순서가 바뀌어도 같은 id)
            qid = 'eco-' + hashlib.sha1(q['question'].encode('utf-8')).hexdigest()[:8]
            out.append({
                'id': qid, 'via': 'ai', 'category': '경제',
                'subCategory': (q.get('subCategory') or '').strip(),
                'question': q['question'].strip(), 'prompt': '',
                'options': options, 'answer': answer,
                'explanation': (q.get('explanation') or '').strip(), 'credit': '',
            })
    return out


def general_sources():
    """general_2026.json (K달인 ②일반). 🔴 뜻풀이는 원문 그대로 — prompt 자리에만 둔다 (doc/04 §4)."""
    out = []
    for g in load(os.path.join(ROOT, 'general_2026.json'), {}).get('items', []):
        kind = g.get('kind')
        if kind not in GENERAL_SUB:
            continue
        options, answer = g.get('choices') or [], g.get('answer')
        if not sane_mc(options, answer) or not (g.get('prompt') or '').strip():
            continue
        out.append({
            'id': g['id'], 'via': kind, 'category': '우리말 사전', 'subCategory': GENERAL_SUB[kind],
            'question': g.get('question') or '', 'prompt': g['prompt'],
            'options': options, 'answer': answer,
            'explanation': '', 'credit': CREDIT,
        })
    return out


def pair_sources():
    """kdalin/confusables.py — 「바른 표기로 달려라」 2갈래. 한쪽만 맞는 짝만 있다(허용 규정 제외)."""
    from confusables import PAIRS
    out = []
    for right, wrong, _head, _sense, rule in PAIRS:
        # 보기 순서는 낱말로 정한다 — 매번 같고, 정답이 늘 왼쪽(위)이지는 않다
        flip = hashlib.sha1(right.encode('utf-8')).digest()[0] % 2 == 1
        out.append({
            'id': 'sp-' + right, 'via': 'pair', 'category': '맞춤법', 'subCategory': '바른 표기',
            'question': '바른 표기는?', 'prompt': '',
            'options': [wrong, right] if flip else [right, wrong], 'answer': right,
            'wrong': wrong, 'explanation': rule, 'credit': '',
        })
    return out


# ── 항목 만들기 ────────────────────────────────────────────────────────────

def fixed_ox(src):
    """AI 없이 만드는 OX 문장. 🔴 조사가 필요 없는 꼴로 쓴다(따옴표 뒤 «—»)."""
    via = src['via']
    if via == 'pair':
        return [{'text': "'%s' — 바른 표기다." % src['answer'], 'answer': 'O'},
                {'text': "'%s' — 바른 표기다." % src['wrong'], 'answer': 'X'}]
    tail = {'definition': '낱말이다', 'idiom': '관용구다', 'proverb': '속담이다'}[via]
    mark = "'%s'" if via == 'definition' else '「%s」'
    ordered = [src['answer']] + [o for o in src['options'] if o != src['answer']]
    return [{'text': '%s — 이 뜻에 맞는 %s.' % (mark % o, tail), 'answer': 'O' if o == src['answer'] else 'X'}
            for o in ordered]


def make_item(src, conv):
    options, answer = src['options'], src['answer']
    mc = None
    if all(len(o) <= MC_MAX_OPTION_CHARS for o in options):
        mc = {'options': options, 'answer': answer}
    item = {
        'id': src['id'], 'category': src['category'], 'subCategory': src['subCategory'],
        'level': 'normal', 'question': src['question'], 'prompt': src['prompt'],
        'mc': mc, 'ox': [], 'explanation': src['explanation'], 'credit': src['credit'],
    }
    if src['via'] != 'ai':
        item['ox'] = fixed_ox(src)
        return item
    c = conv.get(src['id'])
    if c and c.get('oxKey') == ox_key(src['question'], options, answer):
        item['level'] = c.get('level') or 'normal'
        if c.get('grade'):
            item['grade'], item['tier'] = c['grade'], c['tier']
        item['oxKey'] = c['oxKey']
        if c.get('oxSkip'):
            item['oxSkip'] = c['oxSkip']
        elif c.get('oxTemplate'):
            item['oxTemplate'] = c['oxTemplate']
            item['ox'] = ox_template.statements(c['oxTemplate'], options, answer)
    return item


def grading(row):
    """응답의 grade·tier → {'grade', 'tier', 'level'}. 🔴 값이 이상하면 {} — 매기지 않은 채로 둔다."""
    grade, tier = row.get('grade'), row.get('tier')
    if not isinstance(grade, int) or grade not in GRADES:
        return {}
    if not isinstance(tier, int) or tier not in (1, 2, 3):
        tier = 2
    name = GRADES[grade]
    return {'grade': name, 'tier': tier, 'level': LEVEL_BY_GRADE[name]}


def apply_answer(src, row):
    """Gemini 응답 한 줄 → 캐시 항목. 🔴 검사에 걸리면 내지 않고 이유를 남긴다(매일 다시 묻지 않게)."""
    key = ox_key(src['question'], src['options'], src['answer'])
    graded = grading(row) or {
        'level': LEVEL_OF.get(row.get('level') if isinstance(row.get('level'), int) else None, 'normal')}
    if row.get('ok') is False:
        return dict(graded, oxKey=key, oxSkip='AI: %s' % (row.get('why') or '부적합'))
    template = row.get('template')
    problems = ox_template.verify(template, src['options'], src['answer'])
    if problems:
        return dict(graded, oxKey=key, oxSkip='검사: %s' % '; '.join(problems))
    return dict(graded, oxKey=key, oxTemplate=normalize(template.strip()))


def all_sources():
    return legacy_sources() + kquiz_sources() + general_sources() + pair_sources()


def build(ask, use_ai=True, ask_grades=None):
    """ask(batch) → {id: row}. 반환: (items, 요약).

    🔑 ask_grades가 있으면 변환 대기가 다 끝난 뒤 남는 호출로 «수준 없는» 옛 변환을 다시 매긴다
       (수준 도입 전 240문항 — K줄달음 doc/03 2026-10-20). 틀은 건드리지 않는다.
    """
    existing = load(OUT, {}).get('items', [])
    conv = {it['id']: it for it in existing if it.get('oxKey')}
    sources = all_sources()

    pending = [s for s in sources if s['via'] == 'ai'
               and conv.get(s['id'], {}).get('oxKey') != ox_key(s['question'], s['options'], s['answer'])]
    print('출처 %d문항 · OX 변환 대기 %d' % (len(sources), len(pending)))

    converted, regraded, calls = 0, 0, 0
    if use_ai and pending:
        for n in range(CALLS_PER_RUN):
            batch = pending[n * BATCH:(n + 1) * BATCH]
            if not batch:
                break
            calls += 1
            print('  🤖 변환 %d/%d — %d문항' % (n + 1, CALLS_PER_RUN, len(batch)))
            rows = ask(batch)
            if not rows:
                print('  ↪ 이번 실행은 여기까지 — 내일 이어서 한다')
                calls = CALLS_PER_RUN   # 🔴 한도에 막혔으면 다시 매기기도 하지 않는다
                break
            for s in batch:
                row = rows.get(s['id'])
                if row:
                    conv[s['id']] = apply_answer(s, row)
                    converted += 1

    # 🔑 변환이 다 끝났을 때만 — 한도를 나눠 쓰지 않는다
    still_pending = len(pending) - converted
    regrade = [s for s in sources if s['via'] == 'ai' and s['id'] in conv and not conv[s['id']].get('grade')
               and conv[s['id']].get('oxKey') == ox_key(s['question'], s['options'], s['answer'])]
    if use_ai and ask_grades and still_pending == 0 and regrade:
        for n in range(CALLS_PER_RUN - calls):
            batch = regrade[n * BATCH:(n + 1) * BATCH]
            if not batch:
                break
            print('  🤖 수준 다시 매기기 — %d문항' % len(batch))
            rows = ask_grades(batch)
            if not rows:
                break
            for s in batch:
                graded = grading(rows.get(s['id']) or {})
                if graded:
                    conv[s['id']] = dict(conv[s['id']], **graded)
                    regraded += 1

    items = [make_item(s, conv) for s in sources]
    items.sort(key=lambda it: (CATEGORY_ORDER.index(it['category']), it['id']))

    summary = {
        'items': len(items),
        'mc': sum(1 for it in items if it['mc']),
        'oxItems': sum(1 for it in items if it['ox']),
        'statements': sum(len(it['ox']) for it in items),
        'skipped': sum(1 for it in items if it.get('oxSkip')),
        'pending': sum(1 for it in items if not it['ox'] and not it.get('oxSkip')),
        'convertedThisRun': converted,
        'graded': sum(1 for it in items if it.get('grade')),
        'regradePending': len(regrade) - regraded,
        'regradedThisRun': regraded,
    }
    return items, summary


def write(items):
    # 🔑 «한 줄에 한 문항» — 앱이 통째로 받는 파일이라 들여쓰기 공백을 뺀다(약 절반).
    #    그래도 줄 단위라 git diff로 어느 문항이 바뀌었는지 보인다.
    rows = ',\n'.join(json.dumps(it, ensure_ascii=False, separators=(',', ':')) for it in items)
    text = '{"version":1,"items":[\n' + rows + '\n]}\n'
    if os.path.exists(OUT) and io.open(OUT, encoding='utf-8').read() == text:
        print('바뀐 것이 없다 — 쓰지 않는다')
        return
    with io.open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    print('💾 %s 저장' % os.path.basename(OUT))


def selftest():
    """키 없이 한 바퀴 — 가짜 응답으로 틀 검사·조사·문장 생성을 본다. 파일은 쓰지 않는다."""
    global OUT
    OUT = os.path.join(HERE, '__selftest_none__.json')   # 캐시 없이 시작

    def fake_ask(batch):
        rows = {}
        for s in batch:
            if s['id'] == 'q-30002':
                rows[s['id']] = {'id': s['id'], 'template': '태양계에서 가장 큰 행성은 {X}이다.',
                                 'grade': 1, 'tier': 1, 'ok': True}
            elif s['id'] == 'q-30067':
                rows[s['id']] = {'id': s['id'], 'ok': False, 'why': '기준 연도가 있다', 'grade': 1}
            elif s['id'] == 'q-30004':
                # 옛 형식(수준 도입 전) — level만 온다
                rows[s['id']] = {'id': s['id'], 'template': "'별이 빛나는 밤'을 그린 작가는 {X}(이)다.",
                                 'level': 1, 'ok': True}
            else:
                rows[s['id']] = {'id': s['id'], 'template': s['question'], 'grade': 9, 'ok': True}
        return rows

    asked = []

    def fake_grades(batch):
        asked.extend(s['id'] for s in batch)
        return {s['id']: {'id': s['id'], 'grade': 4, 'tier': 3} for s in batch}

    global CALLS_PER_RUN, BATCH
    CALLS_PER_RUN, BATCH = 2, 2000
    items, summary = build(fake_ask, ask_grades=fake_grades)
    by_id = {it['id']: it for it in items}
    jupiter = by_id['q-30002']
    print(json.dumps(jupiter['ox'], ensure_ascii=False))
    assert jupiter['ox'][0] == {'text': '태양계에서 가장 큰 행성은 목성이다.', 'answer': 'O'}, jupiter['ox']
    assert (jupiter['grade'], jupiter['tier'], jupiter['level']) == ('elem', 1, 'easy'), jupiter
    # 🔑 수준이 없는 변환(옛 형식·이상한 값)은 변환이 끝난 뒤 남은 호출로 다시 매긴다 — 틀은 그대로
    assert 'q-30002' not in asked and 'q-30004' in asked
    assert (by_id['q-30004']['grade'], by_id['q-30004']['level']) == ('expert', 'hard')
    assert by_id['q-30004']['ox'], '다시 매겨도 OX 문장은 그대로'
    assert 'oxSkip' in by_id['q-30067']
    assert by_id['sp-며칠']['ox'][0]['answer'] == 'O'
    assert all(it['credit'] == CREDIT for it in items if it['category'] == '우리말 사전')
    print('요약', summary)
    print('✅ selftest 통과')


def main():
    args = sys.argv[1:]
    if '--selftest' in args:
        selftest()
        return 0
    use_ai = '--no-ai' not in args
    items, summary = build(ox_template.ask, use_ai=use_ai, ask_grades=ox_template.ask_grades)
    write(items)
    print('요약', json.dumps(summary, ensure_ascii=False),
          '· Gemini 호출 %d회 · 한도 대기 %d회 · 모델 %s'
          % (ox_template.Stats.calls, ox_template.Stats.quota_waits, ox_template.Stats.model))
    return 0


if __name__ == '__main__':
    sys.exit(main())
