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

from josa import MARKERS, SLOT, fill, normalize

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
""" + '{grading}' + """
- ok: 다음이면 false — 「○○년 기준」처럼 시간이 지나면 답이 바뀌는 문항, 정답이 하나로 갈리지 않는 문항,
  사실이 틀린 문항, 평서문으로 바꾸면 어색해지는 문항. false면 why에 짧은 이유를 쓴다.

[출력] JSON 배열만. 설명·머리말·코드블록 금지.
[{"id": "...", "template": "...", "grade": 2, "tier": 1, "ok": true, "why": ""}]

[문항]
{items}"""

# 🔑 수준 = «교과 과정 몇 학년에서 배우나» (K줄달음 doc/03 2026-10-20).
#    🔴 전에는 「1 = 대부분 아는 쉬운 상식」 한 줄이었다 → 슈뢰딩거의 고양이·기화열까지 «쉬움»(57%).
#    「유명한 용어인가」가 아니라 «그 나이대 보통 사람이 맞히나»로 매기게 예시를 붙인다.
GRADING = """- grade (수준): 이 문항을 «보통 사람이 맞힐 수 있는» 가장 낮은 단계.
  교과서에 나오는 내용은 «처음 배우는 학년», 시사·생활·신조어는 «대략 몇 살이면 아는가»로 정한다.
  1 = 초등 — 초등학생도 안다. 예: 태양계에서 가장 큰 행성은 목성 · 한글을 만든 왕은 세종대왕 · 일본의 수도는 도쿄
  2 = 중등 — 중학교 수준. 예: 3·1 운동은 1919년 · 물체를 위로 밀어 올리는 힘은 부력 · 대기에 가장 많은 기체는 질소
  3 = 고등 — 고등학교·수능 수준. 예: 영조·정조의 탕평책 · 갑신정변(1884) · 액체가 기체로 변할 때 흡수하는 열은 기화열
  4 = 전문 — 대학·전공이거나 그 분야에 관심이 깊어야 안다. 예: 슈뢰딩거의 고양이 · 달의 조석 고정 · 보일의 법칙
  🔴 «유명한 용어»라고 낮게 매기지 마라. 이름은 들어 봤어도 «정답을 고를 수 있나»가 기준이다.
  🔴 헷갈리면 높은 쪽으로 매긴다 — 쉬운 단계에 어려운 문항이 섞이면 처음 하는 사람이 바로 그만둔다.
- tier (같은 수준 안에서): 1 = 그 수준에서 쉬운 편, 2 = 보통, 3 = 그 수준에서 어려운 편"""

PROMPT = PROMPT.replace('{grading}', GRADING)

# 🔑 이미 변환한 문항의 수준만 다시 묻는다 — 틀은 그대로 두고 한도를 덜 쓴다.
#    변환 대기가 다 끝난 뒤에만 돈다(build_runner.regrade_pending).
REGRADE_PROMPT = """너는 한국어 퀴즈 편집자다. 아래 4지선다 문항마다 수준을 매겨라.

""" + GRADING + """

[출력] JSON 배열만. 설명·머리말·코드블록 금지.
[{"id": "...", "grade": 2, "tier": 1}]

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


def ask_grades(items):
    """수준만 다시 묻는다(틀은 그대로). 응답 형식·실패 처리는 [ask]와 같다."""
    return ask(items, REGRADE_PROMPT)


def ask(items, template=None):
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
    prompt = (template or PROMPT).replace('{items}', lines)

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
    else:
        # 🔴 validate_runner.py와 같은 잣대 — fill()은 {X} 바로 뒤 표지만 푼다.
        #    딴 자리의 「물(을)」이 남으면 여기서 못 막고 검사에서 걸려 하루치 푸시가 통째로 막혔다(2026-10-25).
        left = sorted({m for f in filled for m in [SLOT] + list(MARKERS) if m in f})
        if left:
            p.append('채운 문장에 틀 표기가 남았다 (%s)' % ', '.join(left))
    return p


def statements(template, options, answer):
    """틀 + 보기 → [{'text', 'answer': 'O'|'X'}]. 정답이 맨 앞."""
    t = normalize(template.strip())
    out = [{'text': fill(t, answer), 'answer': 'O'}]
    out += [{'text': fill(t, o), 'answer': 'X'} for o in options if o != answer]
    return out
