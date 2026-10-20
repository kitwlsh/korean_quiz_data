# -*- coding: utf-8 -*-
"""K줄달음 문항 검사 — 🔴 **푸시 전에 여기서 막는다.** (kdalin/validate_kdalin.py와 같은 원칙)

🔑 앱(kotlinx-serialization)은 타입이 하나만 틀려도 **파일 전체**를 버린다 → 타입부터 본다.
🔴 기존 `validate.py`·`kdalin/validate_kdalin.py`를 건드리지 않는다 — 각자 걸린 앱이 다르다.

사용:
  python runner/validate_runner.py
"""
import io
import json
import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from build_runner import CATEGORY_ORDER, CREDIT, FORBIDDEN, GRADES, MC_MAX_OPTION_CHARS  # noqa: E402
from josa import MARKERS, SLOT  # noqa: E402

NAME = 'runner_2026.json'
LEVELS = {'easy', 'normal', 'hard'}
STRINGS = ('id', 'category', 'subCategory', 'level', 'question', 'prompt', 'explanation', 'credit')
# 🔑 '(을)' 하나만 보면 관용구 「발(을) 구르다」가 걸린다 → 표지 «전체»로 본다
LEFTOVER = [SLOT] + list(MARKERS)


def check(item):
    p = ['%s가 문자열이 아니다 (%r)' % (k, item.get(k)) for k in STRINGS if not isinstance(item.get(k), str)]
    if p:
        return p
    if not item['id']:
        p.append('id가 비었다')
    if item['category'] not in CATEGORY_ORDER:
        p.append('category가 이상하다 (%s)' % item['category'])
    if item['level'] not in LEVELS:
        p.append('level이 easy|normal|hard가 아니다 (%s)' % item['level'])
    # 🔑 수준(교과 과정 기준)은 아직 없는 문항도 있다 — 있으면 값만 본다 (K줄달음 doc/03 2026-10-20)
    if 'grade' in item and item['grade'] not in GRADES.values():
        p.append('grade가 elem|middle|high|expert가 아니다 (%s)' % item['grade'])
    if 'grade' in item and item.get('tier') not in (1, 2, 3):
        p.append('tier가 1~3이 아니다 (%s)' % item.get('tier'))
    if not item['question'].strip():
        p.append('question이 비었다')
    if item['category'] == '우리말 사전':
        # 🔴 CC BY-SA — 출처 표기 · 뜻풀이 원문
        if item['credit'] != CREDIT:
            p.append('우리말 사전인데 출처 표기가 없다')
        if not item['prompt'].strip():
            p.append('우리말 사전인데 뜻풀이(prompt)가 없다')

    mc = item.get('mc')
    if mc is not None:
        options = mc.get('options') if isinstance(mc, dict) else None
        if not isinstance(options, list) or not all(isinstance(o, str) and o.strip() for o in options):
            p.append('mc.options가 문자열 목록이 아니다')
        else:
            if not 2 <= len(options) <= 4:
                p.append('mc 보기가 %d개다' % len(options))
            if len(set(options)) != len(options):
                p.append('mc 보기에 중복이 있다')
            if mc.get('answer') not in options:
                p.append('mc 정답이 보기에 없다')
            if any(len(o) > MC_MAX_OPTION_CHARS for o in options):
                p.append('mc 보기가 관문에 안 들어간다(%d자 초과)' % MC_MAX_OPTION_CHARS)

    ox = item.get('ox')
    if not isinstance(ox, list):
        return p + ['ox가 목록이 아니다']
    for s in ox:
        if not isinstance(s, dict) or not isinstance(s.get('text'), str) or not s['text'].strip():
            p.append('ox 문장이 비었거나 문자열이 아니다')
            continue
        if s.get('answer') not in ('O', 'X'):
            p.append('ox 정답이 O|X가 아니다 (%r)' % s.get('answer'))
        if any(m in s['text'] for m in LEFTOVER):
            p.append('ox 문장에 틀 표기가 남았다: %s' % s['text'])
    if ox:
        if sum(1 for s in ox if isinstance(s, dict) and s.get('answer') == 'O') != 1:
            p.append('ox에 O가 정확히 하나가 아니다')
        if len({s.get('text') for s in ox if isinstance(s, dict)}) != len(ox):
            p.append('ox 문장이 겹친다')
    return p


def main():
    path = os.path.join(ROOT, NAME)
    if not os.path.exists(path):
        print('⏭  %s — 아직 없다' % NAME)
        return 0
    raw = io.open(path, encoding='utf-8').read()
    errors = 0
    for word in FORBIDDEN:
        if word in raw:
            print('🔴 금지어 「%s」가 들어 있다' % word)
            errors += 1
    feed = json.loads(raw)
    if feed.get('version') != 1 or not isinstance(feed.get('items'), list):
        print('🔴 최상위 형식이 {version: 1, items: [...]}가 아니다')
        return 1
    ids, bad = set(), 0
    for item in feed['items']:
        problems = check(item) if isinstance(item, dict) else ['항목이 객체가 아니다']
        iid = item.get('id') if isinstance(item, dict) else None
        if iid in ids:
            problems.append('id 중복')
        ids.add(iid)
        if problems:
            bad += 1
            if bad <= 10:
                print('🔴 [%s]: %s' % (iid, '; '.join(problems)))
    errors += bad
    items = feed['items']
    print('%s %s %d문항 · 4지 %d · OX %d문항(문장 %d) · 문제 %d건' % (
        '✅' if bad == 0 else '🔴', NAME, len(items),
        sum(1 for it in items if isinstance(it, dict) and it.get('mc')),
        sum(1 for it in items if isinstance(it, dict) and it.get('ox')),
        sum(len(it.get('ox') or []) for it in items if isinstance(it, dict)), bad))
    if errors:
        print('\n🔴 검사 실패 %d건 — 푸시하지 않는다' % errors)
        return 1
    print('\n✅ 검사 통과')
    return 0


if __name__ == '__main__':
    sys.exit(main())
