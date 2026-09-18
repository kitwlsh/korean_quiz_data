# -*- coding: utf-8 -*-
"""K달인 문항 검사 — 🔴 **푸시 전에 여기서 막는다.**

`01` §1의 교훈: **`type` 오타 하나로 100문항이 앱에서 통째로 안 보인 사고**가 있었다.
🔑 앱도 한 번 더 거르지만(항목 단위), 로봇이 애초에 깨진 것을 올리지 않는 편이 낫다.

🔑 **앱의 검사와 같은 규칙이다** (KDalin `DalinValidation`·`QuizValidation` · doc/08 §4).
   한쪽만 고치면 어긋나므로, 규칙을 바꿀 때는 **양쪽을 함께** 본다.

🔴 기존 `validate.py`를 건드리지 않는다 — 그건 `korean.json`·`passages_2026.json`용이고
   KDailyUtil이 거기 걸려 있다.

사용:
  python kdalin/validate_kdalin.py          # 있는 파일만 검사
"""
import io
import json
import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEVELS = {'easy', 'normal', 'hard'}
GENERAL_KINDS = {'definition', 'proverb', 'idiom', 'compound', 'association'}
CHO_BASE, CHO = 0xAC00, 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ'

# 🔴 CLAUDE.md 1·2번 — 기출 금지 · 「우리말 겨루기」·KBS 표기 금지
FORBIDDEN = ['우리말 겨루기', '우리말겨루기', 'KBS']


