# -*- coding: utf-8 -*-
"""①초성 · ②일반 문항 생성 → `choseong_2026.json` · `general_2026.json`

🔑 **사전에서 곧바로 생성된다.** 지문 로봇(③달인)을 거치지 않으므로 파이프라인이 다르고,
   그래서 파일도 따로 낸다(KDalin/doc/03 2026-09-17).
🔴 Gemini를 쓰지 않는다 — 국립국어원 API만 쓴다. 한도가 짜지 않고 결과가 흔들리지 않는다.

🔴 **방송 기출을 옮겨 적지 않는다** (CLAUDE.md 1번). 표제어 풀(`wordlist.py`)에서
   뜻풀이를 «조회»해 문항을 만든다.

사용:
  NIKL_API_KEY=... python kdalin/build_quiz.py
"""
import io
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nikl  # noqa: E402
import wordlist  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_CHOSEONG = os.path.join(ROOT, 'choseong_2026.json')
OUT_GENERAL = os.path.join(ROOT, 'general_2026.json')

CHO_BASE = 0xAC00
CHO = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ'

# 🔑 한 번에 새로 만들 개수. 쿼터(하루 50,000건)는 넉넉하지만 실행이 길어지면 실패 반경이 커진다.
NEW_PER_RUN = 12
KEEP_ITEMS = 400

QUESTION_BY_KIND = {
    'definition': '다음 뜻풀이에 해당하는 낱말은?',
    'idiom': '다음 뜻의 관용구는?',
    'proverb': '다음 뜻의 속담은?',
}


