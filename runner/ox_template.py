# -*- coding: utf-8 -*-
"""4지선다 → **OX 문장 틀** (Gemini).

🔑 문항마다 «빈칸 문장 틀 하나»만 받는다 — 「몬테네그로의 수도는 {X}(이)다.」
   정답 보기를 넣으면 참(O), 오답 보기를 넣으면 거짓(X). 문항 1개 → O 1 + X 3 (K줄달음 doc/04 §3).
   보기를 넣고 조사를 맞추는 일은 `josa.py`가 한다 — AI 호출은 틀 하나 값만.

🔴 **무료 한도로 며칠에 나눠 돈다** (K줄달음 doc/03 10-16 Q2). 한 번에 [BATCH]문항씩 묶어
   하루 [CALLS_PER_RUN]번만 부른다. 기존 로봇(퀴즈·지문·K달인)과 키·한도를 같이 쓰므로
   가장 늦게 돌고, 막히면 다음 날 이어서 한다 — 죽지 않는다.

🔴 AI 말을 믿지 않는다 — [verify]가 틀을 «우리가» 검사한다(passage_source.verify와 같은 원칙).
"""
import json
import os
import re
import time

from josa import SLOT, fill, normalize

MODEL_CANDIDATES = [
    m for m in [
        os.environ.get('QUIZ_MODEL', '').strip(),   # 🔧 기존 로봇과 «같은» 비상 레버
        'gemini-flash-latest',
        'gemini-3.5-flash',
        'gemini-3.6-flash',
    ] if m
]

RETRY_ON_429 = 2
RETRY_SLEEP_CAP = 90

PROMPT = """너는 한국어 퀴즈 편집자다. 아래 4지선다 문항마다 «OX 문장 틀»을 하나씩 만들어라.

[틀 규칙]
1. 틀은 평서문 한 문장이다. 정답이 들어갈 자리에 {X}를 «정확히 한 번» 쓴다.
2. {X}에 «정답»을 넣으면 참, «다른 보기»를 넣으면 거짓인 문장이어야 한다.
3. {X} 바로 뒤 조사는 괄호형으로 쓴다: {X}(이)다, {X}(은)는, {X}(이)가, {X}(을)를, {X}(과)와, {X}(으)로
4. 틀 안에 정답이나 다른 보기의 낱말을 쓰지 마라(빈칸 자리에만 들어간다).
5. 문항이 「~이 아닌 것은?」이면 부정문으로 만든다. 예: {X}(은)는 온실가스가 아니다.
6. 원문의 뜻을 바꾸지 말고, 짧고 자연스럽게 쓴다(80자 이내). 물음표로 끝내지 않는다.

[함께 매길 것]
- level: 1 = 대부분 아는 쉬운 상식, 2 = 보통, 3 = 어려움
- ok: 다음이면 false — 「○○년 기준」처럼 시간이 지나면 답이 바뀌는 문항, 정답이 하나로 갈리지 않는 문항,
  사실이 틀린 문항, 평서문으로 바꾸면 어색해지는 문항. false면 why에 짧은 이유를 쓴다.

[출력] JSON 배열만. 설명·머리말·코드블록 금지.
[{"id": "...", "template": "...", "level": 1, "ok": true, "why": ""}]

[문항]
{items}"""


def _genai():
    import google.generativeai as genai
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not key:
        raise RuntimeError('GEMINI_API_KEY가 없다')
    genai.configure(api_key=key)
    return genai


def _retry_after(err, default=20):
    m = re.search(r'retry in ([0-9.]+)s', str(err), re.IGNORECASE)
    wait = float(m.group(1)) + 2 if m else float(default)
    return int(min(max(wait, 5), RETRY_SLEEP_CAP))


class Stats:
    calls = 0
    quota_waits = 0
    model = None


def ask(items):
    """문항 묶음을 보내고 {id: 응답} 을 받는다. 실패하면 {} — 로봇이 죽지는 않는다(내일 다시).

    items: [{'id', 'question', 'options', 'answer'}]
    """
    try:
        genai = _genai()
    except Exception as e:                                           # noqa: BLE001
        print('  ↪ Gemini를 못 쓴다: %s' % e)
        return {}

    lines = '\n'.join(json.dumps(
        {'id': it['id'], 'question': it['question'], 'options': it['options'], 'answer': it['answer']},
        ensure_ascii=False) for it in items)
    # 🔴 format()을 쓰지 않는다 — 틀 표기 {X}가 자리표시자로 잡혀 KeyError가 난다
    prompt = PROMPT.replace('{items}', lines)

    for name in MODEL_CANDIDATES:
        for attempt in range(RETRY_ON_429 + 1):
            try:
                Stats.calls += 1
                resp = genai.GenerativeModel(name).generate_content(prompt)
                Stats.model = name
                return parse(resp.text or '')
            except Exception as e:                                   # noqa: BLE001
                msg = str(e)
                low = msg.lower()
                if any(k in low for k in ('api key', 'api_key', 'permission', '401', '403')):
                    print('  🔴 키·권한 문제 — 이번 실행은 변환을 멈춘다: %s' % msg[:120])
                    return {}
                if '429' in msg or 'quota' in low or 'resource_exhausted' in low:
                    if attempt < RETRY_ON_429:
                        wait = _retry_after(e)
                        Stats.quota_waits += 1
                        print('  ⏳ %s 한도 초과 — %d초 자고 다시' % (name, wait))
                        time.sleep(wait)
                        continue
                print('  ↪ %s 실패(%s) — 다음 후보로' % (name, msg[:100]))
                break
    return {}


def parse(raw):
    """응답에서 JSON 배열을 꺼낸다. 깨졌으면 {}."""
    start, end = raw.find('['), raw.rfind(']')
    if start < 0 or end <= start:
        print('  ↪ 응답에 JSON 배열이 없다')
        return {}
    try:
        rows = json.loads(raw[start:end + 1])
    except ValueError as e:
        print('  ↪ 응답 JSON이 깨졌다: %s' % e)
        return {}
    return {str(r.get('id')): r for r in rows if isinstance(r, dict) and r.get('id') is not None}


def verify(template, options, answer):
    """🔴 틀이 조건을 지켰는지 «우리가» 검사한다. 문제가 없으면 []."""
    p = []
    if not isinstance(template, str) or not template.strip():
        return ['틀이 비었다']
    t = normalize(template.strip())
    if t.count(SLOT) != 1:
        p.append('{X}가 %d번 나온다(1번이어야 한다)' % t.count(SLOT))
        return p
    rest = t.replace(SLOT, '')
    for o in options:
        if len(o) >= 2 and o in rest:
            p.append("틀에 보기 '%s'가 들어 있다 — 답이 샌다" % o)
    if len(t) > 120:
        p.append('너무 길다(%d자)' % len(t))
    if t.rstrip().endswith('?'):
        p.append('물음표로 끝난다 — 평서문이 아니다')
    filled = [fill(t, o) for o in options]
    if any(f is None for f in filled):
        p.append('조사를 정할 수 없는 보기가 있다')
    elif len(set(filled)) != len(filled):
        p.append('채운 문장이 서로 같다')
    return p


def statements(template, options, answer):
    """틀 + 보기 → [{'text', 'answer': 'O'|'X'}]. 정답이 맨 앞."""
    t = normalize(template.strip())
    out = [{'text': fill(t, answer), 'answer': 'O'}]
    out += [{'text': fill(t, o), 'answer': 'X'} for o in options if o != answer]
    return out