def choseong_of(word):
    out = []
    for ch in word:
        c = ord(ch)
        out.append(CHO[(c - CHO_BASE) // 588] if CHO_BASE <= c <= 0xD7A3 else ch)
    return ''.join(out)


def spacing_of(text):
    chars, gaps, pending = [], [], False
    for ch in text:
        if ch == ' ':
            pending = True
            continue
        if chars:
            gaps.append(pending)
        pending = False
        chars.append(ch)
    return ''.join(chars), gaps


def check_dalin(item):
    """doc/08 §4의 검사 + ③ 어휘력."""
    p = []
    if not item.get('id'):
        p.append('id가 비었다')
    if item.get('level') not in LEVELS:
        p.append('level이 easy|normal|hard가 아니다 (%s)' % item.get('level'))
    text = item.get('answerText') or ''
    if not text:
        return p + ['answerText가 비었다']

    chars, answer = spacing_of(text)
    initial = item.get('initialSpacing') or []
    if len(initial) != max(len(chars) - 1, 0):
        p.append('initialSpacing 길이 %d != %d' % (len(initial), len(chars) - 1))
    elif initial == answer:
        p.append('initialSpacing이 정답과 같다 — 손 안 대도 정답이 된다')

    spelling = item.get('spelling') or []
    if not spelling:
        p.append('맞춤법 문항이 없다')
    orders = set()
    for sp in spelling:
        tag = 'spelling#%s' % sp.get('order')
        if sp.get('order') in orders:
            p.append('%s: order 중복' % tag)
        orders.add(sp.get('order'))
        span = sp.get('span') or [0, 0]
        s, e = span[0], span[1]
        if s < 0 or e > len(text) or s >= e:
            p.append('%s: span이 범위를 벗어났다 (%d..%d / %d)' % (tag, s, e, len(text)))
        elif text[s:e] != sp.get('right'):
            p.append("%s: span 위치가 '%s'인데 right는 '%s'" % (tag, text[s:e], sp.get('right')))
        if sp.get('wrong') == sp.get('right'):
            p.append('%s: wrong과 right가 같다' % tag)
        if sp.get('right') not in (sp.get('choices') or []):
            p.append('%s: choices에 정답이 없다' % tag)
        if not (sp.get('rule') or '').strip():
            p.append('%s: rule이 비었다' % tag)
        if not (sp.get('definition') or '').strip():
            p.append('%s: definition이 비었다' % tag)

    ordered = sorted(spelling, key=lambda x: (x.get('span') or [0])[0])
    for i in range(len(ordered) - 1):
        if (ordered[i].get('span') or [0, 0])[1] > (ordered[i + 1].get('span') or [0, 0])[0]:
            p.append('span이 겹친다 (#%s, #%s)' % (ordered[i].get('order'),
                                                  ordered[i + 1].get('order')))

    v = item.get('vocab')
    if v:
        if not (v.get('headword') or '').strip():
            p.append('vocab: headword가 비었다')
        d = v.get('definition') or ''
        if not d:
            p.append('vocab: definition이 비었다')
        ch = v.get('choices') or []
        if len(ch) != 5:
            p.append('vocab: 보기가 %d개다(5개여야 한다)' % len(ch))
        if len(set(ch)) != len(ch):
            p.append('vocab: 보기에 중복이 있다')
        if v.get('answer') not in ch:
            p.append('vocab: choices에 정답이 없다')
        if d:
            # 🔴 이 두 줄이 이 문항의 «전부»다
            if v.get('answer') in d:
                p.append("vocab: 정답 '%s'이 뜻풀이에 들어 있다" % v.get('answer'))
            for c in ch:
                if c != v.get('answer') and c not in d:
                    p.append("vocab: 보기 '%s'가 뜻풀이에 없다 — 답이 둘이 된다" % c)
    return p


def check_choseong(item):
    p = []
    if not item.get('id'):
        p.append('id가 비었다')
    if item.get('level') not in LEVELS:
        p.append('level이 이상하다 (%s)' % item.get('level'))
    if not (item.get('answer') or '').strip():
        p.append('answer가 비었다')
    if not (item.get('definition') or '').strip():
        # 🔴 뜻풀이가 없으면 초성만 보고 맞히라는 뜻이 된다 — 풀 수 없는 문항
        p.append('definition이 비었다 — 풀 수 없는 문항이다')
    ch = item.get('choices') or []
    if ch:
        if item.get('answer') not in ch:
            p.append('choices에 정답이 없다')
        # 🔴 보기의 초성이 다르면 힌트만 보고 지워져 「보기가 있는 척하는」 4지선다가 된다
        chos = {choseong_of(c) for c in ch}
        if len(chos) > 1:
            p.append('보기의 초성이 서로 다르다: %s' % sorted(chos))
    return p


def check_general(item):
    p = []
    if not item.get('id'):
        p.append('id가 비었다')
    if item.get('kind') not in GENERAL_KINDS:
        p.append('kind가 이상하다 (%s)' % item.get('kind'))
    if item.get('level') not in LEVELS:
        p.append('level이 이상하다 (%s)' % item.get('level'))
    if not (item.get('answer') or '').strip():
        p.append('answer가 비었다')
    prompt = item.get('prompt') or ''
    if not prompt.strip():
        p.append('prompt가 비었다 — 물음에 제시문이 없다')
    ch = item.get('choices') or []
    if len(ch) < 4:
        p.append('보기가 %d개뿐이다' % len(ch))
    if item.get('answer') and item.get('answer') not in ch:
        p.append('choices에 정답이 없다')
    if len(set(ch)) != len(ch):
        p.append('choices에 중복이 있다')
    if not (item.get('definition') or '').strip() and not (item.get('rule') or '').strip():
        p.append('definition과 rule이 둘 다 비었다 — 해설에 근거가 없다')
    if item.get('kind') == 'definition' and item.get('answer') and item['answer'] in prompt:
        p.append('prompt에 정답이 그대로 들어 있다')
    return p


CHECKS = [
    ('dalin_2026.json', check_dalin),
    ('choseong_2026.json', check_choseong),
    ('general_2026.json', check_general),
]


def main():
    total_errors = 0
    for name, check in CHECKS:
        path = os.path.join(ROOT, name)
        if not os.path.exists(path):
            print('⏭  %s — 아직 없다' % name)
            continue
        raw = io.open(path, encoding='utf-8').read()

        # 🔴 CLAUDE.md 1·2번 — 파일 전체에서 금지어를 본다
        for word in FORBIDDEN:
            if word in raw:
                print('🔴 %s: 금지어 「%s」가 들어 있다' % (name, word))
                total_errors += 1

        feed = json.loads(raw)
        items = feed.get('items', [])
        ids, bad = set(), 0
        for item in items:
            problems = check(item)
            if item.get('id') in ids:
                problems = problems + ['id 중복']
            ids.add(item.get('id'))
            if problems:
                bad += 1
                if bad <= 5:
                    print('🔴 %s [%s]: %s' % (name, item.get('id'), '; '.join(problems)))
        total_errors += bad
        mark = '✅' if bad == 0 else '🔴'
        print('%s %-22s %3d문항 · 문제 %d건' % (mark, name, len(items), bad))

    if total_errors:
        print('\n🔴 검사 실패 %d건 — 푸시하지 않는다' % total_errors)
        return 1
    print('\n✅ 검사 통과')
    return 0


if __name__ == '__main__':
    sys.exit(main())