def choseong_of(word):
    """🔑 앱은 이 값을 «저장하지 않고» answer에서 유도한다 — 검사용으로만 쓴다."""
    out = []
    for ch in word:
        c = ord(ch)
        out.append(CHO[(c - CHO_BASE) // 588] if CHO_BASE <= c <= 0xD7A3 else ch)
    return ''.join(out)


def load(path):
    if not os.path.exists(path):
        return {'version': 1, 'items': []}
    try:
        return json.load(io.open(path, encoding='utf-8'))
    except ValueError:
        return {'version': 1, 'items': []}


def save(path, items):
    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump({'version': 1, 'items': items[-KEEP_ITEMS:]}, f,
                  ensure_ascii=False, indent=2)
        f.write('\n')


# ── ① 초성 ──────────────────────────────────────────────────────────────────

def build_choseong(key, words, pool):
    """🔴 4지선다의 보기는 **초성이 전부 같아야** 한다 — 앱의 `QuizValidation`이 막는다.

    🔑 초성이 같은 낱말을 넷 모으기는 어렵다. 못 모으면 **주관식**으로 낸다 —
    방송의 초성 문제도 주관식에 가깝고, 앱에서는 그게 「어려움」 난이도가 된다.
    """
    made = []
    by_cho = {}
    for w in pool:
        by_cho.setdefault(choseong_of(w), []).append(w)

    for word in words:
        got = nikl.definition_of(key, word)
        if not got:
            print('  ↪ 사전에 없다: %s' % word)
            continue
        cho = choseong_of(word)
        same = [w for w in by_cho.get(cho, []) if w != word]
        choices = sorted([word] + same[:3]) if len(same) >= 3 else []
        made.append({
            'id': 'cho-%s' % word,
            'answer': word,
            'definition': got['definition'],       # 🔴 원문 그대로
            'link': got['link'],
            'pos': got['pos'],
            'choices': choices,
            'accepted': [],
            'level': 'normal',
        })
        print('  ✅ %-6s %s  %s' % (word, cho, '4지선다' if choices else '주관식'))
    return made


# ── ② 일반 ──────────────────────────────────────────────────────────────────

def build_general_definitions(key, words, pool_defs):
    """뜻풀이 → 낱말. 🔴 제시문에 정답이 그대로 들어 있으면 답이 보인다 → 버린다."""
    made = []
    for word in words:
        got = nikl.definition_of(key, word)
        if not got:
            continue
        prompt = got['definition']
        if word in prompt:
            print('  ↪ 제시문에 정답이 들어 있다: %s' % word)
            continue
        others = [w for w in pool_defs if w != word][:3]
        if len(others) < 3:
            continue
        made.append({
            'id': 'gen-def-%s' % word,
            'kind': 'definition',
            'question': QUESTION_BY_KIND['definition'],
            'prompt': prompt,                       # 🔴 원문 그대로
            'answer': word,
            'choices': sorted([word] + others),
            'definition': prompt,
            'link': got['link'],
            'rule': '',
            'note': '',
            'level': 'normal',
        })
        print('  ✅ 뜻풀이 %-6s' % word)
    return made


def build_general_relations(key, heads, kind, rng):
    """🔑 관용구·속담은 **검색이 안 된다** — 표제어 상세의 `relation_info`에 있다."""
    made = []
    for head in heads:
        got, _ = nikl.relations(key, head, kind)
        usable = [r for r in got if r['definition'] and r['word']]
        if len(usable) < 4:
            print('  ↪ %s: %s가 %d개뿐' % (head, kind, len(usable)))
            continue
        answer = usable[0]
        distractors = [r['word'] for r in usable[1:4]]
        # 🔴 뜻풀이에 정답 표현이 그대로 들어 있으면 답이 보인다
        if answer['word'] in answer['definition']:
            continue
        made.append({
            'id': 'gen-%s-%s' % ('idiom' if kind == '관용구' else 'proverb', head),
            'kind': 'idiom' if kind == '관용구' else 'proverb',
            'question': QUESTION_BY_KIND['idiom' if kind == '관용구' else 'proverb'],
            'prompt': answer['definition'],          # 🔴 원문 그대로
            'answer': answer['word'],
            'choices': sorted([answer['word']] + distractors),
            'definition': answer['definition'],
            'link': answer['link'],
            'rule': '',
            'note': '',
            'level': 'normal',
        })
        print('  ✅ %s %-4s → %s' % (kind, head, answer['word']))
    return made


def main():
    key = nikl.read_key()
    rng = random.Random(os.environ.get('KDALIN_SEED', ''))

    pool = wordlist.dedup(wordlist.WORDS)

    # ── ① 초성 ──
    cho_feed = load(OUT_CHOSEONG)
    done_cho = {it['id'] for it in cho_feed['items']}
    todo = [w for w in pool if 'cho-%s' % w not in done_cho][:NEW_PER_RUN]
    print('① 초성 — 새로 만들 것 %d개' % len(todo))
    cho_new = build_choseong(key, todo, pool) if todo else []

    # ── ② 일반 ──
    gen_feed = load(OUT_GENERAL)
    done_gen = {it['id'] for it in gen_feed['items']}
    gen_new = []

    def_todo = [w for w in pool if 'gen-def-%s' % w not in done_gen][: NEW_PER_RUN // 2]
    if def_todo:
        print('② 일반 — 뜻풀이 %d개' % len(def_todo))
        gen_new += build_general_definitions(key, def_todo, pool)

    for kind, prefix in (('관용구', 'idiom'), ('속담', 'proverb')):
        heads = [h for h in wordlist.RELATION_HEADS
                 if 'gen-%s-%s' % (prefix, h) not in done_gen][: NEW_PER_RUN // 4]
        if heads:
            print('② 일반 — %s %d개' % (kind, len(heads)))
            gen_new += build_general_relations(key, heads, kind, rng)

    if cho_new:
        save(OUT_CHOSEONG, cho_feed['items'] + cho_new)
    if gen_new:
        save(OUT_GENERAL, gen_feed['items'] + gen_new)

    print('\n① 초성  새로 %2d개 · 전체 %d개' % (len(cho_new), len(cho_feed['items']) + len(cho_new)))
    print('② 일반  새로 %2d개 · 전체 %d개' % (len(gen_new), len(gen_feed['items']) + len(gen_new)))
    # 🔑 아무것도 못 만들어도 «실패»는 아니다 — 풀을 다 쓴 것일 수 있다.
    return 0


if __name__ == '__main__':
    sys.exit(main())
